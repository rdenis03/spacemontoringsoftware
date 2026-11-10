"""B16: outbox with comms delay (M13). Consent (B14) and the shared view (B15)
have their own tests in test_api_consent.py and test_api_shared.py."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from conftest import CONFIG
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.core import Store, load_settings
from orbit.core.interfaces import EarthPacket
from orbit.core.store import OutboxEntry

PERIOD = {"start": "2027-03-27T00:00:00Z", "end": "2027-04-03T23:59:00Z"}
T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class Clock:
    """A settable UTC clock so delivery can be tested without waiting."""

    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return Clock(T0)


@pytest.fixture
def client(ran_pipeline, clock):
    return TestClient(create_app(ran_pipeline, comms_delay_minutes=20, clock=clock))


def send(client, **params):
    response = client.post("/api/crew/AST-01/earth-packet/send", params={**PERIOD, **params})
    assert response.status_code == 200, response.text
    return response.json()


# ---- config ----------------------------------------------------------------------


def test_comms_delay_from_config():
    assert load_settings(CONFIG).comms_delay_minutes == 20


def test_comms_delay_must_be_sane(tmp_path):
    bad = tmp_path / "orbit.toml"
    bad.write_text("[comms]\none_way_delay_minutes = -1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one_way_delay_minutes"):
        load_settings(bad)


def test_health_reports_the_delay(client):
    assert client.get("/api/health").json()["comms"]["one_way_delay_minutes"] == 20


# ---- send and deliver ------------------------------------------------------------------


def test_zero_delay_is_delivered_at_once(client):
    item = send(client, delay_minutes=0)
    assert item["status"] == "delivered" and item["seconds_left"] == 0


def test_default_delay_queues_then_delivers(client, clock):
    item = send(client)
    assert item["status"] == "queued"
    assert item["seconds_left"] == pytest.approx(1200)
    assert datetime.fromisoformat(item["deliver_at"]) - datetime.fromisoformat(item["created_at"]) == timedelta(minutes=20)
    assert item["summary"].startswith("AST-01 Vega")  # B17's report (tests/test_earth_report.py)
    assert item["auto"] is False  # set by B18

    clock.now = T0 + timedelta(minutes=19)
    assert client.get("/api/outbox").json()[0]["status"] == "queued"
    clock.now = T0 + timedelta(minutes=20)
    delivered = client.get("/api/outbox").json()[0]
    assert delivered["status"] == "delivered" and delivered["seconds_left"] == 0


def test_moon_delay_override(client):
    item = send(client, delay_minutes=0.022)
    assert item["seconds_left"] == pytest.approx(1.32)


def test_packet_holds_no_private_readings(client):
    client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital"]})
    item = send(client)
    assert {o["signal"] for o in item["packet"]["observations"]} <= {
        "skin_temp", "resting_hr", "hrv_rmssd", "resp_rate", "spo2"}
    assert set(item["sent"]) == {"vital"}
    assert {"symptom", "wellbeing", "sleep", "lab", "context"} <= set(item["withheld"])
    # score and level always travel
    day90 = next(a for a in item["packet"]["assessments"] if a["assessed_at"].startswith("2027-04-03"))
    assert day90["level"] == "orange"


def test_sent_plus_withheld_is_every_reading(client):
    item = send(client)
    everything = client.get("/api/crew/AST-01/observations", params={**PERIOD, "include_bad": True}).json()
    assert sum(item["sent"].values()) + sum(item["withheld"].values()) == len(everything)


def test_outbox_is_newest_first_and_filters(client, clock):
    send(client)
    clock.now = T0 + timedelta(minutes=1)
    assert client.post("/api/crew/AST-02/earth-packet/send", params=PERIOD).status_code == 200
    assert [i["astronaut_id"] for i in client.get("/api/outbox").json()] == ["AST-02", "AST-01"]
    assert [i["astronaut_id"] for i in client.get("/api/outbox", params={"astronaut_id": "AST-01"}).json()] == ["AST-01"]
    assert client.get("/api/health").json()["counts"]["outbox"] == 2


def test_send_errors(client):
    backwards = {"start": PERIOD["end"], "end": PERIOD["start"]}
    assert client.post("/api/crew/AST-01/earth-packet/send", params=backwards).status_code == 422
    assert client.post("/api/crew/AST-99/earth-packet/send", params=PERIOD).status_code == 404
    assert client.get("/api/outbox", params={"astronaut_id": "AST-99"}).status_code == 404


# ---- store -------------------------------------------------------------------------------


def entry(packet_id="pkt-1", astronaut="AST-01"):
    return OutboxEntry(id=packet_id, astronaut_id=astronaut, created_at=T0, deliver_at=T0 + timedelta(minutes=5),
                       packet=EarthPacket(astronaut_id=astronaut, created_at=T0))


def test_outbox_survives_a_restart(tmp_path):
    path = tmp_path / "orbit.db"
    store = Store(path)
    store.queue(entry())
    store.queue(entry())  # same id replaces
    store.close()
    again = Store(path)
    assert again.outbox() == [entry()]
    assert again.outbox("AST-02") == []
    assert again.counts()["outbox"] == 1


def test_old_database_without_outbox_still_opens(tmp_path):
    path = tmp_path / "old.db"
    Store(path).close()
    with sqlite3.connect(path) as db:  # a database made before B16
        db.execute("DROP TABLE outbox")
    store = Store(path)
    assert store.counts()["outbox"] == 0
    store.queue(entry())
    assert len(store.outbox()) == 1
