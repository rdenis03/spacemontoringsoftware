"""Tests for the consent editing endpoint (B14): PUT /api/crew/{id}/consent."""

import pytest
from fastapi.testclient import TestClient

from orbit.api import create_app

WEEK = {"start": "2027-03-28T00:00:00Z", "end": "2027-04-03T23:59:59Z"}


@pytest.fixture
def client(ran_pipeline):
    return TestClient(create_app(ran_pipeline, mission_name="Test mission"))


def _crew(client):
    return {m["astronaut_id"]: m for m in client.get("/api/crew").json()}


def test_put_consent_changes_crew_list(client):
    response = client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital"]})
    assert response.status_code == 200, response.text
    assert response.json()["share_with_earth"] == ["vital"]
    crew = _crew(client)
    assert crew["AST-01"]["share_with_earth"] == ["vital"]
    assert set(crew["AST-02"]["share_with_earth"]) == {"vital", "sleep", "lab", "context"}
    assert crew["AST-01"]["callsign"] == "Vega", "other fields are kept"


def test_earth_packet_follows_new_consent(client):
    before = client.get("/api/crew/AST-01/earth-packet", params=WEEK).json()
    assert any(o["signal"] == "sleep_duration" for o in before["observations"])

    client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital"]})
    packet = client.get("/api/crew/AST-01/earth-packet", params=WEEK).json()
    signals = {o["signal"] for o in packet["observations"]}
    assert "sleep_duration" not in signals and "sleep_efficiency" not in signals
    assert "skin_temp" in signals
    assert packet["withheld"]["sleep"] > 0
    assert packet["assessments"], "score and level are always sent"


def test_empty_list_shares_nothing_but_score(client):
    response = client.put("/api/crew/AST-01/consent", json={"share_with_earth": []})
    assert response.status_code == 200
    assert response.json()["share_with_earth"] == []
    packet = client.get("/api/crew/AST-01/earth-packet", params=WEEK).json()
    assert packet["observations"] == []
    assert sum(packet["withheld"].values()) > 0
    assert all(a["level"] for a in packet["assessments"])


def test_unknown_category_gives_422(client):
    response = client.put("/api/crew/AST-01/consent",
                          json={"share_with_earth": ["vital", "dreams"]})
    assert response.status_code == 422
    assert "dreams" in response.text
    assert set(_crew(client)["AST-01"]["share_with_earth"]) == {"vital", "sleep", "lab", "context"}


def test_unknown_astronaut_gives_404(client):
    response = client.put("/api/crew/AST-99/consent", json={"share_with_earth": ["vital"]})
    assert response.status_code == 404
