"""Module slots: what each pluggable module must provide.

The pipeline only ever talks to these interfaces, never to a concrete module.
That is what lets each teammate build their module on their own: as long as
it has the method below, it plugs in.

    Slot        Team module          Must provide
    ----------  -------------------  --------------------------------------------
    source      M2, M3, M5           read() -> SourceBatch
    baseline    M6                   compute(ctx) -> list[Baseline]
    detector    M7                   detect(ctx, baselines) -> list[Anomaly]
    scorer      M8                   score(ctx, anomalies) -> RiskAssessment
    actions     M10                  recommend(assessment, ctx) -> list[ActionCard]
    sync        M13                  package(member, observations, assessments) -> EarthPacket
    extractor   M15                  extract(report, ctx) -> list[SymptomFinding]
    reasoner    M15                  rank(evidence, ctx) -> list[PatternScore]
                                     next_question(evidence, ranking, ctx) -> TriageQuestion | None

Data flows one way: sources -> store -> baseline -> detector -> scorer -> actions.
The two M15 slots are used only by the triage service (``orbit/triage/``),
never by the daily pipeline; they are configured under ``[triage]``.
Each analytics stage gets an ``AssessmentContext``: a read-only snapshot of
everything known about one astronaut at one moment. Modules never query the
database themselves, which keeps them pure, fast and easy to test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from orbit.schema import (
    ActionCard,
    Anomaly,
    Baseline,
    ContextEvent,
    CrewMember,
    Observation,
    PatternScore,
    RiskAssessment,
    RowError,
    SignalCategory,
    SignalType,
    SymptomFinding,
    SymptomReport,
    TriageAnswer,
    TriageQuestion,
)

# --------------------------------------------------------------------------
# Data passed between stages
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceBatch:
    """What a data source hands to the pipeline."""

    source_name: str
    crew: tuple[CrewMember, ...] = ()
    observations: tuple[Observation, ...] = ()
    events: tuple[ContextEvent, ...] = ()
    errors: tuple[RowError, ...] = ()


@dataclass(frozen=True)
class AssessmentContext:
    """Everything known about one astronaut at one moment.

    Time windows, oldest to newest::

        |------ history (baseline window) ------|--- recent ---| as_of
                                                 ^ recent_start

    ``history`` deliberately stops where ``recent`` begins, so an illness that
    started two days ago does not leak into the astronaut's "normal".
    Both contain only usable readings (quality is not BAD), sorted by time.
    """

    member: CrewMember
    as_of: datetime
    recent_start: datetime
    history: tuple[Observation, ...]
    recent: tuple[Observation, ...]
    events: tuple[ContextEvent, ...]
    baseline_window_days: int
    recent_days: int

    @property
    def astronaut_id(self) -> str:
        return self.member.astronaut_id

    @property
    def mission_day(self) -> int:
        return self.member.mission_day(self.as_of)

    def history_for(self, signal: SignalType | str) -> list[Observation]:
        signal = SignalType(signal)
        return [o for o in self.history if o.signal is signal]

    def recent_for(self, signal: SignalType | str) -> list[Observation]:
        signal = SignalType(signal)
        return [o for o in self.recent if o.signal is signal]

    def latest(self, signal: SignalType | str, within: timedelta | None = None) -> Observation | None:
        """Most recent reading of a signal, optionally only if newer than ``within``."""
        readings = self.recent_for(signal)
        if not readings:
            return None
        newest = readings[-1]
        if within is not None and newest.timestamp < self.as_of - within:
            return None
        return newest

    def recent_in(self, category: SignalCategory) -> list[Observation]:
        return [o for o in self.recent if o.category is category]


class DayResult(BaseModel):
    """Everything the analytics produced for one astronaut at one moment."""

    model_config = ConfigDict(frozen=True)

    astronaut_id: str
    as_of: datetime
    mission_day: int
    baselines: tuple[Baseline, ...] = ()
    anomalies: tuple[Anomaly, ...] = ()
    assessment: RiskAssessment | None = None
    actions: tuple[ActionCard, ...] = ()
    errors: tuple[str, ...] = Field(
        default=(), description="Stages that failed; the rest of the result is still valid."
    )


class EarthPacket(BaseModel):
    """What leaves the spacecraft for the flight surgeon, after the consent filter."""

    model_config = ConfigDict(frozen=True)

    astronaut_id: str
    created_at: datetime
    observations: tuple[Observation, ...] = ()
    assessments: tuple[RiskAssessment, ...] = ()
    withheld: dict[str, int] = Field(
        default_factory=dict, description="Readings kept onboard, counted per category."
    )


@dataclass(frozen=True)
class TriageEvidence:
    """What a triage reasoner (M15) knows at one turn of a chat.

    ``findings`` already include what the answers said about symptoms (the
    triage service merges each symptom answer in), so a reasoner reads
    symptoms from ``findings`` and uses ``answers`` for the other questions.
    ``preview`` and ``anomalies`` come from ``pipeline.assess(as_of, save=False)``.
    """

    findings: tuple[SymptomFinding, ...] = ()
    answers: tuple[TriageAnswer, ...] = ()
    asked: tuple[str, ...] = ()  # question ids already asked (answered or skipped)
    preview: RiskAssessment | None = None  # assess(save=False) at the session's as_of
    anomalies: tuple[Anomaly, ...] = ()


# --------------------------------------------------------------------------
# Slots
# --------------------------------------------------------------------------


@runtime_checkable
class DataSource(Protocol):
    """M2 simulator, M3 ingestion, M5 space weather."""

    def read(self) -> SourceBatch: ...


@runtime_checkable
class BaselineEngine(Protocol):
    """M6: learn each astronaut's personal normal from ``ctx.history``."""

    def compute(self, ctx: AssessmentContext) -> list[Baseline]: ...


