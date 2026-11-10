"""B18: ORBIT queues a report for Earth by itself on orange or red."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import CONFIG, DAY_89, DAY_90
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.core import ConfigError, load_settings
from orbit.schema import SignalCategory

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
RASH = {"symptoms": {"symptom_fatigue": 2, "symptom_rash_tingling": 1}, "mood": 3, "stress": 3}


def app_for(pipeline, level="orange", **options):
    return TestClient(create_app(pipeline, comms_delay_minutes=20, clock=lambda: T0,
                                 auto_send_level=level, **options))


def auto_packets(client, astronaut_id=None):
    params = {"astronaut_id": astronaut_id} if astronaut_id else {}
    return [item for item in client.get("/api/outbox", params=params).json() if item["auto"]]


def checkin(client, astronaut_id, when, body=RASH):
    response = client.post(f"/api/crew/{astronaut_id}/checkin",
                           json={"timestamp": when.isoformat(), **body})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def until_day_89(loaded_pipeline):
    """Assessed up to day 89: AST-01 is yellow, nobody is orange yet."""
    loaded_pipeline.run(end=DAY_89.date())
    return loaded_pipeline


# ---- config ----------------------------------------------------------------------


def test_level_comes_from_the_config(tmp_path):
    assert load_settings(CONFIG).comms_auto_send_level == "orange"
    off = tmp_path / "off.toml"
    off.write_text('[comms]\nauto_send_level = "off"\n', encoding="utf-8")
    assert load_settings(off).comms_auto_send_level == "off"
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    assert load_settings(empty).comms_auto_send_level == "orange"
    bad = tmp_path / "bad.toml"
    bad.write_text('[comms]\nauto_send_level = "purple"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="auto_send_level"):
        load_settings(bad)


def test_health_reports_the_level(ran_pipeline):
    assert app_for(ran_pipeline).get("/api/health").json()["comms"]["auto_send_level"] == "orange"


# ---- the hook --------------------------------------------------------------------


def test_checkin_to_orange_queues_one_auto_packet(until_day_89):
    client = app_for(until_day_89)
    assert auto_packets(client) == [], "yellow on day 89 sends nothing"

    result = checkin(client, "AST-01", DAY_90.replace(hour=8))
    assert result["assessment"]["level"] == "orange"
    [packet] = auto_packets(client)
    assert packet["id"] == "auto-AST-01-20270403" and packet["astronaut_id"] == "AST-01"
    assert packet["status"] == "queued" and packet["seconds_left"] == pytest.approx(1200)
    assert packet["summary"].startswith("AST-01 Vega · ORANGE (")
    # The packet covers the last 3 days up to the assessment.
    times = [datetime.fromisoformat(o["timestamp"]) for o in packet["packet"]["observations"]]
    as_of = DAY_90.replace(hour=8)
    assert times and as_of - timedelta(days=3) <= min(times) and max(times) <= as_of
    assert packet["packet"]["assessments"][-1]["assessed_at"].startswith("2027-04-03T08:00")

    # A second check-in the same day queues nothing more, and keeps the first packet.
    checkin(client, "AST-01", DAY_90.replace(hour=20))
    assert [p["id"] for p in auto_packets(client)] == ["auto-AST-01-20270403"]
    assert auto_packets(client)[0]["packet"] == packet["packet"]


def test_green_astronaut_gets_none(ran_pipeline):
    client = app_for(ran_pipeline)
    checkin(client, "AST-02", DAY_90.replace(hour=20), {"symptoms": {}, "mood": 4, "stress": 2})
    assert auto_packets(client, "AST-02") == []


def test_off_sends_nothing(ran_pipeline):
    client = app_for(ran_pipeline, level="off")
    checkin(client, "AST-01", DAY_90.replace(hour=20))
    assert client.get("/api/outbox").json() == []
    # create_app without the option is also off, so other tests see an empty outbox.
    assert TestClient(create_app(ran_pipeline)).get("/api/outbox").json() == []


def test_level_red_ignores_orange(ran_pipeline):
    assert auto_packets(app_for(ran_pipeline, level="red")) == []


# ---- startup ---------------------------------------------------------------------


def test_startup_sends_for_whoever_is_already_orange(ran_pipeline):
    client = app_for(ran_pipeline)  # like `serve`: assessed before the app exists
    [packet] = auto_packets(client)
    assert packet["id"] == "auto-AST-01-20270403"
    assert packet["summary"].startswith("AST-01 Vega · ORANGE (")
    # A restart on the same database does not send it again.
    assert len(auto_packets(app_for(ran_pipeline))) == 1


def test_rerunning_the_pipeline_sends_once_per_day(ran_pipeline):
    client = app_for(ran_pipeline)
    assert client.post("/api/pipeline/run", json={}).status_code == 200
    assert client.post("/api/pipeline/run", json={}).status_code == 200
    assert [p["id"] for p in auto_packets(client)] == ["auto-AST-01-20270403"]


# ---- consent and failures --------------------------------------------------------


def test_auto_packet_respects_consent(until_day_89):
    client = app_for(until_day_89)
    checkin(client, "AST-01", DAY_90.replace(hour=8))
    [packet] = auto_packets(client)
    private = {SignalCategory.SYMPTOM.value, SignalCategory.WELLBEING.value}
    assert private.isdisjoint(packet["sent"]) and private <= set(packet["withheld"])
    assert all(not o["signal"].startswith("symptom_") for o in packet["packet"]["observations"])
    assert "rash" not in packet["summary"].lower()
    assert "private reason" in packet["summary"]


def test_a_failed_send_does_not_break_the_assessment(until_day_89, monkeypatch):
    client = app_for(until_day_89)

    def broken(entry):
        raise RuntimeError("outbox is full")

    monkeypatch.setattr(until_day_89.store, "queue", broken)
    result = checkin(client, "AST-01", DAY_90.replace(hour=8))
    assert result["assessment"]["level"] == "orange" and result["errors"] == []
    assert client.get("/api/outbox").json() == []
