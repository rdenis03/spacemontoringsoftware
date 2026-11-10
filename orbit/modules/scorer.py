"""Starter risk scorer (slot ``scorer``, team module M8).

A transparent points system: every piece of evidence adds points, and every
point comes with a plain-language reason the astronaut can check. The total
(capped at 100) maps to green / yellow / orange / red.

    Evidence                               Points
    -------------------------------------  ------------------------------------
    Vital-sign anomaly (temp, HR, HRV ...)  vital_weight x deviation (capped)
    Sleep anomaly                           sleep_weight x deviation (capped)
      ... sustained drift                   x drift_bonus
    Symptom in the last check-in            severity x weight (higher for signs
                                            specific to viral reactivation)
    Virus DNA in saliva                     grows with viral load, up to 12
    High CRP                                8
    High stress / low mood                  3 each
    Recent stress event (solar, EVA ...)    1-10 by severity

The weights are a starting point for the demo, not clinically validated.
Ideas for M8: tune weights on simulator scenarios (with M9), interactions
between signals, a calibrated probability model kept explainable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import timedelta

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import (
    Anomaly,
    AnomalyKind,
    ConcernDirection,
    Contributor,
    EventType,
    RiskAssessment,
    Severity,
    SignalCategory,
    SignalType,
    get_spec,
)

S = SignalType

SYMPTOM_WEIGHTS: dict[SignalType, float] = {
    # Signs fairly specific to herpesvirus reactivation weigh more.
    S.SYMPTOM_RASH_TINGLING: 7,
    S.SYMPTOM_MOUTH_SORES: 6,
    S.SYMPTOM_SWOLLEN_GLANDS: 6,
    S.SYMPTOM_FEVER_CHILLS: 6,
    # General signs.
    S.SYMPTOM_FATIGUE: 3,
    S.SYMPTOM_SORE_THROAT: 3,
    S.SYMPTOM_HEADACHE: 2,
    S.SYMPTOM_MUSCLE_ACHES: 2,
}
VIRAL_DNA = (S.SALIVA_EBV_DNA, S.SALIVA_VZV_DNA, S.SALIVA_HSV1_DNA)
EVENT_POINTS = {Severity.LOW: 1, Severity.MODERATE: 3, Severity.HIGH: 6, Severity.EXTREME: 10}
EVENT_NAMES = {
    EventType.SOLAR_FLARE: "Solar flare",
    EventType.SOLAR_PARTICLE_EVENT: "Solar particle event",
    EventType.CME: "Coronal mass ejection",
    EventType.GEOMAGNETIC_STORM: "Geomagnetic storm",
    EventType.EVA: "Spacewalk",
    EventType.SLEEP_SHIFT: "Sleep schedule shift",
    EventType.CREW_ILLNESS: "Ill crewmate",
    EventType.OTHER: "Stress event",
}
CHECKIN_FRESHNESS = timedelta(hours=36)


def _days_label(days: int) -> str:
    return "today" if days <= 0 else ("1 day ago" if days == 1 else f"{days} days ago")


def describe_anomaly(anomaly: Anomaly) -> str:
    """'Skin temperature 0.5 °C above your normal for 2 days'."""
    spec = get_spec(anomaly.signal)
    delta = anomaly.delta
    side = "above" if delta > 0 else "below"
    if spec.concern is ConcernDirection.DOWN and anomaly.baseline_center:
        amount = f"{abs(delta) / abs(anomaly.baseline_center):.0%}"
    else:
        amount = f"{abs(delta):.2g} {spec.unit_label}"
    when = (f"for {anomaly.consecutive_days} days" if anomaly.kind is AnomalyKind.DRIFT
            else "in the latest reading")
    return f"{spec.label} {amount} {side} your normal {when}"


@register("scorer", "rule_based")
class RuleBasedScorer:
    version = "rule_based-0.1"

    def __init__(
        self,
        vital_weight: float = 2.5,
        sleep_weight: float = 1.5,
        max_deviation: float = 3.0,
        drift_bonus: float = 1.2,
        viral_detection_limit: float = 100.0,
        crp_limit: float = 10.0,
    ):
        self.vital_weight = vital_weight
        self.sleep_weight = sleep_weight
        self.max_deviation = max_deviation
        self.drift_bonus = drift_bonus
        self.viral_detection_limit = viral_detection_limit
        self.crp_limit = crp_limit

    def score(self, ctx: AssessmentContext, anomalies: Sequence[Anomaly]) -> RiskAssessment:
        reasons: list[Contributor] = []
        reasons += self._anomaly_points(anomalies)
        reasons += self._symptom_points(ctx)
        reasons += self._lab_points(ctx)
        reasons += self._wellbeing_points(ctx)
        reasons += self._event_points(ctx)
        reasons = [r for r in reasons if r.points > 0]
        total = min(100.0, round(sum(r.points for r in reasons), 1))
        return RiskAssessment(
            astronaut_id=ctx.astronaut_id,
            assessed_at=ctx.as_of,
            score=total,
            contributors=reasons,
            model_version=self.version,
        )

    def _anomaly_points(self, anomalies: Sequence[Anomaly]) -> list[Contributor]:
        out = []
        for anomaly in anomalies:
            category = get_spec(anomaly.signal).category
            weight = self.sleep_weight if category is SignalCategory.SLEEP else self.vital_weight
            points = weight * min(abs(anomaly.deviation), self.max_deviation)
            if anomaly.kind is AnomalyKind.DRIFT:
                points *= self.drift_bonus
            out.append(Contributor(label=describe_anomaly(anomaly), points=round(points, 1),
                                   signal=anomaly.signal))
        return out

    def _symptom_points(self, ctx: AssessmentContext) -> list[Contributor]:
        out = []
        for signal, weight in SYMPTOM_WEIGHTS.items():
            latest = ctx.latest(signal, within=CHECKIN_FRESHNESS)
            if latest is None or latest.value <= 0:
                continue
            spec = latest.spec
            out.append(Contributor(
                label=f"{spec.label}: {spec.scale_label(latest.value)} in your check-in",
                points=latest.value * weight, signal=signal,
            ))
        return out

    def _lab_points(self, ctx: AssessmentContext) -> list[Contributor]:
        out = []
        for signal in VIRAL_DNA:
            latest = ctx.latest(signal)
            if latest is None or latest.value < self.viral_detection_limit:
                continue
            # 4 points at the detection limit, +4 per tenfold rise, at most 12.
            points = min(12.0, 4 + 4 * math.log10(latest.value / self.viral_detection_limit))
            out.append(Contributor(
                label=f"{latest.spec.label}: {latest.value:,.0f} {latest.spec.unit_label}",
                points=round(points, 1), signal=signal,
            ))
        crp = ctx.latest(S.CRP)
        if crp is not None and crp.value > self.crp_limit:
            out.append(Contributor(label=f"Inflammation marker CRP high ({crp.value:g} mg/L)",
                                   points=8, signal=S.CRP))
        return out

    def _wellbeing_points(self, ctx: AssessmentContext) -> list[Contributor]:
        out = []
        stress = ctx.latest(S.STRESS, within=CHECKIN_FRESHNESS)
        if stress is not None and stress.value >= 4:
            out.append(Contributor(label="High stress in your check-in", points=3, signal=S.STRESS))
        mood = ctx.latest(S.MOOD, within=CHECKIN_FRESHNESS)
        if mood is not None and mood.value <= 2:
            out.append(Contributor(label="Low mood in your check-in", points=3, signal=S.MOOD))
        return out

    def _event_points(self, ctx: AssessmentContext) -> list[Contributor]:
        out = []
        for event in ctx.events:
            if event.start > ctx.as_of:
                continue
            ended = event.end or event.start
            days = max(0, (ctx.as_of - min(ended, ctx.as_of)).days)
            name = EVENT_NAMES.get(event.event_type, event.event_type.value.replace("_", " "))
            out.append(Contributor(label=f"{name} {_days_label(days)}",
                                   points=EVENT_POINTS[event.severity], event_id=event.event_id))
        return out
