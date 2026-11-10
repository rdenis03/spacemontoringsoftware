"""The pipeline: the one place where all modules are connected.

    sources ──ingest──▶ store ──context──▶ baseline ─▶ detector ─▶ scorer ─▶ actions
                                                                               │
                         API / dashboard ◀──────────── store ◀──save_day───────┘

Three guarantees the rest of the team can rely on:

1. **Modules never call each other.** Each gets its inputs from the pipeline
   and returns a value. Any module can be replaced on its own.
2. **One failing module does not stop the system.** If, say, the detector
   crashes, the day is still scored with what is available and the error is
   recorded in ``DayResult.errors``. Health monitoring must degrade, not die.
3. **Re-running is safe.** Assessing the same astronaut and moment again
   replaces the earlier result, so the team can change a module and re-run.

Other code can react to the pipeline without changing it, through hooks::

    pipeline.on("assessed", lambda result: print(result.assessment.level))
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from orbit.schema import Baseline, RowError

from .config import Settings
from .interfaces import (
    ActionEngine,
    AnomalyDetector,
    AssessmentContext,
    BaselineEngine,
    DataSource,
    DayResult,
    EarthPacket,
    RiskScorer,
    SourceBatch,
    SyncGate,
)
from .registry import create
from .store import Store

log = logging.getLogger("orbit.pipeline")

HOOKS = ("ingested", "assessed")


@dataclass
class IngestReport:
    source_name: str
    crew: int = 0
    observations: int = 0
    events: int = 0
    errors: list[RowError] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.source_name}: {self.crew} crew, {self.observations} observations, "
                f"{self.events} events, {len(self.errors)} rejected")


@dataclass
class RunReport:
    assessed: int = 0
    failed_stages: int = 0
    by_level: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    results: list[DayResult] = field(default_factory=list)

    def summary(self) -> str:
        levels = ", ".join(f"{n} {lvl}" for lvl, n in sorted(self.by_level.items()))
        return f"{self.assessed} assessments ({levels or 'none'}), {self.failed_stages} stage errors"


class Pipeline:
    def __init__(
        self,
        store: Store,
        *,
        baseline: BaselineEngine,
        detector: AnomalyDetector,
        scorer: RiskScorer,
        actions: ActionEngine,
        sync: SyncGate,
        baseline_window_days: int = 14,
        recent_days: int = 3,
        event_lookback_days: int = 7,
        assessment_hour_utc: int = 10,
        module_names: dict[str, str] | None = None,
    ):
        self.store = store
        self.baseline = baseline
        self.detector = detector
        self.scorer = scorer
        self.actions = actions
        self.sync = sync
        self.baseline_window_days = baseline_window_days
        self.recent_days = recent_days
        self.event_lookback_days = event_lookback_days
        self.assessment_hour_utc = assessment_hour_utc
        self.module_names = module_names or {}
        self._hooks: dict[str, list[Callable[[Any], None]]] = {name: [] for name in HOOKS}

    @classmethod
    def from_settings(cls, settings: Settings, store: Store | None = None) -> Pipeline:
        """Build the store and every module chosen in the config."""
        modules = {slot: create(slot, choice.use, **choice.options)
                   for slot, choice in settings.modules.items()}
        return cls(
            store or Store(settings.database),
            **modules,
            baseline_window_days=settings.baseline_window_days,
            recent_days=settings.recent_days,
            event_lookback_days=settings.event_lookback_days,
            assessment_hour_utc=settings.assessment_hour_utc,
            module_names={slot: choice.use for slot, choice in settings.modules.items()},
        )

    # ---- hooks -----------------------------------------------------------

    def on(self, hook: str, callback: Callable[[Any], None]) -> None:
        """Call ``callback`` after every 'ingested' (IngestReport) or 'assessed' (DayResult)."""
        if hook not in self._hooks:
            raise ValueError(f"unknown hook '{hook}'; hooks are: {', '.join(HOOKS)}")
        self._hooks[hook].append(callback)

    def _emit(self, hook: str, payload: Any) -> None:
        for callback in self._hooks[hook]:
            try:
                callback(payload)
            except Exception:  # a broken listener must not break the pipeline
                log.exception("hook '%s' listener failed", hook)

    # ---- ingest ----------------------------------------------------------

    def ingest(self, source: DataSource | SourceBatch) -> IngestReport:
        """Read a source (or a ready batch) and save it. Crew is saved first."""
        batch = source if isinstance(source, SourceBatch) else source.read()
        report = IngestReport(batch.source_name, errors=list(batch.errors))
        report.crew = self.store.upsert_crew(batch.crew)
        known = {m.astronaut_id for m in self.store.crew()}
        accepted = []
        for obs in batch.observations:
            if obs.astronaut_id in known:
                accepted.append(obs)
            else:
                report.errors.append(RowError(0, f"unknown astronaut '{obs.astronaut_id}' "
                                                 f"(observation {obs.observation_id})"))
        report.observations = self.store.add_observations(accepted)
        report.events = self.store.add_events(batch.events)
        self._emit("ingested", report)
        return report

    # ---- assess ----------------------------------------------------------

    def context(self, astronaut_id: str, as_of: datetime) -> AssessmentContext:
        """Snapshot of everything known about one astronaut at ``as_of``."""
        member = self.store.member(astronaut_id)
        if member is None:
            raise KeyError(f"unknown astronaut '{astronaut_id}'")
        as_of = as_of.astimezone(timezone.utc)
        recent_start = as_of - timedelta(days=self.recent_days)
        history_start = recent_start - timedelta(days=self.baseline_window_days)
        readings = self.store.observations(astronaut_id, start=history_start, end=as_of)
        return AssessmentContext(
            member=member,
            as_of=as_of,
            recent_start=recent_start,
            history=tuple(o for o in readings if o.timestamp < recent_start),
            recent=tuple(o for o in readings if o.timestamp >= recent_start),
            events=tuple(self.store.events(
                astronaut_id, start=as_of - timedelta(days=self.event_lookback_days), end=as_of)),
            baseline_window_days=self.baseline_window_days,
            recent_days=self.recent_days,
        )

    def assess(self, astronaut_id: str, as_of: datetime, *, save: bool = True) -> DayResult:
        """Run baseline -> detector -> scorer -> actions for one astronaut at one moment."""
        ctx = self.context(astronaut_id, as_of)
        errors: list[str] = []

        def run_stage(name: str, call: Callable[[], Any], fallback: Any) -> Any:
            try:
                return call()
            except Exception as exc:
                log.exception("%s stage failed for %s at %s", name, astronaut_id, ctx.as_of)
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                return fallback

        baselines: list[Baseline] = run_stage("baseline", lambda: self.baseline.compute(ctx), [])
        by_signal = {b.signal: b for b in baselines}
        anomalies = run_stage("detector", lambda: self.detector.detect(ctx, by_signal), [])
        assessment = run_stage("scorer", lambda: self.scorer.score(ctx, anomalies), None)
        actions = []
        if assessment is not None:
            actions = run_stage("actions", lambda: self.actions.recommend(assessment, ctx), [])

        result = DayResult(
            astronaut_id=astronaut_id, as_of=ctx.as_of, mission_day=ctx.mission_day,
            baselines=tuple(baselines), anomalies=tuple(anomalies), assessment=assessment,
            actions=tuple(actions), errors=tuple(errors),
        )
        if save:
            self.store.save_day(result)
        self._emit("assessed", result)
        return result

    def assessment_time(self, day: date) -> datetime:
        """When the daily assessment runs: after the night's data and morning check-in."""
        return datetime.combine(day, time(self.assessment_hour_utc), tzinfo=timezone.utc)

    def run(
        self,
        start: date | None = None,
        end: date | None = None,
        astronaut_ids: Iterable[str] | None = None,
    ) -> RunReport:
        """Assess every astronaut once per day from ``start`` to ``end`` (inclusive).

        Without dates, covers every day that has data for that astronaut.
        """
        report = RunReport()
        ids = list(astronaut_ids) if astronaut_ids else [m.astronaut_id for m in self.store.crew()]
        for astronaut_id in ids:
            span = self.store.data_range(astronaut_id)
            if span is None and (start is None or end is None):
                continue
            first = start or span[0].date()
            last = end or span[1].date()
            day = first
            while day <= last:
                result = self.assess(astronaut_id, self.assessment_time(day))
                report.assessed += 1
                report.failed_stages += len(result.errors)
                if result.assessment is not None:
                    report.by_level[result.assessment.level.value] += 1
                report.results.append(result)
                day += timedelta(days=1)
        return report

    # ---- read side ---------------------------------------------------------

    def status(self, astronaut_id: str) -> DayResult | None:
        """The latest saved assessment with its actions and anomalies."""
        member = self.store.member(astronaut_id)
        if member is None:
            raise KeyError(f"unknown astronaut '{astronaut_id}'")
        assessment = self.store.latest_assessment(astronaut_id)
        if assessment is None:
            return None
        as_of = assessment.assessed_at
        return DayResult(
            astronaut_id=astronaut_id,
            as_of=as_of,
            mission_day=member.mission_day(as_of),
            baselines=tuple(self.store.baselines(astronaut_id, start=as_of, end=as_of)),
            anomalies=tuple(self.store.anomalies_at(astronaut_id, as_of)),
            assessment=assessment,
            actions=tuple(self.store.recommendations(assessment.assessment_id)),
        )

    def earth_packet(self, astronaut_id: str, start: datetime, end: datetime) -> EarthPacket:
        """What may be sent to Earth for this period, after the consent filter."""
        member = self.store.member(astronaut_id)
        if member is None:
            raise KeyError(f"unknown astronaut '{astronaut_id}'")
        return self.sync.package(
            member,
            self.store.observations(astronaut_id, start=start, end=end, usable_only=False),
            self.store.assessments(astronaut_id, start=start, end=end),
        )
