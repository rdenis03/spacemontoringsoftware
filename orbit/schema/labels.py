"""Scenario labels: the "right answers" for a simulated mission.

The simulator (M2) writes one ``ScenarioLabel`` per episode it injects: what
happened, to whom, when, and whether ORBIT should have alerted. The evaluation
(M9) and the trainer compare ORBIT's assessments with these labels::

    from orbit.schema import ScenarioLabel, read_labels

    for label in read_labels("data/sim/labels.jsonl"):
        start, end = label.window()     # where an alert counts for this label

Rules:
    * ``onset`` is the physiological onset; ``symptom_onset`` and ``resolved``
      must not be before it.
    * ``virus`` is set only for ``viral_reactivation`` (and is then required).
    * ``should_alert`` must match the scenario type: only the types in
      ``ALERTING_SCENARIOS`` should alert. Look-alike confounders, faults and
      missing data should not.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from .io import parse_jsonl, write_jsonl
from .models import AstronautId, UtcDatetime, _Model

WINDOW_LEAD_DAYS = 2
"""A label's window starts this many days before ``onset`` (SPEC M9)."""


class ScenarioType(StrEnum):
    """What the simulator injected into a mission."""

    VIRAL_REACTIVATION = "viral_reactivation"
    RESPIRATORY_INFECTION = "respiratory_infection"
    EVA_EXERTION = "eva_exertion"
    SLEEP_SHIFT = "sleep_shift"
    SOLAR_PARTICLE_EVENT = "solar_particle_event"
    SENSOR_FAULT = "sensor_fault"
    MISSING_DATA = "missing_data"


ALERTING_SCENARIOS: frozenset[ScenarioType] = frozenset(
    {ScenarioType.VIRAL_REACTIVATION, ScenarioType.RESPIRATORY_INFECTION}
)
"""Scenarios ORBIT should alert on. Every other type is a look-alike or a data problem."""


class ScenarioLabel(_Model):
    """Ground truth for one injected episode."""

    label_id: str
    astronaut_id: AstronautId
    scenario: ScenarioType
    virus: Literal["ebv", "vzv", "hsv1"] | None = None
    onset: UtcDatetime
    symptom_onset: UtcDatetime | None = None
    resolved: UtcDatetime | None = None
    should_alert: bool
    notes: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.symptom_onset is not None and self.symptom_onset < self.onset:
            raise ValueError("symptom_onset must not be before onset")
        if self.resolved is not None and self.resolved < self.onset:
            raise ValueError("resolved must not be before onset")

        if self.scenario is ScenarioType.VIRAL_REACTIVATION:
            if self.virus is None:
                raise ValueError("virus is required for viral_reactivation")
        elif self.virus is not None:
            raise ValueError(f"virus must be None for {self.scenario.value}")

        expected = self.scenario in ALERTING_SCENARIOS
        if self.should_alert != expected:
            raise ValueError(
                f"should_alert must be {expected} for {self.scenario.value}"
            )
        return self

    def window(self, lookahead_days: int = 14) -> tuple[datetime, datetime]:
        """Where an alert counts for this label (SPEC M9).

        From ``onset - 2 days`` to ``resolved``, or to ``onset + lookahead_days``
        when ``resolved`` is not set.
        """
        start = self.onset - timedelta(days=WINDOW_LEAD_DAYS)
        end = self.resolved or self.onset + timedelta(days=lookahead_days)
        return start, end


def write_labels(path: str | Path, labels: Iterable[ScenarioLabel]) -> int:
    """Write labels as JSON lines. Returns the number written."""
    return write_jsonl(labels, path)


def read_labels(path: str | Path) -> list[ScenarioLabel]:
    """Read labels from a JSON-lines file; raises ``SchemaError`` on any bad line."""
    return parse_jsonl(path, ScenarioLabel).raise_if_errors()
