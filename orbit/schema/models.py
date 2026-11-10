"""Data models: the contract between every ORBIT module.

Inputs (produced by the simulator M2, ingestion M3, space weather M5):
    Observation   one health reading for one astronaut at one time
    ContextEvent  something that stresses the crew (solar storm, EVA ...)
    CrewMember    astronaut profile, mission start, sharing consent

Outputs (produced by analytics M7/M8 and the action engine M10):
    Anomaly        a deviation from the astronaut's personal baseline
    RiskAssessment immune risk score, alert level and the reasons behind it
    ActionCard     what to do at a given alert level

Rules every model follows:
    * Timestamps must carry a timezone and are stored in UTC.
      Naive times are rejected because "06:00" means nothing on a spacecraft.
    * Models are immutable (frozen) and reject unknown fields, so a typo in a
      field name fails loudly instead of being silently dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Self
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    field_validator,
    model_validator,
)

from .enums import (
    AlertLevel,
    AnomalyKind,
    EscalationTarget,
    EventType,
    Quality,
    Severity,
    SignalCategory,
    SignalKind,
    SignalType,
    Source,
)
from .signals import SIGNALS, SignalSpec

SCHEMA_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Shared field types
# --------------------------------------------------------------------------


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "timestamp must include a timezone, e.g. '2026-03-01T06:00:00Z'; "
            "naive times are ambiguous"
        )
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""A datetime that must be timezone-aware; it is converted to UTC."""

AstronautId = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
]
"""Short stable ID such as 'AST-01'. Letters, digits, '-' and '_' only."""

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


def _new_id() -> str:
    return uuid4().hex


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        use_enum_values=False,
        str_strip_whitespace=True,
    )


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