@runtime_checkable
class AnomalyDetector(Protocol):
    """M7: compare ``ctx.recent`` with the baselines."""

    def detect(
        self, ctx: AssessmentContext, baselines: Mapping[SignalType, Baseline]
    ) -> list[Anomaly]: ...


@runtime_checkable
class RiskScorer(Protocol):
    """M8: combine anomalies, symptoms, lab results and events into one score."""

    def score(self, ctx: AssessmentContext, anomalies: Sequence[Anomaly]) -> RiskAssessment: ...


@runtime_checkable
class ActionEngine(Protocol):
    """M10: turn an assessment into concrete action cards."""

    def recommend(self, assessment: RiskAssessment, ctx: AssessmentContext) -> list[ActionCard]: ...


@runtime_checkable
class SyncGate(Protocol):
    """M13: decide what may leave the spacecraft, following the astronaut's consent."""

    def package(
        self,
        member: CrewMember,
        observations: Sequence[Observation],
        assessments: Sequence[RiskAssessment],
    ) -> EarthPacket: ...


@runtime_checkable
class SymptomExtractor(Protocol):
    """M15: turn the astronaut's own words into symptom findings. Pure."""

    def extract(self, report: SymptomReport, ctx: AssessmentContext) -> list[SymptomFinding]: ...


@runtime_checkable
class TriageReasoner(Protocol):
    """M15: rank the patterns and choose the next follow-up question. Pure.

    ``rank`` returns every ``TriagePattern`` once, probabilities summing to 1,
    most likely first. ``next_question`` returns None when no more should be asked.
    """

    def rank(self, evidence: TriageEvidence, ctx: AssessmentContext) -> list[PatternScore]: ...

    def next_question(
        self, evidence: TriageEvidence, ranking: Sequence[PatternScore], ctx: AssessmentContext
    ) -> TriageQuestion | None: ...


SLOTS: dict[str, type] = {
    "source": DataSource,
    "baseline": BaselineEngine,
    "detector": AnomalyDetector,
    "scorer": RiskScorer,
    "actions": ActionEngine,
    "sync": SyncGate,
    "extractor": SymptomExtractor,
    "reasoner": TriageReasoner,
}
"""Slot name -> interface. The registry and config use these names."""

__all__ = [
    "SLOTS", "SourceBatch", "AssessmentContext", "DayResult", "EarthPacket", "TriageEvidence",
    "DataSource", "BaselineEngine", "AnomalyDetector", "RiskScorer", "ActionEngine",
    "SyncGate", "SymptomExtractor", "TriageReasoner",
]
