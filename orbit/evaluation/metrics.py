"""Evaluation metrics (M9, task B05): the math behind the pitch numbers.

Compares a list of ``RiskAssessment``s with the simulator's ``ScenarioLabel``s,
using the exact definitions in SPEC M9. Pure functions: no I/O, no clock, no
simulator or pipeline, so they can be tested on tiny hand-made inputs.

Definitions
-----------
* **Alert**: an assessment with ``level >= min_level`` (default yellow).
* **Episode** (of alerts): a run of alerts for one astronaut on consecutive
  calendar days (UTC). A day without an alert ends the run.
* **Window** of a label: ``label.window()``, from ``onset - 2 days`` to
  ``resolved`` (or ``onset + 14 days``), both ends included.
* **Sensitivity**: share of ``should_alert`` labels with at least one alert
  (same astronaut) inside their window. ``None`` when there are no such labels.
* **Lead time**: per detected label, ``symptom_onset - first alert in the
  window``, in days as a float (positive = before symptoms). Exact times are
  used: an alert at 10:00 the day before a 07:00 symptom onset is 0.875 days,
  an alert at 10:00 on symptom day is -0.125.
* **False alarm**: an alert episode that overlaps no ``should_alert`` window of
  the same astronaut. Counted, and per 30 astronaut-days. Reported separately:
  how many false alarms overlap a confounder window (spacewalk, sleep shift,
  solar particle event) and how many overlap a fault window (sensor fault,
  missing data).
* **Confounder alert rate**: share of confounder labels with at least one alert
  in their window.

``evaluate(...)`` returns this JSON-ready dict (B06 calls it once per config and seed)::

    {
      "min_level": "yellow",
      "astronaut_days": 720,             # given, or distinct (astronaut, UTC date) assessed
      "assessments": 720,
      "alerts": 41,
      "alert_episodes": 12,
      "labels": {"should_alert": 8, "should_not_alert": 63},
      "detected": 7,                     # should_alert labels with an alert in the window
      "sensitivity": 0.875,              # or None
      "lead_times": [1.875, 0.875, ...], # days, one per detected label, in label order
      "lead_time": {"n": 7, "median": 0.875, "min": -0.125, "max": 1.875},  # None values if n = 0
      "false_alarms": {"count": 4, "per_30_days": 0.167,   # per_30_days None if no astronaut-days
                       "confounder_count": 2, "fault_count": 0},
      "confounder_alert_rate": 0.12,     # or None
      "by_scenario": {"viral_reactivation": {"labels": 6, "alerted": 5, "rate": 0.833}, ...},
    }

Numbers are not rounded. ``by_scenario`` has one entry per scenario type that
has labels; ``alerted`` counts labels with an alert in their window (for an
illness that is "detected").
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from orbit.schema import AlertLevel, RiskAssessment, ScenarioLabel, ScenarioType

CONFOUNDER_SCENARIOS = frozenset({
    ScenarioType.EVA_EXERTION, ScenarioType.SLEEP_SHIFT, ScenarioType.SOLAR_PARTICLE_EVENT,
})
FAULT_SCENARIOS = frozenset({ScenarioType.SENSOR_FAULT, ScenarioType.MISSING_DATA})
DAY = timedelta(days=1)


@dataclass(frozen=True)
class Episode:
    """A run of alerts for one astronaut on consecutive days."""

    astronaut_id: str
    start: datetime  # first alert's assessed_at
    end: datetime  # last alert's assessed_at
    n_alerts: int = 1


@dataclass(frozen=True)
class FalseAlarmReport:
    count: int
    per_30_days: float | None
    confounder_count: int
    fault_count: int


def _level(min_level: AlertLevel | str) -> AlertLevel:
    return AlertLevel(min_level)


def alerts(assessments: Iterable[RiskAssessment],
           min_level: AlertLevel | str = AlertLevel.YELLOW) -> list[RiskAssessment]:
    """Assessments at or above ``min_level``, sorted by astronaut then time."""
    rank = _level(min_level).rank
    found = [a for a in assessments if a.level.rank >= rank]
    return sorted(found, key=lambda a: (a.astronaut_id, a.assessed_at))


def episodes(assessments: Iterable[RiskAssessment],
             min_level: AlertLevel | str = AlertLevel.YELLOW) -> list[Episode]:
    """Runs of alerts on consecutive UTC days, per astronaut."""
    out: list[Episode] = []
    current: Episode | None = None
    for alert in alerts(assessments, min_level):
        if (current is not None and current.astronaut_id == alert.astronaut_id
                and (alert.assessed_at.date() - current.end.date()).days <= 1):
            current = Episode(current.astronaut_id, current.start, alert.assessed_at,
                              current.n_alerts + 1)
        else:
            if current is not None:
                out.append(current)
            current = Episode(alert.astronaut_id, alert.assessed_at, alert.assessed_at)
    if current is not None:
        out.append(current)
    return out


def _in_window(when: datetime, label: ScenarioLabel) -> bool:
    start, end = label.window()
    return start <= when <= end


def _overlaps(episode: Episode, label: ScenarioLabel) -> bool:
    start, end = label.window()
    return (episode.astronaut_id == label.astronaut_id
            and episode.start <= end and episode.end >= start)


def _first_alert(label: ScenarioLabel, found: Sequence[RiskAssessment]) -> RiskAssessment | None:
    return next((a for a in found
                 if a.astronaut_id == label.astronaut_id and _in_window(a.assessed_at, label)),
                None)


def sensitivity(assessments: Iterable[RiskAssessment], labels: Iterable[ScenarioLabel],
                min_level: AlertLevel | str = AlertLevel.YELLOW) -> float | None:
    """Share of should_alert labels with at least one alert in their window."""
    found = alerts(assessments, min_level)
    targets = [label for label in labels if label.should_alert]
    if not targets:
        return None
    return sum(_first_alert(label, found) is not None for label in targets) / len(targets)


def lead_times(assessments: Iterable[RiskAssessment], labels: Iterable[ScenarioLabel],
               min_level: AlertLevel | str = AlertLevel.YELLOW) -> list[float]:
    """Days from the first alert in the window to symptom onset, per detected label."""
    found = alerts(assessments, min_level)
    out = []
    for label in labels:
        if not label.should_alert or label.symptom_onset is None:
            continue
        first = _first_alert(label, found)
        if first is not None:
            out.append((label.symptom_onset - first.assessed_at) / DAY)
    return out


def summary(values: Sequence[float]) -> dict[str, float | int | None]:
    """Median, min and max (None when empty), and how many values."""
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None}
    return {"n": len(values), "median": median(values), "min": min(values), "max": max(values)}


def false_alarms(assessments: Iterable[RiskAssessment], labels: Iterable[ScenarioLabel],
                 min_level: AlertLevel | str = AlertLevel.YELLOW,
                 astronaut_days: int | None = None) -> FalseAlarmReport:
    """Alert episodes that overlap no should_alert window of the same astronaut."""
    labels = list(labels)
    illness = [label for label in labels if label.should_alert]
    confounders = [label for label in labels if label.scenario in CONFOUNDER_SCENARIOS]
    faults = [label for label in labels if label.scenario in FAULT_SCENARIOS]
    false = [e for e in episodes(assessments, min_level)
             if not any(_overlaps(e, label) for label in illness)]
    return FalseAlarmReport(
        count=len(false),
        per_30_days=len(false) * 30 / astronaut_days if astronaut_days else None,
        confounder_count=sum(any(_overlaps(e, label) for label in confounders) for e in false),
        fault_count=sum(any(_overlaps(e, label) for label in faults) for e in false),
    )


def evaluate(assessments: Iterable[RiskAssessment], labels: Iterable[ScenarioLabel],
             min_level: AlertLevel | str = AlertLevel.YELLOW,
             astronaut_days: int | None = None) -> dict:
    """All metrics in one JSON-ready dict (keys in the module docstring)."""
    assessments, labels, level = list(assessments), list(labels), _level(min_level)
    if astronaut_days is None:
        astronaut_days = len({(a.astronaut_id, a.assessed_at.date()) for a in assessments})
    found = alerts(assessments, level)
    times = lead_times(assessments, labels, level)
    report = false_alarms(assessments, labels, level, astronaut_days)

    by_scenario: dict[str, dict] = {}
    for scenario in ScenarioType:
        group = [label for label in labels if label.scenario is scenario]
        if group:
            alerted = sum(_first_alert(label, found) is not None for label in group)
            by_scenario[scenario.value] = {"labels": len(group), "alerted": alerted,
                                           "rate": alerted / len(group)}
    confounders = [label for label in labels if label.scenario in CONFOUNDER_SCENARIOS]
    targets = [label for label in labels if label.should_alert]

    return {
        "min_level": level.value,
        "astronaut_days": astronaut_days,
        "assessments": len(assessments),
        "alerts": len(found),
        "alert_episodes": len(episodes(assessments, level)),
        "labels": {"should_alert": len(targets), "should_not_alert": len(labels) - len(targets)},
        "detected": sum(_first_alert(label, found) is not None for label in targets),
        "sensitivity": sensitivity(assessments, labels, level),
        "lead_times": times,
        "lead_time": summary(times),
        "false_alarms": {"count": report.count, "per_30_days": report.per_30_days,
                         "confounder_count": report.confounder_count,
                         "fault_count": report.fault_count},
        "confounder_alert_rate": (
            sum(_first_alert(label, found) is not None for label in confounders) / len(confounders)
            if confounders else None),
        "by_scenario": by_scenario,
    }
