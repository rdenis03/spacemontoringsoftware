"""Signal registry: the single source of truth for every health indicator.

Each signal has one canonical unit, a plausible range and a concern direction.

* The **plausible range** is a hard physical limit, not a medical "normal"
  range. A value outside it is almost certainly a sensor or typing error, so
  the ``Observation`` model refuses to store it as ``quality="good"``.
* "Normal" is personal in ORBIT: the baseline module (M6) learns it per
  astronaut. Nothing here says what is healthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from .enums import ConcernDirection as C
from .enums import SignalCategory as Cat
from .enums import SignalKind, SignalType, Source

SEVERITY_SCALE = ("none", "mild", "moderate", "severe")  # values 0..3
MOOD_SCALE = ("very low", "low", "neutral", "good", "very good")  # values 1..5
STRESS_SCALE = ("very low", "low", "moderate", "high", "very high")  # values 1..5

# Which input channels may report each category of signal.
ALLOWED_SOURCES: MappingProxyType[Cat, frozenset[Source]] = MappingProxyType(
    {
        Cat.VITAL: frozenset({Source.WEARABLE, Source.MANUAL}),
        Cat.SLEEP: frozenset({Source.WEARABLE, Source.MANUAL}),
        Cat.SYMPTOM: frozenset({Source.CHECKIN}),
        Cat.WELLBEING: frozenset({Source.CHECKIN}),
        Cat.LAB: frozenset({Source.LAB, Source.MANUAL}),
        Cat.CONTEXT: frozenset({Source.ENVIRONMENT, Source.GROUND, Source.MANUAL}),
    }
)


@dataclass(frozen=True)
class SignalSpec:
    """Everything a module needs to know about one signal."""

    signal: SignalType
    label: str  # short human-readable name for the UI
    category: Cat
    kind: SignalKind
    unit: str  # canonical unit; every Observation must use exactly this
    unit_label: str  # pretty unit for display (may contain non-ASCII)
    plausible_min: float
    plausible_max: float
    concern: C
    cadence: str  # "nightly", "daily" or "on_demand"
    description: str
    scale_labels: tuple[str, ...] | None = field(default=None)

    @property
    def allowed_sources(self) -> frozenset[Source]:
        return ALLOWED_SOURCES[self.category]

    @property
    def scale_min(self) -> int | None:
        """Lowest value on an ordinal scale (0 for symptoms, 1 for mood)."""
        return int(self.plausible_min) if self.kind is SignalKind.ORDINAL else None

    def is_plausible(self, value: float) -> bool:
        return self.plausible_min <= value <= self.plausible_max

    def scale_label(self, value: float) -> str | None:
        """'moderate' for a symptom value of 2, None for continuous signals."""
        if self.scale_labels is None:
            return None
        index = int(value) - int(self.plausible_min)
        if 0 <= index < len(self.scale_labels):
            return self.scale_labels[index]
        return None

    def to_dict(self) -> dict:
        """JSON-friendly form, used for the frontend's signals.json."""
        return {
            "signal": self.signal.value,
            "label": self.label,
            "category": self.category.value,
            "kind": self.kind.value,
            "unit": self.unit,
            "unit_label": self.unit_label,
            "plausible_min": self.plausible_min,
            "plausible_max": self.plausible_max,
            "concern": self.concern.value,
            "cadence": self.cadence,
            "description": self.description,
            "scale_labels": list(self.scale_labels) if self.scale_labels else None,
            "allowed_sources": sorted(s.value for s in self.allowed_sources),
        }


def _symptom(signal: SignalType, label: str, description: str) -> SignalSpec:
    return SignalSpec(
        signal=signal,
        label=label,
        category=Cat.SYMPTOM,
        kind=SignalKind.ORDINAL,
        unit="severity_0_3",
        unit_label="0–3",
        plausible_min=0,
        plausible_max=3,
        concern=C.UP,
        cadence="daily",
        description=description,
        scale_labels=SEVERITY_SCALE,
    )


def _viral_dna(signal: SignalType, label: str, virus: str) -> SignalSpec:
    return SignalSpec(
        signal=signal,
        label=label,
        category=Cat.LAB,
        kind=SignalKind.CONTINUOUS,
        unit="copies/mL",
        unit_label="copies/mL",
        plausible_min=0,
        plausible_max=1e10,
        concern=C.UP,
        cadence="on_demand",
        description=(
            f"{virus} DNA shed in saliva. Dormant herpesviruses reactivate more "
            "often in spaceflight; rising shedding is an early sign of weakened "
            "immune control."
        ),
    )


