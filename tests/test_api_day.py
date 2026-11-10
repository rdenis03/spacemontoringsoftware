"""Tests for the past-day endpoint (B13): GET /api/crew/{id}/day?as_of=."""

import pytest
from conftest import DAY_90
from fastapi.testclient import TestClient

from orbit.api import create_app


@pytest.fixture
def client(ran_pipeline):
    return TestClient(create_app(ran_pipeline, mission_name="Test mission"))


def test_every_assessment_can_be_replayed(client):
    history = client.get("/api/crew/AST-01/assessments").json()
    assert len(history) == 21
    for item in history:
        response = client.get("/api/crew/AST-01/day", params={"as_of": item["assessed_at"]})
        assert response.status_code == 200, response.text
        day = response.json()
        assert day["as_of"] == item["assessed_at"]
        assert day["assessment"]["score"] == item["score"]
        assert day["assessment"]["level"] == item["level"]
        assert day["actions"], "every saved day has at least one action card"


def test_latest_day_equals_status(client):
    status = client.get("/api/crew/AST-01/status").json()
    day = client.get("/api/crew/AST-01/day", params={"as_of": status["as_of"]}).json()
    assert day["assessment"]["score"] == status["assessment"]["score"]
    assert [c["card_id"] for c in day["actions"]] == [c["card_id"] for c in status["actions"]]
    assert day["mission_day"] == status["mission_day"] == 90
    assert len(day["anomalies"]) == len(status["anomalies"]) > 0
    assert len(day["baselines"]) == len(status["baselines"]) > 0


def test_past_day_has_its_own_result(client):
    day_89 = client.get("/api/crew/AST-01/day",
                        params={"as_of": "2027-04-02T10:00:00Z"}).json()
    assert day_89["mission_day"] == 89
    assert day_89["assessment"]["level"] == "yellow"


def test_naive_time_is_utc_and_offsets_work(client):
    naive = client.get("/api/crew/AST-01/day", params={"as_of": "2027-04-03T10:00:00"})
    offset = client.get("/api/crew/AST-01/day", params={"as_of": "2027-04-03T12:00:00+02:00"})
    assert naive.status_code == offset.status_code == 200
    assert naive.json()["as_of"] == offset.json()["as_of"] == DAY_90.isoformat().replace(
        "+00:00", "Z")


def test_time_without_assessment_gives_404(client):
    response = client.get("/api/crew/AST-01/day", params={"as_of": "2027-04-03T11:00:00Z"})
    assert response.status_code == 404
    assert "no assessment" in response.json()["detail"]


def test_unknown_astronaut_gives_404(client):
    response = client.get("/api/crew/AST-99/day", params={"as_of": DAY_90.isoformat()})
    assert response.status_code == 404
    assert "unknown astronaut" in response.json()["detail"]


def test_missing_as_of_gives_422(client):
    assert client.get("/api/crew/AST-01/day").status_code == 422


def test_endpoint_in_openapi_docs(client):
    assert "/api/crew/{astronaut_id}/day" in client.get("/openapi.json").json()["paths"]
