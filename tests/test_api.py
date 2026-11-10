import pytest
from conftest import DAY_90
from fastapi.testclient import TestClient

from orbit.api import create_app


@pytest.fixture
def client(ran_pipeline):
    return TestClient(create_app(ran_pipeline, mission_name="Test mission"))


def test_health_and_signals(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["modules"]["detector"] == "robust_z"
    assert health["counts"]["observations"] == 800
    signals = client.get("/api/signals").json()
    assert signals["alert_level_order"] == ["green", "yellow", "orange", "red"]


def test_overview_and_status(client):
    overview = {row["astronaut_id"]: row for row in client.get("/api/overview").json()}
    assert overview["AST-01"]["level"] == "orange"
    assert overview["AST-02"]["level"] == "green"

    status = client.get("/api/crew/AST-01/status").json()
    assert status["mission_day"] == 90
    assert status["assessment"]["contributors"][0]["points"] > 0
    assert status["actions"][0]["card_id"] == "reduce-load"


def test_chart_data(client):
    temps = client.get("/api/crew/AST-01/observations",
                       params={"signal": "skin_temp", "start": "2027-04-01T00:00:00Z"}).json()
    assert [o["signal"] for o in temps] == ["skin_temp"] * 3
    both = client.get("/api/crew/AST-01/observations",
                      params=[("signal", "skin_temp"), ("signal", "hrv_rmssd")]).json()
    assert {o["signal"] for o in both} == {"skin_temp", "hrv_rmssd"}
    band = client.get("/api/crew/AST-01/baselines", params={"signal": "skin_temp"}).json()
    assert band and band[-1]["spread"] > 0
    trend = client.get("/api/crew/AST-01/assessments").json()
    assert len(trend) == 21


def test_bad_readings_hidden_unless_asked(client):
    normal = client.get("/api/crew/AST-02/observations", params={"signal": "skin_temp"}).json()
    everything = client.get("/api/crew/AST-02/observations",
                            params={"signal": "skin_temp", "include_bad": True}).json()
    assert len(everything) == len(normal) + 1


def test_checkin_updates_status_immediately(client):
    when = (DAY_90.replace(hour=20)).isoformat()
    result = client.post("/api/crew/AST-02/checkin", json={
        "timestamp": when,
        "symptoms": {"symptom_fever_chills": 2, "symptom_sore_throat": 2},
        "mood": 2, "stress": 4,
    }).json()
    assert result["assessment"]["score"] > 20
    assert client.get("/api/crew/AST-02/status").json()["as_of"].startswith("2027-04-03T20:00")


def test_checkin_validation(client):
    wrong_signal = client.post("/api/crew/AST-01/checkin",
                               json={"symptoms": {"skin_temp": 1}})
    assert wrong_signal.status_code == 422
    out_of_scale = client.post("/api/crew/AST-01/checkin",
                               json={"symptoms": {"symptom_fatigue": 7}})
    assert out_of_scale.status_code == 422
    assert client.post("/api/crew/AST-99/checkin", json={}).status_code == 404


def test_push_observations(client):
    response = client.post("/api/observations", json=[
        {"astronaut_id": "AST-01", "timestamp": "2027-04-04T06:00:00Z",
         "signal": "skin_temp", "value": 34.5, "source": "wearable"},
        {"astronaut_id": "AST-01", "timestamp": "2027-04-04T06:00:00",
         "signal": "skin_temp", "value": 34.5, "source": "wearable"},
        {"astronaut_id": "AST-77", "timestamp": "2027-04-04T06:00:00Z",
         "signal": "skin_temp", "value": 34.5, "source": "wearable"},
    ]).json()
    assert response["accepted"] == 1 and response["rejected"] == 2
    assert any("timezone" in e for e in response["errors"])


def test_earth_packet_and_run(client):
    packet = client.get("/api/crew/AST-01/earth-packet",
                        params={"start": "2027-04-01T00:00:00Z",
                                "end": "2027-04-03T23:59:00Z"}).json()
    assert packet["withheld"]["symptom"] > 0
    run = client.post("/api/pipeline/run", json={"start": "2027-04-03", "end": "2027-04-03"})
    assert run.json()["assessed"] == 2


def test_unknown_astronaut_404(client):
    assert client.get("/api/crew/AST-99/status").status_code == 404
    assert client.get("/api/crew/AST-99/observations").status_code == 404
