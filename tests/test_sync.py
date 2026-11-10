"""M13 sync and consent (consent editing, outbox with comms delay) and the M14 shared view."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import CONFIG
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.core import Store, load_settings
from orbit.core.interfaces import EarthPacket
from orbit.core.store import OutboxEntry
from orbit.modules.consent import PRIVATE_LABEL

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
    return TestClient(create_app(ran_pipeline, one_way_delay_minutes=20, clock=clock))


# ---- config ----------------------------------------------------------------------


def test_comms_delay_from_config():
    assert load_settings(CONFIG).one_way_delay_minutes == 20


def test_comms_delay_must_be_sane(tmp_path):
    bad = tmp_path / "orbit.toml"
    bad.write_text("[comms]\none_way_delay_minutes = -1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one_way_delay_minutes"):
        load_settings(bad)


def test_health_reports_the_delay(client):
    assert client.get("/api/health").json()["comms"]["one_way_delay_minutes"] == 20


# ---- consent ---------------------------------------------------------------------


def test_consent_update_changes_what_is_shared(client):
    member = client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital", "symptom"]}).json()
    assert set(member["share_with_earth"]) == {"symptom", "vital"}  # a set: order is not defined
    packet = client.get("/api/crew/AST-01/earth-packet", params=PERIOD).json()
    sent = {o["signal"] for o in packet["observations"]}
    assert any(s.startswith("symptom_") for s in sent)
    assert "sleep" in packet["withheld"] and "lab" in packet["withheld"]


def test_consent_rejects_unknown_categories(client):
    response = client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital", "diary"]})
    assert response.status_code == 422


def test_consent_unknown_astronaut(client):
    assert client.put("/api/crew/AST-99/consent", json={"share_with_earth": []}).status_code == 404


# ---- outbox --------------------------------------------------------------------------


def test_send_queues_with_the_comms_delay(client, clock):
    item = client.post("/api/crew/AST-01/earth-packet/send", params=PERIOD).json()
    assert item["status"] == "queued"
    assert item["delay_minutes"] == 20
    assert item["seconds_to_delivery"] == pytest.approx(20 * 60)
    assert datetime.fromisoformat(item["deliver_at"]) - datetime.fromisoformat(item["created_at"]) == timedelta(minutes=20)

    clock.now = T0 + timedelta(minutes=19)
    assert client.get("/api/outbox").json()[0]["status"] == "queued"
    clock.now = T0 + timedelta(minutes=20)
    delivered = client.get("/api/outbox").json()[0]
    assert delivered["status"] == "delivered" and delivered["seconds_to_delivery"] == 0


def test_send_delay_override_for_the_moon(client):
    item = client.post("/api/crew/AST-01/earth-packet/send", params={**PERIOD, "delay_minutes": 0.022}).json()
    assert item["delay_minutes"] == pytest.approx(0.022)
    assert item["seconds_to_delivery"] == pytest.approx(1.32)


def test_private_categories_never_leave(client):
    client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital"]})
    item = client.post("/api/crew/AST-01/earth-packet/send", params=PERIOD).json()
    assert set(item["sent"]) == {"vital"}
    assert {"symptom", "wellbeing", "sleep", "lab", "context"} <= set(item["withheld"])
    # score and level always travel, private reasons are redacted
    day90 = next(a for a in item["packet"]["assessments"] if a["assessed_at"].startswith("2027-04-03"))
    assert day90["level"] == "orange" and day90["score"] > 50
    labels = [c["label"] for c in day90["contributors"]]
    assert PRIVATE_LABEL in labels
    assert not any("check-in" in label for label in labels)
    assert all(c["signal"] is None or c["signal"] in {"skin_temp", "hrv_rmssd", "resting_hr", "resp_rate", "spo2"}
               for c in day90["contributors"])


def test_withheld_counts_are_exact(client):
    item = client.post("/api/crew/AST-01/earth-packet/send", params=PERIOD).json()
    everything = client.get("/api/crew/AST-01/observations",
                            params={**PERIOD, "include_bad": True}).json()
    assert sum(item["sent"].values()) + sum(item["withheld"].values()) == len(everything)


def test_outbox_filters_and_orders(client, clock):
    client.post("/api/crew/AST-01/earth-packet/send", params=PERIOD)
    clock.now = T0 + timedelta(minutes=1)
    client.post("/api/crew/AST-02/earth-packet/send", params=PERIOD)
    everyone = client.get("/api/outbox").json()
    assert [i["astronaut_id"] for i in everyone] == ["AST-02", "AST-01"]  # newest first
    assert [i["astronaut_id"] for i in client.get("/api/outbox", params={"astronaut_id": "AST-01"}).json()] == ["AST-01"]
    assert client.get("/api/health").json()["counts"]["outbox"] == 2


def test_send_rejects_a_backwards_period(client):
    response = client.post("/api/crew/AST-01/earth-packet/send",
                           params={"start": PERIOD["end"], "end": PERIOD["start"]})
    assert response.status_code == 422


def test_outbox_survives_a_restart(tmp_path):
    path = tmp_path / "orbit.db"
    entry = OutboxEntry(packet_id="pkt-1", astronaut_id="AST-01", created_at=T0, deliver_at=T0 + timedelta(minutes=5),
                        delay_minutes=5, start=T0, end=T0, packet=EarthPacket(astronaut_id="AST-01", created_at=T0))
    store = Store(path)
    store.queue_packet(entry)
    store.queue_packet(entry)  # same id replaces
    store.close()
    again = Store(path)
    assert again.outbox() == [entry]
    assert again.outbox("AST-02") == []


# ---- M14 shared view --------------------------------------------------------------------


def test_shared_status_hides_private_reasons(client):
    full = client.get("/api/crew/AST-01/status").json()
    shared = client.get("/api/crew/AST-01/status", params={"view": "shared"}).json()
    assert shared["assessment"]["score"] == full["assessment"]["score"]
    assert shared["assessment"]["level"] == full["assessment"]["level"]
    full_labels = [c["label"] for c in full["assessment"]["contributors"]]
    shared_labels = [c["label"] for c in shared["assessment"]["contributors"]]
    assert any("check-in" in label for label in full_labels)
    assert not any("check-in" in label for label in shared_labels)
    assert PRIVATE_LABEL in shared_labels
    assert sum(c["points"] for c in shared["assessment"]["contributors"]) == pytest.approx(
        sum(c["points"] for c in full["assessment"]["contributors"]))


def test_shared_status_drops_private_anomalies(client):
    client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["context"]})
    shared = client.get("/api/crew/AST-01/status", params={"view": "shared"}).json()
    assert shared["anomalies"] == [] and shared["baselines"] == []
    assert client.get("/api/crew/AST-01/status").json()["anomalies"]  # the astronaut still sees them


def test_status_view_must_be_known(client):
    assert client.get("/api/crew/AST-01/status", params={"view": "secret"}).status_code == 422