class Observation(_Model):
    """One health reading for one astronaut at one moment.

    Example::

        Observation(
            astronaut_id="AST-01",
            timestamp="2026-03-01T06:00:00Z",
            signal="skin_temp",
            value=34.6,
            source="wearable",
        )

    ``unit`` may be omitted and is then filled with the signal's canonical
    unit. If given, it must match exactly, which catches °F/°C mix-ups.
    """

    observation_id: str = Field(default_factory=_new_id, max_length=64)
    astronaut_id: AstronautId
    timestamp: UtcDatetime = Field(
        description="When the reading applies, in UTC. For nightly summaries, "
        "use the wake-up time."
    )
    signal: SignalType
    value: FiniteFloat
    unit: str = Field(description="Must equal the signal's canonical unit.")
    source: Source
    quality: Quality = Quality.GOOD
    simulated: bool = Field(
        default=False, description="True for data produced by the mission simulator."
    )
    device_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def _fill_default_unit(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("unit") in (None, ""):
            try:
                spec = SIGNALS[SignalType(data.get("signal"))]
            except (ValueError, KeyError):
                return data  # unknown signal: let field validation report it
            data = {**data, "unit": spec.unit}
        return data

    @model_validator(mode="after")
    def _check_against_registry(self) -> Self:
        spec = self.spec
        if self.unit != spec.unit:
            raise ValueError(
                f"unit '{self.unit}' is wrong for {self.signal.value}; "
                f"expected '{spec.unit}' ({spec.unit_label})"
            )
        if self.source not in spec.allowed_sources:
            allowed = ", ".join(sorted(s.value for s in spec.allowed_sources))
            raise ValueError(
                f"source '{self.source.value}' cannot report {self.signal.value}; "
                f"allowed: {allowed}"
            )
        if spec.kind is SignalKind.ORDINAL and not float(self.value).is_integer():
            raise ValueError(
                f"{self.signal.value} is a whole-number scale "
                f"({spec.unit_label}); got {self.value}"
            )
        if not spec.is_plausible(self.value) and self.quality is Quality.GOOD:
            raise ValueError(
                f"{self.value} {spec.unit_label} is outside the plausible range "
                f"[{spec.plausible_min:g}, {spec.plausible_max:g}] for "
                f"{self.signal.value}. If this is a real reading from a faulty "
                f"sensor, store it with quality='bad' or 'suspect'."
            )
        return self

    @property
    def spec(self) -> SignalSpec:
        return SIGNALS[self.signal]

    @property
    def category(self) -> SignalCategory:
        return self.spec.category

    @property
    def is_usable(self) -> bool:
        """False for readings flagged BAD. Analytics should skip those."""
        return self.quality is not Quality.BAD


class ContextEvent(_Model):
    """Something that happened to the crew and may stress the immune system.

    ``astronaut_id=None`` means the event affects the whole crew (e.g. a
    solar particle event). ``external_id`` keeps the source's own ID, such as
    a NASA DONKI activity ID, so events are not imported twice.
    """

    event_id: str = Field(default_factory=_new_id, max_length=64)
    event_type: EventType
    start: UtcDatetime
    end: UtcDatetime | None = Field(
        default=None, description="None for a single moment or still ongoing."
    )
    severity: Severity = Severity.MODERATE
    astronaut_id: AstronautId | None = None
    source: Source = Source.GROUND
    external_id: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    simulated: bool = False

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end is not None and self.end < self.start:
            raise ValueError("event end must not be before its start")
        return self

    def affects(self, astronaut_id: str) -> bool:
        return self.astronaut_id is None or self.astronaut_id == astronaut_id

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """True if the event touches the window [start, end]."""
        event_end = self.end or self.start
        return self.start <= _require_utc(end) and event_end >= _require_utc(start)


DEFAULT_SHARED_CATEGORIES: frozenset[SignalCategory] = frozenset(
    {SignalCategory.VITAL, SignalCategory.SLEEP, SignalCategory.LAB, SignalCategory.CONTEXT}
)
"""Shared with Earth unless the astronaut changes it. Symptoms and wellbeing
stay private by default: astronauts under-report when they fear consequences."""


class CrewMember(_Model):
    """Astronaut profile."""

    astronaut_id: AstronautId
    callsign: str = Field(min_length=1, max_length=32)
    role: str | None = Field(default=None, max_length=64)
    mission_start: UtcDatetime
    share_with_earth: frozenset[SignalCategory] = DEFAULT_SHARED_CATEGORIES

    def mission_day(self, when: datetime) -> int:
        """Mission day number in UTC: 1 on launch day, 0 or less before launch."""
        return (_require_utc(when).date() - self.mission_start.date()).days + 1

    def shares(self, category: SignalCategory) -> bool:
        return category in self.share_with_earth


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------

LEVEL_THRESHOLDS: tuple[tuple[float, AlertLevel], ...] = (
    (75.0, AlertLevel.RED),
    (50.0, AlertLevel.ORANGE),
    (25.0, AlertLevel.YELLOW),
    (0.0, AlertLevel.GREEN),
)
"""Minimum score for each level. Shared so backend and frontend always agree."""


def level_for_score(score: float) -> AlertLevel:
    """Map a 0-100 risk score to its alert level."""
    for minimum, level in LEVEL_THRESHOLDS:
        if score >= minimum:
            return level
    return AlertLevel.GREEN


class Baseline(_Model):
    """An astronaut's personal normal for one signal (from M6).

    The dashboard draws ``center ± spread`` as the shaded "your normal" band.
    """

    astronaut_id: AstronautId
    signal: SignalType
    as_of: UtcDatetime = Field(description="Computed from data before this moment.")
    center: FiniteFloat = Field(description="Typical value, e.g. the median.")
    spread: FiniteFloat = Field(ge=0, description="Typical variation, e.g. scaled MAD.")
    n_samples: int = Field(ge=1, description="Readings the baseline was built from.")
    window_days: int = Field(ge=1)
    method: str = Field(default="unspecified", max_length=32)

    @property
    def low(self) -> float:
        return self.center - self.spread

    @property
    def high(self) -> float:
        return self.center + self.spread


class Anomaly(_Model):
    """A reading that departs from the astronaut's personal baseline (from M7)."""

    astronaut_id: AstronautId
    signal: SignalType
    detected_at: UtcDatetime
    kind: AnomalyKind
    value: FiniteFloat = Field(description="The reading, or recent average for drift.")
    baseline_center: FiniteFloat = Field(description="Personal normal (e.g. median).")
    baseline_spread: FiniteFloat = Field(ge=0, description="Personal variability (e.g. MAD).")
    deviation: FiniteFloat = Field(
        description="Signed distance from baseline in spread units (robust z-score)."
    )
    consecutive_days: int = Field(default=1, ge=1)

    @property
    def delta(self) -> float:
        """Raw difference from the personal baseline, in the signal's unit."""
        return self.value - self.baseline_center


class Contributor(_Model):
    """One reason behind a risk score, shown in the dashboard's 'why' panel."""

    label: str = Field(
        min_length=1,
        max_length=160,
        description="Plain-language reason, e.g. 'Skin temp +0.4 °C above your "
        "normal for 2 nights'.",
    )
    points: FiniteFloat = Field(ge=0, description="How much this adds to the score.")
    signal: SignalType | None = None
    event_id: str | None = None


class RiskAssessment(_Model):
    """Immune risk for one astronaut at one time (from M8)."""

    assessment_id: str = Field(default_factory=_new_id, max_length=64)
    astronaut_id: AstronautId
    assessed_at: UtcDatetime
    score: FiniteFloat = Field(ge=0, le=100)
    level: AlertLevel
    contributors: tuple[Contributor, ...] = ()
    model_version: str = Field(default="unversioned", max_length=32)

    @model_validator(mode="before")
    @classmethod
    def _derive_level(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("level") is None and "score" in data:
            try:
                data = {**data, "level": level_for_score(float(data["score"]))}
            except (TypeError, ValueError):
                pass  # let field validation report the bad score
        return data

    @field_validator("contributors")
    @classmethod
    def _sort_contributors(cls, value: tuple[Contributor, ...]) -> tuple[Contributor, ...]:
        return tuple(sorted(value, key=lambda c: c.points, reverse=True))

    @model_validator(mode="after")
    def _level_matches_score(self) -> Self:
        expected = level_for_score(self.score)
        if self.level is not expected:
            raise ValueError(
                f"level '{self.level.value}' does not match score {self.score:g} "
                f"(expected '{expected.value}'); omit level to derive it"
            )
        return self

    def top_reasons(self, n: int = 3) -> tuple[Contributor, ...]:
        return self.contributors[:n]


class ActionCard(_Model):
    """A concrete thing the astronaut can do (from M10's protocol library)."""

    card_id: Slug
    level: AlertLevel = Field(description="Lowest alert level at which this card applies.")
    title: str = Field(min_length=1, max_length=80)
    steps: tuple[Annotated[str, StringConstraints(min_length=1, max_length=200)], ...] = (
        Field(min_length=1)
    )
    rationale: str = Field(min_length=1, max_length=400)
    escalate_to: EscalationTarget = EscalationTarget.SELF
    triggers: tuple[SignalType, ...] = Field(
        default=(), description="Signals that make this card relevant; empty = any."
    )
