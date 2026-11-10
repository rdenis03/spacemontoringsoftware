"""HTTP API: how the frontend (M11, M12, M14) and live data feeds connect.

The API is a thin layer over the pipeline. It contains no health logic, so the
dashboard and the command line always show exactly the same results.

    GET  /api/health                         is it running, which modules are active
    GET  /api/signals                        signal registry for labels and units
    GET  /api/crew                           crew list
    GET  /api/overview                       latest level for every astronaut (M14)
    GET  /api/crew/{id}/status               latest assessment + reasons + actions (M12)
    GET  /api/crew/{id}/observations         readings for charts (?signal=&start=&end=)
    GET  /api/crew/{id}/baselines            "your normal" band over time (?signal=)
    GET  /api/crew/{id}/assessments          score history for the trend line
    POST /api/crew/{id}/checkin              daily check-in (M11); re-assesses at once
    GET  /api/crew/{id}/earth-packet         what would be sent to Earth (M13)
    GET  /api/events                         stress events (solar, EVA ...)
    POST /api/observations                   push readings from a device or feed (M3)
    POST /api/pipeline/run                   re-run the assessments

Interactive docs: http://localhost:8000/docs once the server runs.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from orbit.core.interfaces import DayResult, EarthPacket
from orbit.core.pipeline import Pipeline
from orbit.schema import (
    SCHEMA_VERSION,
    Baseline,
    ContextEvent,
    CrewMember,
    Observation,
    RiskAssessment,
    SignalCategory,
    SignalType,
    get_spec,
    parse_records,
)
from orbit.schema.export import registry_document

# ---- request and response bodies --------------------------------------------


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


class RunRequest(BaseModel):
    start: date | None = None
    end: date | None = None
    astronaut_ids: list[str] | None = None


class RunResponse(BaseModel):
    summary: str
    assessed: int
    by_level: dict[str, int]


# ---- app ----------------------------------------------------------------------


def create_app(pipeline: Pipeline, *, mission_name: str = "ORBIT mission") -> FastAPI:
    app = FastAPI(
        title="ORBIT API",
        version=SCHEMA_VERSION,
        description="Immune early-warning system for long-duration space missions.",
    )
    # Open CORS so the frontend dev server (any port) can call the API.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    app.state.pipeline = pipeline
    store = pipeline.store

    def member_or_404(astronaut_id: str) -> CrewMember:
        member = store.member(astronaut_id)
        if member is None:
            raise HTTPException(404, f"unknown astronaut '{astronaut_id}'")
        return member

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "mission": mission_name, "schema_version": SCHEMA_VERSION,
                "modules": pipeline.module_names, "counts": store.counts()}

    @app.get("/api/signals")
    def signals() -> dict[str, Any]:
        return registry_document()

    @app.get("/api/crew")
    def crew() -> list[CrewMember]:
        return store.crew()

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
            ))
        return rows

    @app.get("/api/crew/{astronaut_id}/status")
    def status(astronaut_id: str) -> DayResult:
        member_or_404(astronaut_id)
        result = pipeline.status(astronaut_id)
        if result is None:
            raise HTTPException(404, "no assessment yet; run the pipeline first")
        return result

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

    return app


def _utc(value: datetime | None) -> datetime | None:
    """Query-string times without a timezone are taken as UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def create_app_from_settings(config_path: str | None = None) -> FastAPI:
    """Factory for uvicorn: ``uvicorn orbit.api.app:create_app_from_settings --factory``."""
    from orbit.core.config import load_settings

    settings = load_settings(config_path)
    return create_app(Pipeline.from_settings(settings), mission_name=settings.mission_name)
