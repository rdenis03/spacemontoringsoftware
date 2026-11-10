"""Tests for the shared status view (B15): ?view=shared on /status and /day."""

import pytest
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.modules.consent import PRIVATE_LABEL
from orbit.schema import SignalCategory, get_spec

PRIVATE = {SignalCategory.SYMPTOM.value, SignalCategory.WELLBEING.value}


@pytest.fixture
def client(ran_pipeline):
    return TestClient(create_app(ran_pipeline, mission_name="Test mission"))


def _category(signal: str | None) -> str | None:
    return get_spec(signal).category.value if signal else None


def _status(client, view: str | None = None) -> dict:
    params = {"view": view} if view else {}
    response = client.get("/api/crew/AST-01/status", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_shared_status_redacts_symptoms_but_keeps_score_and_level(client):
    full, shared = _status(client), _status(client, "shared")
    assert shared["assessment"]["score"] == full["assessment"]["score"]
    assert shared["assessment"]["level"] == full["assessment"]["level"] == "orange"

    full_reasons = full["assessment"]["contributors"]
    shared_reasons = shared["assessment"]["contributors"]
    assert len(shared_reasons) == len(full_reasons)
    assert sum(r["points"] for r in shared_reasons) == pytest.approx(
        sum(r["points"] for r in full_reasons))
    symptom_reasons = [r for r in full_reasons if _category(r["signal"]) in PRIVATE]
    assert symptom_reasons, "AST-01 reports fatigue and a rash on day 90"
    assert not any("Rash" in r["label"] or "Fatigue" in r["label"] for r in shared_reasons)
    assert sum(r["label"] == PRIVATE_LABEL for r in shared_reasons) == len(symptom_reasons)
    assert not any(r["signal"] and _category(r["signal"]) in PRIVATE for r in shared_reasons)

    assert not any(_category(a["signal"]) in PRIVATE for a in shared["anomalies"])
    assert not any(_category(b["signal"]) in PRIVATE for b in shared["baselines"])
    assert [(c["level"], c["escalate_to"]) for c in shared["actions"]] == [
        (c["level"], c["escalate_to"]) for c in full["actions"]], "level and escalate_to are kept"
    assert any(card["escalate_to"] != "self" for card in shared["actions"])


def _card_text(card: dict) -> str:
    return " ".join([card["card_id"], card["title"], card["rationale"], *card["steps"]]).lower()


def test_shared_cards_do_not_mention_the_rash(client):
    full, shared = _status(client), _status(client, "shared")
    assert any("rash" in _card_text(c) for c in full["actions"]), "the full view names the rash"
    assert not any("rash" in _card_text(c) for c in shared["actions"])
    assert len(shared["actions"]) == len(full["actions"])

    for before, after in zip(full["actions"], shared["actions"], strict=True):
        private = any(_category(s) in PRIVATE for s in before["triggers"])
        if private:  # e.g. reduce-load, triggered by symptom_rash_tingling
            assert after["card_id"].startswith("private-")
            assert after["title"] == "Private action"
            assert after["steps"] == ["Details kept private by the astronaut"]
            assert after["triggers"] == []
            assert before["card_id"] not in _card_text(after)
        else:  # no triggers, or only shared ones: shown in full
            assert after == before


def test_shared_cards_show_in_full_once_symptoms_are_shared(client):
    client.put("/api/crew/AST-01/consent", json={
        "share_with_earth": ["vital", "sleep", "lab", "context", "symptom"]})
    assert _status(client, "shared")["actions"] == _status(client)["actions"]


def test_vital_reasons_are_unchanged(client):
    full, shared = _status(client), _status(client, "shared")

    def vital(reasons):
        return [r for r in reasons if _category(r["signal"]) == "vital"]

    assert vital(full["assessment"]["contributors"])
    assert vital(shared["assessment"]["contributors"]) == vital(full["assessment"]["contributors"])
    assert [a for a in shared["anomalies"] if _category(a["signal"]) == "vital"] == [
        a for a in full["anomalies"] if _category(a["signal"]) == "vital"]


def test_sharing_symptoms_shows_the_rash_reason(client):
    assert not any("Rash" in r["label"]
                   for r in _status(client, "shared")["assessment"]["contributors"])
    response = client.put("/api/crew/AST-01/consent", json={
        "share_with_earth": ["vital", "sleep", "lab", "context", "symptom"]})
    assert response.status_code == 200
    reasons = _status(client, "shared")["assessment"]["contributors"]
    assert any("Rash" in r["label"] for r in reasons)


def test_unshared_category_drops_its_anomalies_and_baselines(client):
    # The starter detector only flags vital and sleep signals, so test the filter with sleep.
    full = _status(client)
    assert any(_category(a["signal"]) == "sleep" for a in full["anomalies"])
    assert any(_category(b["signal"]) == "sleep" for b in full["baselines"])
    client.put("/api/crew/AST-01/consent", json={"share_with_earth": ["vital", "lab", "context"]})
    shared = _status(client, "shared")
    assert not any(_category(a["signal"]) == "sleep" for a in shared["anomalies"])
    assert not any(_category(b["signal"]) == "sleep" for b in shared["baselines"])
    assert any(_category(a["signal"]) == "vital" for a in shared["anomalies"])
    assert not any("Sleep" in r["label"] for r in shared["assessment"]["contributors"])
    assert _status(client) == full, "the full view ignores consent"


def test_full_view_is_unchanged(client):
    assert _status(client) == _status(client, "full")
    assert any("Rash" in r["label"] for r in _status(client)["assessment"]["contributors"])


def test_past_day_has_shared_view_too(client):
    history = client.get("/api/crew/AST-01/assessments").json()
    as_of = history[-1]["assessed_at"]
    full = client.get("/api/crew/AST-01/day", params={"as_of": as_of}).json()
    shared = client.get("/api/crew/AST-01/day", params={"as_of": as_of, "view": "shared"}).json()
    assert shared["assessment"]["score"] == full["assessment"]["score"]
    assert any(r["label"] == PRIVATE_LABEL for r in shared["assessment"]["contributors"])
    assert not any(r["label"] == PRIVATE_LABEL for r in full["assessment"]["contributors"])


def test_unknown_view_gives_422(client):
    response = client.get("/api/crew/AST-01/status", params={"view": "commander"})
    assert response.status_code == 422
