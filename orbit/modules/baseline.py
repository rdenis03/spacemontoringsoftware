"""Starter baseline engine (slot ``baseline``, team module M6).

Personal normal = median of the astronaut's own readings over the baseline
window; spread = scaled median absolute deviation (MAD). Median and MAD are
used instead of mean and standard deviation because one bad night or sensor
glitch barely moves them.

Ideas for M6: weight recent days more (EWMA), adjust for circadian shifts,
separate pre-flight and in-flight baselines.
"""

from __future__ import annotations

from statistics import median

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import Baseline, SignalCategory, SignalKind, SignalType

MAD_TO_SD = 1.4826  # makes MAD comparable to a standard deviation for normal data

# Smallest spread allowed per signal, so a very stable astronaut does not get
# a zero-width band where any tiny change looks like a huge anomaly.
MIN_SPREAD: dict[SignalType, float] = {
    SignalType.SKIN_TEMP: 0.10,
    SignalType.RESTING_HR: 1.5,
    SignalType.HRV_RMSSD: 3.0,
    SignalType.RESP_RATE: 0.3,
    SignalType.SPO2: 0.5,
    SignalType.SLEEP_DURATION: 0.3,
    SignalType.SLEEP_EFFICIENCY: 2.0,
}
DEFAULT_CATEGORIES = (SignalCategory.VITAL, SignalCategory.SLEEP)


@register("baseline", "rolling_median")
class RollingMedianBaseline:
    def __init__(self, min_samples: int = 5, categories: list[str] | None = None):
        if min_samples < 2:
            raise ValueError("min_samples must be at least 2")
        self.min_samples = min_samples
        self.categories = tuple(SignalCategory(c) for c in categories) if categories \
            else DEFAULT_CATEGORIES

    def compute(self, ctx: AssessmentContext) -> list[Baseline]:
        by_signal: dict[SignalType, list[float]] = {}
        for obs in ctx.history:
            if obs.category in self.categories and obs.spec.kind is SignalKind.CONTINUOUS:
                by_signal.setdefault(obs.signal, []).append(obs.value)

        baselines = []
        for signal, values in by_signal.items():
            if len(values) < self.min_samples:
                continue  # not enough data yet to know this astronaut's normal
            center = median(values)
            mad = median(abs(v - center) for v in values) * MAD_TO_SD
            floor = MIN_SPREAD.get(signal, 0.05 * abs(center) or 1.0)
            baselines.append(Baseline(
                astronaut_id=ctx.astronaut_id,
                signal=signal,
                as_of=ctx.as_of,
                center=round(center, 4),
                spread=round(max(mad, floor), 4),
                n_samples=len(values),
                window_days=ctx.baseline_window_days,
                method="rolling_median",
            ))
        return sorted(baselines, key=lambda b: list(SignalType).index(b.signal))
