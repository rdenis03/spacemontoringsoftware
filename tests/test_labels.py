"""Tests for scenario labels (B01): validation, window and JSONL round trip."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from orbit.schema import (
    ALERTING_SCENARIOS,
    ScenarioLabel,
    ScenarioType,
    read_labels,
    write_labels,
)

ONSET = datetime(2027, 3, 31, 6, tzinfo=timezone.utc)


def viral(**overrides) -> ScenarioLabel:
    fields = dict(
        label_id="AST-01-viral-1",
        astronaut_id="AST-01",
        scenario=ScenarioType.VIRAL_REACTIVATION,
        virus="vzv",
        onset=ONSET,
        symptom_onset=ONSET + timedelta(days=2),
        resolved=ONSET + timedelta(days=9),
        should_alert=True,
        notes="shingles reactivation",
    )
    fields.update(overrides)
    return ScenarioLabel(**fields)


def test_scenario_types_are_exactly_eight():
    assert {t.value for t in ScenarioType} == {
        "viral_reactivation", "respiratory_infection", "eva_exertion", "sleep_shift",
        "solar_particle_event", "sensor_fault", "missing_data", "stress_load",
    }
    assert ALERTING_SCENARIOS == {
        ScenarioType.VIRAL_REACTIVATION, ScenarioType.RESPIRATORY_INFECTION,
    }


def test_valid_viral_label_builds():
    label = viral()
    assert label.scenario is ScenarioType.VIRAL_REACTIVATION
    assert label.virus == "vzv"
    assert label.should_alert is True


def test_non_utc_time_is_converted_to_utc():
    plus_two = timezone(timedelta(hours=2))
    label = viral(onset=datetime(2027, 3, 31, 8, tzinfo=plus_two))
    assert label.onset == ONSET
    assert label.onset.tzinfo == timezone.utc


def test_naive_datetime_is_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        viral(onset=datetime(2027, 3, 31, 6), symptom_onset=None, resolved=None)


def test_symptom_onset_before_onset_is_rejected():
    with pytest.raises(ValidationError, match="symptom_onset must not be before onset"):
        viral(symptom_onset=ONSET - timedelta(hours=1))


def test_resolved_before_onset_is_rejected():
    with pytest.raises(ValidationError, match="resolved must not be before onset"):
        viral(resolved=ONSET - timedelta(days=1))


def test_confounder_that_should_alert_is_rejected():
    with pytest.raises(ValidationError, match="should_alert must be False"):
        viral(scenario=ScenarioType.EVA_EXERTION, virus=None, should_alert=True)


def test_alerting_scenario_with_should_alert_false_is_rejected():
    with pytest.raises(ValidationError, match="should_alert must be True"):
        viral(should_alert=False)


def test_viral_label_without_virus_is_rejected():
    with pytest.raises(ValidationError, match="virus is required"):
        viral(virus=None)


def test_virus_on_non_viral_scenario_is_rejected():
    with pytest.raises(ValidationError, match="virus must be None"):
        viral(scenario=ScenarioType.RESPIRATORY_INFECTION, virus="ebv")


def test_unknown_virus_is_rejected():
    with pytest.raises(ValidationError):
        viral(virus="flu")


def test_window_with_resolved():
    label = viral()
    assert label.window() == (ONSET - timedelta(days=2), ONSET + timedelta(days=9))


def test_window_without_resolved_uses_lookahead():
    label = viral(resolved=None)
    assert label.window() == (ONSET - timedelta(days=2), ONSET + timedelta(days=14))
    assert label.window(lookahead_days=5)[1] == ONSET + timedelta(days=5)


def test_write_then_read_gives_equal_labels(tmp_path):
    labels = [
        viral(),
        viral(label_id="AST-02-resp-1", astronaut_id="AST-02",
              scenario=ScenarioType.RESPIRATORY_INFECTION, virus=None, resolved=None),
        ScenarioLabel(label_id="AST-03-eva-1", astronaut_id="AST-03",
                      scenario=ScenarioType.EVA_EXERTION, onset=ONSET, should_alert=False),
    ]
    path = tmp_path / "sim" / "labels.jsonl"
    assert write_labels(path, labels) == 3
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3
    assert read_labels(path) == labels
