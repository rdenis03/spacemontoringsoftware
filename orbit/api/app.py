"""HTTP API: how the frontend (M11, M12, M14) and live data feeds connect.

The API is a thin layer over the pipeline. It contains no health logic, so the
dashboard and the command line always show exactly the same results.

    GET  /api/health                         is it running, which modules are active
    GET  /api/signals                        signal registry for labels and units
    GET  /api/crew                           crew list
    PUT  /api/crew/{id}/consent              which categories may go to Earth (M13)
    GET  /api/overview                       latest level for every astronaut (M14)
    GET  /api/crew/{id}/status               latest assessment + reasons + actions (M12)
                                             ?view=shared: what the crew may see (M14)
    GET  /api/crew/{id}/day?as_of=           the same for any past assessment (replay),
                                             also with ?view=shared
    GET  /api/crew/{id}/observations         readings for charts (?signal=&start=&end=)
    GET  /api/crew/{id}/baselines            "your normal" band over time (?signal=)
    GET  /api/crew/{id}/assessments          score history for the trend line
    POST /api/crew/{id}/checkin              daily check-in (M11); re-assesses at once
    GET  /api/crew/{id}/earth-packet         what would be sent to Earth (M13)
    POST /api/crew/{id}/earth-packet/send    package and queue for Earth with the comms delay (M13);
                                             adds a one-line report for the flight surgeon
    GET  /api/outbox                         queued and delivered packets (M13)
                                             (``auto``: queued by ORBIT itself on orange or red)
    GET  /api/events                         stress events (solar, EVA ...)
    POST /api/observations                   push readings from a device or feed (M3)
    POST /api/pipeline/run                   re-run the assessments

    Symptom triage, the chat check-in (M15; the astronaut's own view only):
    POST /api/crew/{id}/triage                         {text, timestamp?} -> TriageResult
    POST /api/crew/{id}/triage/{session_id}/answer     {question_id, value}, {text} or {done} -> TriageResult
    POST /api/crew/{id}/triage/{session_id}/confirm    {corrections?} -> {result, day}; saves a check-in
    POST /api/crew/{id}/triage/{session_id}/cancel     -> TriageSession; saves nothing
    GET  /api/crew/{id}/triage/{session_id}            -> TriageSession
    GET  /api/crew/{id}/triage?start=&end=             -> TriageSession[], newest first

Interactive docs: http://localhost:8000/docs once the server runs.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StrictInt

from orbit.core.interfaces import DayResult, EarthPacket
from orbit.core.pipeline import Pipeline
from orbit.core.store import OutboxEntry
from orbit.schema import (
    SCHEMA_VERSION,
    ActionCard,
    AlertLevel,
    Baseline,
    ContextEvent,
    CrewMember,
    Observation,
    RiskAssessment,
    SignalCategory,
    SignalType,
    TriageResult,
    TriageSession,
    get_spec,
    parse_records,
)
from orbit.schema.export import registry_document
from orbit.triage.service import (
    BadAnswer,
    SessionClosed,
    SessionNotFound,
    TriageService,
    UnknownAstronaut,
)

from .earth_report import build_report

log = logging.getLogger("orbit.api")

AUTO_SEND_DAYS = 3
"""An auto packet covers this many days up to the assessment (B18)."""

# ---- request and response bodies --------------------------------------------

View = Literal["full", "shared"]
"""``full``: everything (the astronaut's own view). ``shared``: what the crew may see."""

# Shared view: what replaces an action card that is triggered by a private signal.
PRIVATE_CARD_TITLE = "Private action"
PRIVATE_CARD_STEP = "Details kept private by the astronaut"
PRIVATE_CARD_RATIONALE = "The astronaut has not shared the reasons for this step."


class CheckIn(BaseModel):
    """The astronaut's daily check-in. Symptoms use the 0-3 scale, mood/stress 1-5."""

    timestamp: datetime | None = Field(
        default=None, description="When the check-in was made (with timezone). Default: now."
    )
    symptoms: dict[SignalType, int] = Field(
        default_factory=dict, examples=[{"symptom_fatigue": 2, "symptom_rash_tingling": 1}]
    )
    mood: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    errors: list[str]


class OverviewRow(BaseModel):
    astronaut_id: str
    callsign: str
    level: str | None
    score: float | None
    assessed_at: datetime | None
    red_flag_at: datetime | None = Field(
        default=None, description="Mission time of the latest triage red flag in the last 24 h "
                                  "(real time); no details (M15).")


class TriageStart(BaseModel):
    """The first message of a triage chat, in the astronaut's own words (M15)."""

    text: str = Field(min_length=1, max_length=1000,
                      examples=["Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."])
    timestamp: datetime | None = Field(
        default=None, description="The moment assessed (mission time in the demo). Default: now.")


class TriageReply(BaseModel):
    """Answer the open question (value null skips it), add text, and/or say that's all."""

    question_id: str | None = Field(default=None, examples=["rash-tingling"])
    value: bool | int | float | str | None = Field(default=None, examples=["moderate"])
    text: str | None = Field(default=None, max_length=1000)
    done: bool = False


Severity = Annotated[StrictInt, Field(ge=0, le=3)]
"""A whole number 0-3. Booleans, strings and floats are refused (422)."""


class TriageConfirm(BaseModel):
    """Optional corrections before saving: symptom signal -> severity 0-3."""

    corrections: dict[SignalType, Severity] | None = Field(
        default=None, examples=[{"symptom_rash_tingling": 2}])


NO_SHARED_TRIAGE = "Triage sessions have no shared view"


def no_shared_view(view: str | None = Query(default=None, include_in_schema=False)) -> None:
    """Triage holds the astronaut's own words: it has no shared view, and asking for one is an error."""
    if view is not None:
        raise HTTPException(400, NO_SHARED_TRIAGE)


class TriageConfirmed(BaseModel):
    """The confirmed chat and the new assessment, with the chat's cards.

    ``day`` is null when a red flag in an invalid confirm escalated the chat instead.
    """

    result: TriageResult
    day: DayResult | None = None


class ConsentUpdate(BaseModel):
    """The categories the astronaut shares with Earth. An empty list shares nothing."""

    share_with_earth: list[SignalCategory] = Field(examples=[["vital", "sleep"]])


class OutboxItem(BaseModel):
    """An outbox entry with its delivery status right now (B16)."""

    id: str
    astronaut_id: str
    created_at: datetime
    deliver_at: datetime
    packet: EarthPacket
    summary: str = ""
    auto: bool = False
    status: Literal["queued", "delivered"]
    seconds_left: float = Field(description="Seconds until delivery; 0 once delivered.")
    sent: dict[str, int] = Field(description="Readings sent, per category.")
    withheld: dict[str, int] = Field(description="Readings kept onboard, per category.")


class RunRequest(BaseModel):
    start: date | None = None
    end: date | None = None
    astronaut_ids: list[str] | None = None


class RunResponse(BaseModel):
    summary: str
    assessed: int
    by_level: dict[str, int]


# ---- app ----------------------------------------------------------------------


def create_app(
    pipeline: Pipeline,
    *,
    mission_name: str = "ORBIT mission",
    comms_delay_minutes: float = 20.0,
    clock: Callable[[], datetime] | None = None,
    auto_send_level: str = "off",
    triage: TriageService | None = None,
) -> FastAPI:
    """Build the API. ``clock`` (UTC) drives the comms queue; tests pass a fixed one.

    Comms delay is real time, not mission time, so the demo countdown is visible.

    ``auto_send_level`` ("yellow", "orange", "red" or "off"; B18): when an
    assessment reaches this level, ORBIT queues a packet for Earth by itself,
    at most one per astronaut per assessment day. The default here is "off";
    ``serve`` passes ``[comms] auto_send_level`` from orbit.toml (default "orange").

    ``triage`` (M15): the chat check-in service. Without one, a service with
    the built-in starters and the same ``clock`` is used; ``serve`` passes one
    built from ``[triage]`` in orbit.toml.
    """
    auto_level = None if auto_send_level == "off" else AlertLevel(auto_send_level)
    now = clock or (lambda: datetime.now(timezone.utc))
    triage = triage if triage is not None else TriageService(pipeline, clock=now)
    app = FastAPI(
        title="ORBIT API",
        version=SCHEMA_VERSION,
        description="Immune early-warning system for long-duration space missions.",
    )
    # Open CORS so the frontend dev server (any port) can call the API.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    app.state.pipeline = pipeline
    app.state.triage = triage
    store = pipeline.store

    def member_or_404(astronaut_id: str) -> CrewMember:
        member = store.member(astronaut_id)
        if member is None:
            raise HTTPException(404, f"unknown astronaut '{astronaut_id}'")
        return member

    def shared_view(result: DayResult, member: CrewMember) -> DayResult:
        """What the commander and crew medical officer may see (M14).

        Reasons go through the sync slot's consent gate (private ones get its
        neutral label); anomalies and baselines of categories the astronaut does
        not share are dropped. Score and level stay. An action card is shown in
        full only if all its triggers are shared (cards without triggers always
        are); otherwise it keeps its level and escalate_to but its text and ID
        are replaced, so the steps cannot give a private symptom away.
        """
        assessment = result.assessment
        if assessment is not None:
            [assessment] = pipeline.sync.package(member, [], [assessment]).assessments

        def shared(signal: SignalType) -> bool:
            return member.shares(get_spec(signal).category)

        cards, hidden = [], 0
        for card in result.actions:
            if all(shared(signal) for signal in card.triggers):
                cards.append(card)
                continue
            hidden += 1
            cards.append(ActionCard(
                card_id=f"private-{hidden}", level=card.level, title=PRIVATE_CARD_TITLE,
                steps=(PRIVATE_CARD_STEP,), rationale=PRIVATE_CARD_RATIONALE,
                escalate_to=card.escalate_to,
            ))

        return result.model_copy(update={
            "assessment": assessment,
            "anomalies": tuple(a for a in result.anomalies if shared(a.signal)),
            "baselines": tuple(b for b in result.baselines if shared(b.signal)),
            "actions": tuple(cards),
        })

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "mission": mission_name, "schema_version": SCHEMA_VERSION,
                "modules": pipeline.module_names, "counts": store.counts(),
                "comms": {"one_way_delay_minutes": comms_delay_minutes,
                          "auto_send_level": auto_send_level},
                "triage": {"modules": triage.module_names, "model_version": triage.model_version}}

    @app.get("/api/signals")
    def signals() -> dict[str, Any]:
        return registry_document()

    @app.get("/api/crew")
    def crew() -> list[CrewMember]:
        return store.crew()

    @app.put("/api/crew/{astronaut_id}/consent")
    def consent(astronaut_id: str, body: ConsentUpdate) -> CrewMember:
        """Change which kinds of data may leave the spacecraft.

        Readings of other categories stay onboard. Score and level are always
        sent (the consent gate's rule), so a hidden emergency is impossible.
        """
        member = member_or_404(astronaut_id)
        updated = CrewMember.model_validate(
            {**member.model_dump(), "share_with_earth": body.share_with_earth})
        store.upsert_crew([updated])
        return updated

    @app.get("/api/overview")
    def overview() -> list[OverviewRow]:
        rows = []
        for member in store.crew():
            latest = store.latest_assessment(member.astronaut_id)
            rows.append(OverviewRow(
                astronaut_id=member.astronaut_id, callsign=member.callsign,
                level=latest.level.value if latest else None,
                score=latest.score if latest else None,
                assessed_at=latest.assessed_at if latest else None,
                red_flag_at=triage.red_flag_at(member.astronaut_id),
            ))
        return rows

    @app.get("/api/crew/{astronaut_id}/status")
    def status(astronaut_id: str, view: View = "full") -> DayResult:
        member = member_or_404(astronaut_id)
        result = pipeline.status(astronaut_id)
        if result is None:
            raise HTTPException(404, "no assessment yet; run the pipeline first")
        return shared_view(result, member) if view == "shared" else result

    @app.get("/api/crew/{astronaut_id}/day")
    def day(
        astronaut_id: str,
        as_of: datetime = Query(
            description="An `assessed_at` value from /assessments. No timezone means UTC.",
            examples=["2027-04-02T10:00:00Z"],
        ),
        view: View = "full",
    ) -> DayResult:
        """The full saved result of one past assessment, for the mission replay slider."""
        member = member_or_404(astronaut_id)
        when = _utc(as_of)
        found = store.assessments(astronaut_id, start=when, end=when)
        if not found:
            raise HTTPException(
                404, f"no assessment for '{astronaut_id}' at {when.isoformat()}; "
                     "use an assessed_at value from /assessments")
        assessment = found[0]
        when = assessment.assessed_at
        result = DayResult(
            astronaut_id=astronaut_id,
            as_of=when,
            mission_day=member.mission_day(when),
            baselines=tuple(store.baselines(astronaut_id, start=when, end=when)),
            anomalies=tuple(store.anomalies_at(astronaut_id, when)),
            assessment=assessment,
            actions=tuple(store.recommendations(assessment.assessment_id)),
        )
        return shared_view(result, member) if view == "shared" else result

    @app.get("/api/crew/{astronaut_id}/observations")
    def observations(
        astronaut_id: str,
        signal: list[SignalType] | None = Query(default=None),
        start: datetime | None = None,
        end: datetime | None = None,
        include_bad: bool = False,
    ) -> list[Observation]:
        member_or_404(astronaut_id)
        return store.observations(astronaut_id, signals=signal, start=_utc(start),
                                  end=_utc(end), usable_only=not include_bad)

    @app.get("/api/crew/{astronaut_id}/baselines")
    def baselines(
        astronaut_id: str,
        signal: SignalType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Baseline]:
        member_or_404(astronaut_id)
        return store.baselines(astronaut_id, signal=signal, start=_utc(start), end=_utc(end))

    @app.get("/api/crew/{astronaut_id}/assessments")
    def assessments(
        astronaut_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[RiskAssessment]:
        member_or_404(astronaut_id)
        return store.assessments(astronaut_id, start=_utc(start), end=_utc(end))

    @app.post("/api/crew/{astronaut_id}/checkin")
    def checkin(astronaut_id: str, body: CheckIn) -> DayResult:
        member_or_404(astronaut_id)
        when = _utc(body.timestamp) or datetime.now(timezone.utc)
        records = [
            {"signal": signal, "value": value}
            for signal, value in body.symptoms.items()
        ]
        if body.mood is not None:
            records.append({"signal": SignalType.MOOD, "value": body.mood})
        if body.stress is not None:
            records.append({"signal": SignalType.STRESS, "value": body.stress})
        stamp = when.strftime("%Y%m%dT%H%M%S")
        records = [
            {**r, "astronaut_id": astronaut_id, "timestamp": when, "source": "checkin",
             "observation_id": f"{astronaut_id}-{r['signal'].value}-{stamp}",
             "note": body.note}
            for r in records
        ]
        for r in records:
            if get_spec(r["signal"]).category not in (SignalCategory.SYMPTOM,
                                                      SignalCategory.WELLBEING):
                raise HTTPException(422, f"{r['signal'].value} is not a check-in signal")
        parsed = parse_records(records)
        if not parsed.ok:
            raise HTTPException(422, [str(e) for e in parsed.errors])
        store.add_observations(parsed.valid)
        return pipeline.assess(astronaut_id, when)

    @app.get("/api/crew/{astronaut_id}/earth-packet")
    def earth_packet(astronaut_id: str, start: datetime, end: datetime) -> EarthPacket:
        member_or_404(astronaut_id)
        return pipeline.earth_packet(astronaut_id, _utc(start), _utc(end))

    def outbox_item(entry: OutboxEntry) -> OutboxItem:
        left = (entry.deliver_at - now()).total_seconds()
        sent: dict[str, int] = {}
        for obs in entry.packet.observations:
            sent[obs.category.value] = sent.get(obs.category.value, 0) + 1
        return OutboxItem(
            **entry.model_dump(exclude={"packet"}), packet=entry.packet,
            status="delivered" if left <= 0 else "queued", seconds_left=max(0.0, left),
            sent=sent, withheld=dict(entry.packet.withheld),
        )

    @app.post("/api/crew/{astronaut_id}/earth-packet/send")
    def send_earth_packet(
        astronaut_id: str,
        start: datetime,
        end: datetime,
        delay_minutes: float | None = Query(
            default=None, ge=0, le=24 * 60,
            description="One-way delay for this packet: Moon about 0.02, Mars 4-24. "
                        "Default: [comms] one_way_delay_minutes in orbit.toml.",
        ),
    ) -> OutboxItem:
        """Package the period through the consent gate and queue it for Earth (B16).

        ``summary`` is the plain-language report for the flight surgeon (B17).
        """
        member = member_or_404(astronaut_id)
        start_utc, end_utc = _utc(start), _utc(end)
        if end_utc < start_utc:
            raise HTTPException(422, "end must not be before start")
        delay = comms_delay_minutes if delay_minutes is None else delay_minutes
        created = now()
        packet = pipeline.earth_packet(astronaut_id, start_utc, end_utc)
        # The cards advised with the latest assessment in the packet.
        actions: list[ActionCard] = []
        if packet.assessments:
            latest = max(packet.assessments, key=lambda a: (a.assessed_at, a.assessment_id))
            actions = store.recommendations(latest.assessment_id)
        entry = OutboxEntry(
            id=f"pkt-{uuid.uuid4().hex[:12]}", astronaut_id=astronaut_id,
            created_at=created, deliver_at=created + timedelta(minutes=delay),
            packet=packet, summary=build_report(member, packet, actions),
        )
        store.queue(entry)
        return outbox_item(entry)

    def auto_send(result: DayResult) -> None:
        """Queue a packet for Earth when an assessment reaches ``auto_send_level`` (B18).

        Registered on the pipeline's "assessed" hook and run once at startup.
        One packet per astronaut per assessment day (the UTC date of ``as_of``):
        its id is ``auto-<astronaut>-<yyyymmdd>``, and an id already in the
        outbox is left alone. Never raises: a failed send must not break an
        assessment.
        """
        try:
            assessment = result.assessment
            if auto_level is None or assessment is None:
                return
            if assessment.level.rank < auto_level.rank:
                return
            packet_id = f"auto-{result.astronaut_id}-{result.as_of:%Y%m%d}"
            if any(entry.id == packet_id for entry in store.outbox(result.astronaut_id)):
                return
            member = store.member(result.astronaut_id)
            if member is None:
                return
            packet = pipeline.earth_packet(
                result.astronaut_id, result.as_of - timedelta(days=AUTO_SEND_DAYS), result.as_of)
            if all(a.assessment_id != assessment.assessment_id for a in packet.assessments):
                return  # the assessment was not saved (a preview): nothing to report
            created = now()
            store.queue(OutboxEntry(
                id=packet_id, astronaut_id=result.astronaut_id, created_at=created,
                deliver_at=created + timedelta(minutes=comms_delay_minutes),
                packet=packet, summary=build_report(member, packet, result.actions), auto=True,
            ))
        except Exception:
            log.exception("auto-send failed for %s at %s", result.astronaut_id, result.as_of)

    if auto_level is not None:
        pipeline.on("assessed", auto_send)
        # `serve` assesses before this hook exists, so look at every latest status once.
        try:
            for member in store.crew():
                latest = pipeline.status(member.astronaut_id)
                if latest is not None:
                    auto_send(latest)
        except Exception:
            log.exception("auto-send startup check failed")

    @app.get("/api/outbox")
    def outbox(astronaut_id: str | None = None) -> list[OutboxItem]:
        """Everything sent to Earth, newest first, with ``status`` and ``seconds_left`` now."""
        if astronaut_id is not None:
            member_or_404(astronaut_id)
        return [outbox_item(e) for e in store.outbox(astronaut_id)]

    @app.get("/api/events")
    def events(
        astronaut_id: str | None = None, start: datetime | None = None, end: datetime | None = None
    ) -> list[ContextEvent]:
        return store.events(astronaut_id, start=_utc(start), end=_utc(end))

    @app.post("/api/observations")
    def push_observations(records: list[dict[str, Any]]) -> IngestResponse:
        parsed = parse_records(records)
        known = {m.astronaut_id for m in store.crew()}
        accepted = [o for o in parsed.valid if o.astronaut_id in known]
        errors = [str(e) for e in parsed.errors]
        errors += [f"unknown astronaut '{o.astronaut_id}'" for o in parsed.valid
                   if o.astronaut_id not in known]
        store.add_observations(accepted)
        return IngestResponse(accepted=len(accepted), rejected=len(errors), errors=errors[:50])

    @app.post("/api/pipeline/run")
    def run(body: RunRequest) -> RunResponse:
        report = pipeline.run(body.start, body.end, body.astronaut_ids)
        return RunResponse(summary=report.summary(), assessed=report.assessed,
                           by_level=dict(report.by_level))

    # ---- symptom triage (M15): the astronaut's own view only ------------------------

    def triage_call(astronaut_id: str, session_id: str | None, call: Callable[[], Any]) -> Any:
        """Run a service call with the HTTP errors the frontend expects: 404, 409, 422."""
        member_or_404(astronaut_id)
        try:
            if session_id is not None and triage.session(session_id).astronaut_id != astronaut_id:
                raise SessionNotFound(f"unknown triage session '{session_id}' for '{astronaut_id}'")
            return call()
        except (SessionNotFound, UnknownAstronaut) as exc:
            raise HTTPException(404, str(exc)) from exc
        except SessionClosed as exc:
            raise HTTPException(409, str(exc)) from exc
        except BadAnswer as exc:
            raise HTTPException(422, str(exc)) from exc

    # The triage POST endpoints read the raw body and hand it to the service, which runs
    # the red-flag gate before any validation: FastAPI must not reject a request (422)
    # before the gate has seen it. The models only document the bodies in /docs.

    async def write(request: Request, astronaut_id: str, view: str | None,
                    call: Callable[[Any], Any]) -> Any:
        raw = await _raw_body(request)

        def run() -> Any:
            member_or_404(astronaut_id)
            if view is not None and not triage.screen(raw):  # a flagged body is never refused
                raise HTTPException(400, NO_SHARED_TRIAGE)
            return triage_call(astronaut_id, None, lambda: call(raw))

        return await run_in_threadpool(run)

    hidden_view = Query(default=None, include_in_schema=False)

    @app.post("/api/crew/{astronaut_id}/triage", response_model=TriageResult,
              openapi_extra=_body_doc(TriageStart))
    async def triage_start(astronaut_id: str, request: Request, view: str | None = hidden_view):
        """Start a chat check-in. Nothing is saved as a check-in until confirm."""
        return await write(request, astronaut_id, view, lambda raw: triage.start_raw(astronaut_id, raw))

    @app.post("/api/crew/{astronaut_id}/triage/{session_id}/answer", response_model=TriageResult,
              openapi_extra=_body_doc(TriageReply))
    async def triage_answer(astronaut_id: str, session_id: str, request: Request,
                            view: str | None = hidden_view):
        return await write(request, astronaut_id, view,
                           lambda raw: triage.answer_raw(astronaut_id, session_id, raw))

    @app.post("/api/crew/{astronaut_id}/triage/{session_id}/confirm", response_model=TriageConfirmed,
              openapi_extra=_body_doc(TriageConfirm, required=False))
    async def triage_confirm(astronaut_id: str, session_id: str, request: Request,
                             view: str | None = hidden_view):
        """Save the findings as a check-in, re-assess, and keep the chat's cards with that run.

        If the body carries a red flag but is invalid, the chat is escalated, not
        confirmed: ``result`` is the escalated result and ``day`` is null.
        """
        def confirm(raw: Any) -> TriageConfirmed:
            result, day = triage.confirm_raw(astronaut_id, session_id, raw)
            return TriageConfirmed(result=result, day=day)

        return await write(request, astronaut_id, view, confirm)

    @app.post("/api/crew/{astronaut_id}/triage/{session_id}/cancel", response_model=TriageSession)
    async def triage_cancel(astronaut_id: str, session_id: str, request: Request,
                            view: str | None = hidden_view):
        return await write(request, astronaut_id, view,
                           lambda raw: triage.cancel_raw(astronaut_id, session_id, raw))

    @app.get("/api/crew/{astronaut_id}/triage/{session_id}", dependencies=[Depends(no_shared_view)])
    def triage_session(astronaut_id: str, session_id: str) -> TriageSession:
        return triage_call(astronaut_id, session_id, lambda: triage.session(session_id))

    @app.get("/api/crew/{astronaut_id}/triage", dependencies=[Depends(no_shared_view)])
    def triage_sessions(
        astronaut_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[TriageSession]:
        """This astronaut's chats started (real time) in [start, end], newest first. No shared view."""
        return triage_call(astronaut_id, None,
                           lambda: triage.sessions(astronaut_id, start=_utc(start), end=_utc(end)))

    return app


async def _raw_body(request: Request) -> Any:
    """The request body as parsed JSON, or its text if it is not JSON; None if empty."""
    body = await request.body()
    if not body.strip():
        return None
    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def _body_doc(model: type[BaseModel], required: bool = True) -> dict[str, Any]:
    """Document a raw-body endpoint's JSON body in /docs (it is validated by the service)."""
    return {"requestBody": {"required": required, "content": {
        "application/json": {"schema": model.model_json_schema()}}}}


def _utc(value: datetime | None) -> datetime | None:
    """Query-string times without a timezone are taken as UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def create_app_from_settings(config_path: str | None = None) -> FastAPI:
    """Factory for uvicorn: ``uvicorn orbit.api.app:create_app_from_settings --factory``."""
    from orbit.core.config import load_settings
    from orbit.triage.config import load_triage_settings

    settings = load_settings(config_path)
    pipeline = Pipeline.from_settings(settings)
    return create_app(pipeline, mission_name=settings.mission_name,
                      comms_delay_minutes=settings.comms_delay_minutes,
                      auto_send_level=settings.comms_auto_send_level,
                      triage=TriageService.from_settings(load_triage_settings(settings), pipeline))
