"""Starter anomaly detector (slot ``detector``, team module M7).

For each signal with a baseline, every recent reading gets a robust z-score:
how many "spreads" it sits from the personal normal. Only the worrying
direction counts (skin temperature up, HRV down, ...).

* SPIKE: the latest reading is at least ``threshold`` spreads off.
* DRIFT: the last ``drift_days`` readings in a row are at least
  ``drift_threshold`` spreads off. Catches slow changes a spike test misses.

Ideas for M7: CUSUM or EWMA charts, combining signals, learning thresholds
from the simulator's labelled scenarios.
"""

from __future__ import annotations

from collections.abc import Mapping
from statistics import fmean

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import Anomaly, AnomalyKind, Baseline, ConcernDirection, SignalType, get_spec


def concern_score(z: float, direction: ConcernDirection) -> float:
    """Positive when the change goes the worrying way, negative otherwise."""
    if direction is ConcernDirection.UP:
        return z
    if direction is ConcernDirection.DOWN:
        return -z
    return abs(z)


@register("detector", "robust_z")
class RobustZDetector:
    def __init__(self, threshold: float = 2.5, drift_threshold: float = 1.5, drift_days: int = 2):
        if not 0 < drift_threshold <= threshold:
            raise ValueError("need 0 < drift_threshold <= threshold")
        self.threshold = threshold
        self.drift_threshold = drift_threshold
        self.drift_days = drift_days

    def detect(
        self, ctx: AssessmentContext, baselines: Mapping[SignalType, Baseline]
    ) -> list[Anomaly]:
        anomalies = []
        for signal, baseline in baselines.items():
            readings = ctx.recent_for(signal)
            if not readings or baseline.spread <= 0:
                continue
            direction = get_spec(signal).concern
            z_values = [(o.value - baseline.center) / baseline.spread for o in readings]
            concern = [concern_score(z, direction) for z in z_values]

            run = 0  # consecutive worrying readings, counted back from the latest
            for value in reversed(concern):
                if value < self.drift_threshold:
                    break
                run += 1

            if run >= self.drift_days:
                kind = AnomalyKind.DRIFT
                value = fmean(o.value for o in readings[-run:])
                deviation = fmean(z_values[-run:])
            elif concern[-1] >= self.threshold:
                kind, value, deviation = AnomalyKind.SPIKE, readings[-1].value, z_values[-1]
            else:
                continue

            anomalies.append(Anomaly(
                astronaut_id=ctx.astronaut_id,
                signal=signal,
                detected_at=readings[-1].timestamp,
                kind=kind,
                value=round(value, 4),
                baseline_center=baseline.center,
                baseline_spread=baseline.spread,
                deviation=round(deviation, 3),
                consecutive_days=max(run, 1),
            ))
        return anomalies
