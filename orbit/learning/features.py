"""Feature extraction for the AI scorer (task B07).

Turns one astronaut-day (the context plus the detector's anomalies) into a
fixed list of numbers, each with a plain-language reason. The trainer (B09)
learns one weight per number; the learned scorer (B08) multiplies them back
into points. Both call :func:`extract`, so training and runtime always see the
same features, and every point keeps a reason the astronaut can check.

    Name                    Value
    ----------------------  -------------------------------------------------
    dev:<signal>            min(|deviation|, 3) of that signal's anomaly
                            (7 vital and sleep signals)
    drift:<signal>          1 if that anomaly is a sustained drift
    vitals_moving           number of vital anomalies, when 2 or more
    sym:<signal>            fresh check-in severity 0-3 (8 symptoms)
    dna:<signal>            1 + log10(copies / 100), from 100 copies/mL up
    crp:high                1 if CRP is above 10 mg/L
    stress:high, mood:low   1 if fresh stress >= 4 / mood <= 2
    event:<event_type>      highest severity (low 1 ... extreme 4) among
                            events that started by ``as_of``

Rules: pure (no clock, no I/O, no randomness); the same input gives the same
list in the same order (``FEATURE_NAMES`` order); every feature has ``signal``
or ``event_id`` set. Thresholds are illustrative, not clinical.

``FEATURE_NAMES`` is the contract with B08 and B09: add new features only at
the end of the tuple, then retrain.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from orbit.core.interfaces import AssessmentContext
from orbit.modules.scorer import (
    CHECKIN_FRESHNESS,
    EVENT_NAMES,
    SYMPTOM_WEIGHTS,
    VIRAL_DNA,
    _days_label,
    describe_anomaly,
)
from orbit.schema import (
    Anomaly,
    AnomalyKind,
    ContextEvent,
    EventType,
    Severity,
    SignalCategory,
    SignalType,
    get_spec,
    signals_in,
)

S = SignalType

MAX_DEVIATION = 3.0
VIRAL_DETECTION_LIMIT = 100.0  # copies/mL, same as rule_based
CRP_LIMIT = 10.0  # mg/L, same as rule_based
SEVERITY_RANK = {Severity.LOW: 1, Severity.MODERATE: 2, Severity.HIGH: 3, Severity.EXTREME: 4}

VITAL_SIGNALS: tuple[SignalType, ...] = tuple(spec.signal for spec in signals_in(SignalCategory.VITAL))
NIGHTLY_SIGNALS: tuple[SignalType, ...] = VITAL_SIGNALS + tuple(
    spec.signal for spec in signals_in(SignalCategory.SLEEP)
)
SYMPTOM_SIGNALS: tuple[SignalType, ...] = tuple(SYMPTOM_WEIGHTS)


@dataclass(frozen=True)
class Feature:
    name: str  # stable key, e.g. "dev:skin_temp"
    value: float  # always >= 0
    label: str  # reason shown to the astronaut if it earns points
    signal: SignalType | None = None
    event_id: str | None = None


FEATURE_NAMES: tuple[str, ...] = (
    *(f"dev:{s.value}" for s in NIGHTLY_SIGNALS),
    *(f"drift:{s.value}" for s in NIGHTLY_SIGNALS),
    "vitals_moving",
    *(f"sym:{s.value}" for s in SYMPTOM_SIGNALS),
    *(f"dna:{s.value}" for s in VIRAL_DNA),
    "crp:high",
    "stress:high",
    "mood:low",
    *(f"event:{e.value}" for e in EventType),
)
"""Every name :func:`extract` can return, in a fixed order. Append only."""


def extract(ctx: AssessmentContext, anomalies: Sequence[Anomaly]) -> list[Feature]:
    """Non-zero features for one astronaut-day, in ``FEATURE_NAMES`` order."""
    found: list[Feature] = []
    found += _anomaly_features(anomalies)
    found += _symptom_features(ctx)
    found += _lab_features(ctx)
    found += _wellbeing_features(ctx)
    found += _event_features(ctx)
    order = {name: i for i, name in enumerate(FEATURE_NAMES)}
    return sorted((f for f in found if f.value > 0), key=lambda f: order[f.name])


def vector(features: Iterable[Feature]) -> dict[str, float]:
    """All ``FEATURE_NAMES`` as keys (in order), zeros where a feature is absent."""
    values = {f.name: f.value for f in features}
    unknown = set(values) - set(FEATURE_NAMES)
    if unknown:
        raise ValueError(f"unknown feature names: {sorted(unknown)}")
    return {name: values.get(name, 0.0) for name in FEATURE_NAMES}


# --------------------------------------------------------------------------
# Feature groups
# --------------------------------------------------------------------------


def _anomaly_features(anomalies: Sequence[Anomaly]) -> list[Feature]:
    # One anomaly per signal: if a detector reports several, keep the most deviant.
    strongest: dict[SignalType, Anomaly] = {}
    for anomaly in anomalies:
        if anomaly.signal not in NIGHTLY_SIGNALS:
            continue
        kept = strongest.get(anomaly.signal)
        if kept is None or abs(anomaly.deviation) > abs(kept.deviation):
            strongest[anomaly.signal] = anomaly

    out: list[Feature] = []
    for signal, anomaly in strongest.items():
        label = describe_anomaly(anomaly)
        out.append(Feature(f"dev:{signal.value}", min(abs(anomaly.deviation), MAX_DEVIATION),
                           label, signal=signal))
        if anomaly.kind is AnomalyKind.DRIFT:
            out.append(Feature(f"drift:{signal.value}", 1.0, label, signal=signal))

    vitals = [a for s, a in strongest.items() if s in VITAL_SIGNALS]
    if len(vitals) >= 2:
        lead = max(vitals, key=lambda a: (abs(a.deviation), -VITAL_SIGNALS.index(a.signal)))
        out.append(Feature("vitals_moving", float(len(vitals)),
                           f"{len(vitals)} vital signs moved together", signal=lead.signal))
    return out


def _symptom_features(ctx: AssessmentContext) -> list[Feature]:
    out = []
    for signal in SYMPTOM_SIGNALS:
        latest = ctx.latest(signal, within=CHECKIN_FRESHNESS)
        if latest is None or latest.value <= 0:
            continue
        spec = latest.spec
        out.append(Feature(f"sym:{signal.value}", float(latest.value),
                           f"{spec.label}: {spec.scale_label(latest.value)} in your check-in",
                           signal=signal))
    return out


def _lab_features(ctx: AssessmentContext) -> list[Feature]:
    out = []
    for signal in VIRAL_DNA:
        latest = ctx.latest(signal)
        if latest is None or latest.value < VIRAL_DETECTION_LIMIT:
            continue
        spec = latest.spec
        out.append(Feature(f"dna:{signal.value}",
                           1 + math.log10(latest.value / VIRAL_DETECTION_LIMIT),
                           f"{spec.label}: {latest.value:,.0f} {spec.unit_label}", signal=signal))
    crp = ctx.latest(S.CRP)
    if crp is not None and crp.value > CRP_LIMIT:
        out.append(Feature("crp:high", 1.0,
                           f"Inflammation marker CRP high ({crp.value:g} {get_spec(S.CRP).unit_label})",
                           signal=S.CRP))
    return out


def _wellbeing_features(ctx: AssessmentContext) -> list[Feature]:
    out = []
    stress = ctx.latest(S.STRESS, within=CHECKIN_FRESHNESS)
    if stress is not None and stress.value >= 4:
        out.append(Feature("stress:high", 1.0, "High stress in your check-in", signal=S.STRESS))
    mood = ctx.latest(S.MOOD, within=CHECKIN_FRESHNESS)
    if mood is not None and mood.value <= 2:
        out.append(Feature("mood:low", 1.0, "Low mood in your check-in", signal=S.MOOD))
    return out


def _event_features(ctx: AssessmentContext) -> list[Feature]:
    # Per event type, the most severe started event; ties go to the most recent.
    chosen: dict[EventType, ContextEvent] = {}
    for event in ctx.events:
        if event.start > ctx.as_of:
            continue
        kept = chosen.get(event.event_type)
        if kept is None or _event_key(event) > _event_key(kept):
            chosen[event.event_type] = event

    out = []
    for event_type, event in chosen.items():
        ended = event.end or event.start
        days = max(0, (ctx.as_of - min(ended, ctx.as_of)).days)
        name = EVENT_NAMES.get(event_type, event_type.value.replace("_", " "))
        out.append(Feature(f"event:{event_type.value}", float(SEVERITY_RANK[event.severity]),
                           f"{name} {_days_label(days)}", event_id=event.event_id))
    return out


def _event_key(event: ContextEvent) -> tuple:
    return (SEVERITY_RANK[event.severity], event.start, event.event_id)
