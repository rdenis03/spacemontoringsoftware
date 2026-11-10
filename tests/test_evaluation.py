"""Tests for the evaluation metrics (B05), on tiny hand-made inputs."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from orbit.evaluation import (
    alerts,
    episodes,
    evaluate,
    false_alarms,
    lead_times,
    sensitivity,
    summary,
)
from orbit.schema import AlertLevel, RiskAssessment, ScenarioLabel

T0 = datetime(2027, 1, 1, tzinfo=timezone.utc)


def at(day: int, hour: int = 10) -> datetime:
    return T0 + timedelta(days=day, hours=hour)


def assess(day: int, score: float, astronaut: str = "AST-01") -> RiskAssessment:
    return RiskAssessment(astronaut_id=astronaut, assessed_at=at(day), score=score)


def illness(symptom_day: int, astronaut: str = "AST-01", lead: int = 1,
            recovery: int = 5) -> ScenarioLabel:
    return ScenarioLabel(
        label_id=f"{astronaut}-viral-{symptom_day}", astronaut_id=astronaut,
        scenario="viral_reactivation", virus="vzv",
        onset=at(symptom_day - lead, 0), symptom_onset=at(symptom_day),
        resolved=at(symptom_day + recovery, 0), should_alert=True,
    )


def spacewalk(day: int, astronaut: str = "AST-01") -> ScenarioLabel:
    return ScenarioLabel(label_id=f"{astronaut}-eva-{day}", astronaut_id=astronaut,
                         scenario="eva_exertion", onset=at(day, 0),
                         resolved=at(day + 2, 0), should_alert=False)


def scores(values: list[float], astronaut: str = "AST-01", first_day: int = 0):
    return [assess(first_day + i, s, astronaut) for i, s in enumerate(values)]


def test_alerts_use_min_level():
    data = scores([10, 30, 60, 80])  # green, yellow, orange, red
    assert [a.score for a in alerts(data)] == [30, 60, 80]
    assert [a.score for a in alerts(data, AlertLevel.ORANGE)] == [60, 80]
    assert [a.score for a in alerts(data, "red")] == [80]


def test_alert_two_days_before_symptoms_gives_lead_time_2():
    #          day: 0   1   2   3   4   5   6
    data = scores([0,  0,  0, 30, 40, 60, 60])
    label = illness(symptom_day=5, lead=3)  # onset day 2, window from day 0
    assert lead_times(data, [label]) == [2.0]
    assert sensitivity(data, [label]) == 1.0


def test_alert_only_after_window_gives_sensitivity_0():
    data = scores([0, 0, 0, 0, 0, 0, 0, 0, 0, 40])  # alert on day 9
    label = illness(symptom_day=3, recovery=5)  # window ends on day 8 at 00:00
    assert sensitivity(data, [label]) == 0.0
    assert lead_times(data, [label]) == []
    report = false_alarms(data, [label], astronaut_days=10)
    assert report.count == 1 and report.per_30_days == pytest.approx(3.0)


def test_alert_run_during_spacewalk_is_false_and_confounder_alarm():
    data = scores([0, 0, 30, 35, 0, 0])  # alerts on days 2-3
    report = false_alarms(data, [spacewalk(day=2)], astronaut_days=6)
    assert report.count == 1
    assert report.confounder_count == 1
    assert report.fault_count == 0
    assert report.per_30_days == pytest.approx(5.0)


def test_episodes_split_on_a_quiet_day():
    two = episodes(scores([30, 30, 0, 30, 0]))
    assert [(e.start, e.end, e.n_alerts) for e in two] == [
        (at(0), at(1), 2), (at(3), at(3), 1)]
    [one] = episodes(scores([0, 40, 50, 60, 0]))
    assert (one.start, one.end, one.n_alerts) == (at(1), at(3), 3)


def test_episodes_are_per_astronaut():
    data = scores([30, 30, 30]) + scores([0, 30, 0], astronaut="AST-02")
    found = episodes(data)
    assert [(e.astronaut_id, e.n_alerts) for e in found] == [("AST-01", 3), ("AST-02", 1)]


def test_alert_for_another_astronaut_does_not_detect():
    data = scores([0, 0, 0], astronaut="AST-01") + scores([0, 40, 40], astronaut="AST-02")
    assert sensitivity(data, [illness(symptom_day=2, astronaut="AST-01")]) == 0.0


def test_no_labels_gives_none_not_division_error():
    data = scores([30, 0, 0])
    assert sensitivity(data, []) is None
    assert sensitivity(data, [spacewalk(day=5)]) is None  # no should_alert labels
    assert summary([]) == {"n": 0, "median": None, "min": None, "max": None}
    result = evaluate(data, [])
    assert result["sensitivity"] is None and result["confounder_alert_rate"] is None
    assert result["false_alarms"]["count"] == 1
    assert false_alarms(data, [], astronaut_days=0).per_30_days is None


def test_evaluate_bundles_everything_as_json():
    #          day: 0  1  2   3   4   5  6  7  8   9
    data = scores([0, 0, 0, 30, 60, 60, 0, 0, 0, 35])
    labels = [illness(symptom_day=5, lead=2, recovery=3), spacewalk(day=9)]  # window ends day 8
    result = evaluate(data, labels)
    json.dumps(result)  # JSON-ready
    assert result["astronaut_days"] == 10 and result["assessments"] == 10
    assert result["alerts"] == 4 and result["alert_episodes"] == 2
    assert result["labels"] == {"should_alert": 1, "should_not_alert": 1}
    assert result["detected"] == 1 and result["sensitivity"] == 1.0
    assert result["lead_times"] == [2.0]
    assert result["lead_time"] == {"n": 1, "median": 2.0, "min": 2.0, "max": 2.0}
    assert result["false_alarms"] == {"count": 1, "per_30_days": 3.0,
                                      "confounder_count": 1, "fault_count": 0}
    assert result["confounder_alert_rate"] == 1.0
    assert result["by_scenario"] == {
        "viral_reactivation": {"labels": 1, "alerted": 1, "rate": 1.0},
        "eva_exertion": {"labels": 1, "alerted": 1, "rate": 1.0},
    }
    assert evaluate(data, labels, min_level="orange")["lead_times"] == [1.0]


def test_summary_median_and_range():
    assert summary([3.0, -0.125, 1.0, 2.0]) == {"n": 4, "median": 1.5, "min": -0.125, "max": 3.0}