_SPECS: tuple[SignalSpec, ...] = (
    # ---- Vitals ------------------------------------------------------------
    SignalSpec(
        SignalType.SKIN_TEMP, "Skin temperature", Cat.VITAL, SignalKind.CONTINUOUS,
        "degC", "°C", 28, 42, C.UP, "nightly",
        "Mean distal skin temperature during sleep. A sustained rise above the "
        "personal baseline can precede fever.",
    ),
    SignalSpec(
        SignalType.RESTING_HR, "Resting heart rate", Cat.VITAL, SignalKind.CONTINUOUS,
        "bpm", "bpm", 25, 200, C.UP, "nightly",
        "Lowest stable heart rate during sleep. Rises during infection and stress.",
    ),
    SignalSpec(
        SignalType.HRV_RMSSD, "Heart rate variability", Cat.VITAL, SignalKind.CONTINUOUS,
        "ms", "ms", 3, 300, C.DOWN, "nightly",
        "Nightly HRV (RMSSD). Drops when the body is fighting infection or under "
        "heavy stress.",
    ),
    SignalSpec(
        SignalType.RESP_RATE, "Respiratory rate", Cat.VITAL, SignalKind.CONTINUOUS,
        "breaths/min", "breaths/min", 4, 60, C.UP, "nightly",
        "Average breathing rate during sleep. Very stable per person, so small "
        "rises are meaningful.",
    ),
    SignalSpec(
        SignalType.SPO2, "Blood oxygen", Cat.VITAL, SignalKind.CONTINUOUS,
        "pct", "%", 50, 100, C.DOWN, "nightly",
        "Average peripheral oxygen saturation during sleep.",
    ),
    # ---- Sleep -------------------------------------------------------------
    SignalSpec(
        SignalType.SLEEP_DURATION, "Sleep duration", Cat.SLEEP, SignalKind.CONTINUOUS,
        "h", "h", 0, 16, C.DOWN, "nightly",
        "Total sleep time. Sleep loss weakens immune defences.",
    ),
    SignalSpec(
        SignalType.SLEEP_EFFICIENCY, "Sleep efficiency", Cat.SLEEP, SignalKind.CONTINUOUS,
        "pct", "%", 0, 100, C.DOWN, "nightly",
        "Share of time in bed actually spent asleep.",
    ),
    # ---- Symptoms ----------------------------------------------------------
    _symptom(SignalType.SYMPTOM_FATIGUE, "Fatigue",
             "Unusual tiredness not explained by workload."),
    _symptom(SignalType.SYMPTOM_FEVER_CHILLS, "Fever or chills",
             "Feeling feverish, chills or night sweats."),
    _symptom(SignalType.SYMPTOM_SORE_THROAT, "Sore throat",
             "Pain or scratchiness in the throat."),
    _symptom(SignalType.SYMPTOM_SWOLLEN_GLANDS, "Swollen glands",
             "Tender or swollen lymph nodes in the neck; can accompany EBV activity."),
    _symptom(SignalType.SYMPTOM_MOUTH_SORES, "Mouth or lip sores",
             "Cold sores or mouth ulcers; can signal HSV-1 reactivation."),
    _symptom(SignalType.SYMPTOM_RASH_TINGLING, "Rash or tingling",
             "Tingling, burning or a rash on one side of the body; can signal "
             "shingles (VZV) reactivation."),
    _symptom(SignalType.SYMPTOM_HEADACHE, "Headache", "Headache of any kind."),
    _symptom(SignalType.SYMPTOM_MUSCLE_ACHES, "Muscle aches",
             "Body or muscle aches not explained by exercise."),
    # ---- Wellbeing ---------------------------------------------------------
    SignalSpec(
        SignalType.MOOD, "Mood", Cat.WELLBEING, SignalKind.ORDINAL,
        "scale_1_5", "1–5", 1, 5, C.DOWN, "daily",
        "Self-rated overall mood.", MOOD_SCALE,
    ),
    SignalSpec(
        SignalType.STRESS, "Stress", Cat.WELLBEING, SignalKind.ORDINAL,
        "scale_1_5", "1–5", 1, 5, C.UP, "daily",
        "Self-rated stress. Chronic stress suppresses immune function.", STRESS_SCALE,
    ),
    # ---- Lab ---------------------------------------------------------------
    _viral_dna(SignalType.SALIVA_EBV_DNA, "EBV in saliva", "Epstein-Barr virus"),
    _viral_dna(SignalType.SALIVA_VZV_DNA, "VZV in saliva", "Varicella-zoster virus (shingles)"),
    _viral_dna(SignalType.SALIVA_HSV1_DNA, "HSV-1 in saliva", "Herpes simplex virus 1"),
    SignalSpec(
        SignalType.SALIVA_CORTISOL, "Saliva cortisol", Cat.LAB, SignalKind.CONTINUOUS,
        "nmol/L", "nmol/L", 0, 300, C.UP, "on_demand",
        "Stress hormone. Persistently high levels are linked to viral reactivation.",
    ),
    SignalSpec(
        SignalType.WBC_COUNT, "White blood cells", Cat.LAB, SignalKind.CONTINUOUS,
        "10^9/L", "×10⁹/L", 0.1, 100, C.BOTH, "on_demand",
        "Total white blood cell count. Abnormal in either direction.",
    ),
    SignalSpec(
        SignalType.CRP, "C-reactive protein", Cat.LAB, SignalKind.CONTINUOUS,
        "mg/L", "mg/L", 0, 500, C.UP, "on_demand",
        "General marker of inflammation.",
    ),
    # ---- Context -----------------------------------------------------------
    SignalSpec(
        SignalType.RADIATION_DOSE_DAILY, "Radiation dose", Cat.CONTEXT, SignalKind.CONTINUOUS,
        "mGy", "mGy/day", 0, 1000, C.UP, "daily",
        "Absorbed dose over the day from the personal or habitat dosimeter. "
        "Radiation is a known immune stressor.",
    ),
    SignalSpec(
        SignalType.WORKLOAD, "Workload", Cat.CONTEXT, SignalKind.CONTINUOUS,
        "h", "h", 0, 24, C.UP, "daily",
        "Scheduled working hours that day.",
    ),
)

SIGNALS: MappingProxyType[SignalType, SignalSpec] = MappingProxyType(
    {spec.signal: spec for spec in _SPECS}
)


def get_spec(signal: SignalType | str) -> SignalSpec:
    """Look up a signal by enum or by its string name ("skin_temp")."""
    return SIGNALS[SignalType(signal)]


def signals_in(category: Cat) -> list[SignalSpec]:
    """All signals of one category, in registry order."""
    return [spec for spec in _SPECS if spec.category is category]
