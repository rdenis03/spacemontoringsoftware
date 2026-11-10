from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from orbit.schema import (
    ActionCard,
    AlertLevel,
    Anomaly,
    ContextEvent,
    CrewMember,
    Observation,
    Quality,
    RiskAssessment,
    SignalCategory,
    level_for_score,
)

UTC = timezone.utc


def obs(**overrides):
    data = dict(
        astronaut_id="AST-01",
        timestamp="2027-04-03T06:00:00Z",
        signal="skin_temp",
        value=34.6,
        source="wearable",
    )
    data.update(overrides)
    return Observation(**data)


# ---- Observation ------------------------------------------------------------


def test_valid_observation_fills_unit_and_defaults():
    o = obs()
    assert o.unit == "degC"
    assert o.quality is Quality.GOOD
    assert o.is_usable
    assert len(o.observation_id) == 32


def test_timestamp_converted_to_utc():
    o = obs(timestamp="2027-04-03T09:00:00+03:00")
    assert o.timestamp == datetime(2027, 4, 3, 6, tzinfo=UTC)
    assert o.timestamp.tzinfo is UTC


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError, match="must include a timezone"):
        obs(timestamp="2027-04-03T06:00:00")


def test_wrong_unit_rejected():
    with pytest.raises(ValidationError, match="expected 'degC'"):
        obs(unit="degF", value=94.3)


def test_explicit_correct_unit_accepted():
    assert obs(unit="degC").unit == "degC"


def test_unknown_signal_rejected():
    with pytest.raises(ValidationError, match="signal"):
        obs(signal="blood_magic")


def test_wrong_source_rejected():
    with pytest.raises(ValidationError, match="cannot report skin_temp"):
        obs(source="checkin")


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_rejected(value):
    with pytest.raises(ValidationError, match="finite"):
        obs(value=value)


def test_implausible_good_value_rejected_but_bad_value_kept():
    with pytest.raises(ValidationError, match="outside the plausible range"):
        obs(value=55)
    stored = obs(value=55, quality="bad")
    assert stored.quality is Quality.BAD
    assert not stored.is_usable


def test_ordinal_must_be_whole_number():
    assert obs(signal="symptom_fatigue", value=2, source="checkin").value == 2
    with pytest.raises(ValidationError, match="whole-number"):
        obs(signal="symptom_fatigue", value=1.5, source="checkin")
    with pytest.raises(ValidationError, match="plausible range"):
        obs(signal="mood", value=0, source="checkin")


def test_bad_astronaut_id_rejected():
    with pytest.raises(ValidationError, match="astronaut_id"):
        obs(astronaut_id="AST 01")


def test_unknown_field_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        obs(temprature=34.6)


def test_observation_is_immutable():
    o = obs()
    with pytest.raises(ValidationError):
        o.value = 40.0


def test_json_round_trip():
    o = obs(note="first night after EVA")
    assert Observation.model_validate_json(o.model_dump_json()) == o


# ---- ContextEvent and CrewMember ---------------------------------------------


def test_event_end_before_start_rejected():
    with pytest.raises(ValidationError, match="before its start"):
        ContextEvent(event_type="eva", start="2027-04-03T10:00:00Z", end="2027-04-03T09:00:00Z")


def test_event_scope_and_overlap():
    crew_wide = ContextEvent(event_type="solar_particle_event", start="2027-04-02T14:00:00Z",
                             end="2027-04-03T02:00:00Z")
    personal = ContextEvent(event_type="eva", start="2027-04-01T08:00:00Z",
                            astronaut_id="AST-01")
    assert crew_wide.affects("AST-02")
    assert personal.affects("AST-01") and not personal.affects("AST-02")
    day = datetime(2027, 4, 3, tzinfo=UTC)
    assert crew_wide.overlaps(day, day + timedelta(days=1))
    assert not personal.overlaps(day, day + timedelta(days=1))


def test_mission_day_and_consent():
    member = CrewMember(astronaut_id="AST-01", callsign="Vega",
                        mission_start="2027-01-04T00:00:00Z")
    assert member.mission_day(datetime(2027, 1, 4, 23, tzinfo=UTC)) == 1
    assert member.mission_day(datetime(2027, 4, 3, 6, tzinfo=UTC)) == 90
    assert member.mission_day(datetime(2027, 1, 3, tzinfo=UTC)) == 0  # pre-launch
    assert member.shares(SignalCategory.VITAL)
    assert not member.shares(SignalCategory.SYMPTOM)


# ---- Outputs -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "level"),
    [(0, "green"), (24.9, "green"), (25, "yellow"), (49.9, "yellow"),
     (50, "orange"), (72, "orange"), (75, "red"), (100, "red")],
)
def test_level_for_score(score, level):
    assert level_for_score(score) is AlertLevel(level)


def test_risk_assessment_derives_level_and_sorts_reasons():
    risk = RiskAssessment(
        astronaut_id="AST-01", assessed_at="2027-04-03T10:00:00Z", score=72,
        contributors=[{"label": "small", "points": 4}, {"label": "big", "points": 24},
                      {"label": "medium", "points": 14}],
    )
    assert risk.level is AlertLevel.ORANGE
    assert [c.label for c in risk.top_reasons(2)] == ["big", "medium"]


def test_risk_assessment_level_must_match_score():
    with pytest.raises(ValidationError, match="does not match score"):
        RiskAssessment(astronaut_id="AST-01", assessed_at="2027-04-03T10:00:00Z",
                       score=72, level="green")


def test_risk_score_bounds():
    with pytest.raises(ValidationError):
        RiskAssessment(astronaut_id="AST-01", assessed_at="2027-04-03T10:00:00Z", score=101)


def test_alert_levels_are_ordered():
    assert AlertLevel.RED.rank > AlertLevel.ORANGE.rank > AlertLevel.YELLOW.rank > AlertLevel.GREEN.rank


def test_anomaly_delta():
    a = Anomaly(astronaut_id="AST-01", signal="skin_temp", detected_at="2027-04-03T06:00:00Z",
                kind="drift", value=34.9, baseline_center=34.45, baseline_spread=0.12,
                deviation=3.75, consecutive_days=2)
    assert a.delta == pytest.approx(0.45)


def test_action_card_needs_steps():
    with pytest.raises(ValidationError):
        ActionCard(card_id="empty", level="yellow", title="Nothing", steps=(), rationale="x")
    with pytest.raises(ValidationError, match="card_id"):
        ActionCard(card_id="Not A Slug", level="yellow", title="t", steps=("a",), rationale="x")
