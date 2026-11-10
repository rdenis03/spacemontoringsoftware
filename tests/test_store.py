from datetime import datetime, timedelta, timezone

import pytest

from orbit.core import DayResult, Store, StoreError
from orbit.schema import ContextEvent, CrewMember, Observation, RiskAssessment

UTC = timezone.utc
T0 = datetime(2027, 4, 1, 6, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.upsert_crew([CrewMember(astronaut_id="AST-01", callsign="Vega", mission_start=T0)])
    return s


def reading(day: int, value: float, **extra) -> Observation:
    return Observation(observation_id=f"o{day}", astronaut_id="AST-01",
                       timestamp=T0 + timedelta(days=day), signal="resting_hr",
                       value=value, source="wearable", **extra)


def test_observations_are_idempotent_and_ordered(store):
    store.add_observations([reading(2, 54), reading(0, 52), reading(1, 53)])
    store.add_observations([reading(1, 53.5)])  # same id: replaces, no duplicate
    values = [o.value for o in store.observations("AST-01")]
    assert values == [52, 53.5, 54]


def test_observation_filters(store):
    store.add_observations([reading(0, 52), reading(1, 120, quality="bad"), reading(2, 54)])
    assert len(store.observations("AST-01")) == 2
    assert len(store.observations("AST-01", usable_only=False)) == 3
    assert len(store.observations("AST-01", start=T0 + timedelta(days=1))) == 1
    assert store.observations("AST-01", signals=["skin_temp"]) == []
    assert store.observations("AST-01", signals=[]) == []
    first, last = store.data_range("AST-01")
    assert first == T0 and last == T0 + timedelta(days=2)
    assert store.data_range("AST-99") is None


def test_events_include_crew_wide_and_overlap(store):
    store.add_events([
        ContextEvent(event_id="sep", event_type="solar_particle_event",
                     start=T0, end=T0 + timedelta(hours=12)),
        ContextEvent(event_id="eva", event_type="eva", astronaut_id="AST-02",
                     start=T0 + timedelta(hours=2)),
    ])
    assert [e.event_id for e in store.events("AST-01")] == ["sep"]
    assert len(store.events()) == 2
    later = T0 + timedelta(days=1)
    assert store.events("AST-01", start=later, end=later + timedelta(days=1)) == []


def test_save_day_replaces_earlier_run(store):
    def result(score):
        return DayResult(
            astronaut_id="AST-01", as_of=T0, mission_day=1,
            assessment=RiskAssessment(astronaut_id="AST-01", assessed_at=T0, score=score),
        )

    store.save_day(result(10))
    store.save_day(result(60))
    assert [a.score for a in store.assessments("AST-01")] == [60]
    assert store.latest_assessment("AST-01").level.value == "orange"
    assert store.counts()["assessments"] == 1


def test_store_persists_to_file(tmp_path):
    path = tmp_path / "db" / "orbit.db"
    first = Store(path)
    first.upsert_crew([CrewMember(astronaut_id="AST-01", callsign="Vega", mission_start=T0)])
    first.close()
    assert Store(path).member("AST-01").callsign == "Vega"


def test_schema_major_version_mismatch(tmp_path):
    path = tmp_path / "old.db"
    s = Store(path)
    s._conn.execute("UPDATE meta SET value='0.9.0' WHERE key='schema_version'")
    s._conn.commit()
    s.close()
    with pytest.raises(StoreError, match="schema 0.9.0"):
        Store(path)


def test_naive_query_time_rejected(store):
    with pytest.raises(ValueError, match="timezone"):
        store.observations("AST-01", start=datetime(2027, 4, 1))
