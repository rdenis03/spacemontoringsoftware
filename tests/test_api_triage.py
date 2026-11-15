"""M15 triage endpoints (task B23, step 7)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.modules.consent import PRIVATE_LABEL
from orbit.triage.config import load_triage_settings
from orbit.triage.service import TriageService

WALL = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)
AT_1030 = "2027-04-02T10:30:00Z"  # day 89, mission time
WORKED_EXAMPLE = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."
BASE = "/api/crew/AST-01/triage"


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock(WALL)


def make_client(settings, pipeline, clock, **options):
    triage = TriageService.from_settings(load_triage_settings(settings), pipeline, clock=clock)
    return TestClient(create_app(pipeline, clock=clock, triage=triage, **options))


@pytest.fixture
def day89_pipeline(loaded_pipeline):
    """Assessed up to day 89 10:00, so a chat at 10:30 becomes the latest status."""
    loaded_pipeline.run(end=date(2027, 4, 2))
    return loaded_pipeline


@pytest.fixture
def client(settings, day89_pipeline, clock):
    return make_client(settings, day89_pipeline, clock)


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def run_chat(client, text=WORKED_EXAMPLE, timestamp=AT_1030, replies=("moderate", True, "none")):
    result = ok(client.post(BASE, json={"text": text, "timestamp": timestamp}))
    session_id = result["session_id"]
    for reply in replies:
        question = result["next_question"]
        result = ok(client.post(f"{BASE}/{session_id}/answer",
                                json={"question_id": question["question_id"], "value": reply}))
    return session_id, result


def card_ids(cards):
    return [c["card_id"] for c in cards]


def test_worked_example_through_the_api(client):
    first = ok(client.post(BASE, json={"text": WORKED_EXAMPLE, "timestamp": AT_1030}))
    assert first["status"] == "asking" and first["next_question"]["question_id"] == "rash-tingling"
    assert first["next_question"]["choices"] == ["none", "mild", "moderate", "severe"]
    assert [f["signal"] for f in first["findings"]] == ["symptom_rash_tingling", "symptom_fatigue"]
    assert first["as_of"].startswith("2027-04-02T10:30")

    session_id, ready = run_chat(client)
    assert ready["status"] == "ready" and ready["next_question"] is None
    assert ready["ranking"][0]["pattern"] == "vzv_like" and ready["ranking"][0]["probability"] >= 0.8
    assert ready["ranking"][0]["label"] == "Signs that fit shingles (VZV)"

    confirmed = ok(client.post(f"{BASE}/{session_id}/confirm", json={}))
    assert confirmed["result"]["status"] == "confirmed"
    day = confirmed["day"]
    assert day["assessment"]["level"] == "yellow" and day["assessment"]["score"] == 44.7
    merged = card_ids(day["actions"])
    assert merged[0] == "saliva-test" and {"watch-patch", "rest-watch"} <= set(merged)

    status = ok(client.get("/api/crew/AST-01/status"))
    assert status["as_of"].startswith("2027-04-02T10:30")
    assert status["assessment"]["level"] == "yellow" and status["assessment"]["score"] == 44.7
    assert card_ids(status["actions"]) == merged
    past = ok(client.get("/api/crew/AST-01/day", params={"as_of": AT_1030}))
    assert card_ids(past["actions"]) == merged

    session = ok(client.get(f"{BASE}/{session_id}"))
    assert session["status"] == "confirmed" and session["reports"][0]["text"] == WORKED_EXAMPLE


def test_shared_view_hides_the_patch_card(client):
    session_id, _ = run_chat(client)
    ok(client.post(f"{BASE}/{session_id}/confirm"))
    full = ok(client.get("/api/crew/AST-01/status"))
    shared = ok(client.get("/api/crew/AST-01/status", params={"view": "shared"}))
    index = card_ids(full["actions"]).index("watch-patch")
    assert shared["actions"][index]["title"] == "Private action"
    assert shared["actions"][index]["card_id"].startswith("private-")
    assert "patch" not in str(shared["actions"]).lower()
    assert shared["actions"][0] == full["actions"][0], "saliva-test triggers on vitals: shown in full"
    assert shared["assessment"]["score"] == 44.7
    reasons = shared["assessment"]["contributors"]
    assert not any("Rash" in r["label"] for r in reasons) and any(r["label"] == PRIVATE_LABEL for r in reasons)


def test_overview_shows_red_flag_at(client, clock):
    def red_flags():
        return {row["astronaut_id"]: row["red_flag_at"] for row in ok(client.get("/api/overview"))}

    assert red_flags() == {"AST-01": None, "AST-02": None}
    flagged = ok(client.post(BASE, json={"text": "I can't breathe properly", "timestamp": AT_1030}))
    assert flagged["status"] == "escalated" and flagged["red_flags"] == ["breathing"]
    assert flagged["procedures"][0]["card_id"] == "rf-breathing" and flagged["next_question"] is None
    seen = red_flags()
    assert seen["AST-01"].startswith("2027-04-02T10:30") and seen["AST-02"] is None
    clock.now = WALL + timedelta(hours=25)
    assert red_flags()["AST-01"] is None


def test_list_and_cancel(client, clock):
    first = ok(client.post(BASE, json={"text": "tired", "timestamp": AT_1030}))["session_id"]
    clock.now = WALL + timedelta(minutes=5)
    second = ok(client.post(BASE, json={"text": "headache", "timestamp": AT_1030}))["session_id"]
    listed = ok(client.get(BASE))
    assert [s["session_id"] for s in listed] == [second, first]
    later = ok(client.get(BASE, params={"start": (WALL + timedelta(minutes=1)).isoformat()}))
    assert [s["session_id"] for s in later] == [second]
    cancelled = ok(client.post(f"{BASE}/{first}/cancel"))
    assert cancelled["status"] == "cancelled"
    assert ok(client.get("/api/crew/AST-02/triage")) == []


def test_previews_do_not_auto_send_but_confirm_does(settings, day89_pipeline, clock):
    client = make_client(settings, day89_pipeline, clock, auto_send_level="orange")
    assert ok(client.get("/api/outbox")) == []  # the latest status (day 89) is yellow
    session_id, _ = run_chat(client, timestamp="2027-04-03T10:30:00Z", replies=())
    ok(client.post(f"{BASE}/{session_id}/answer", json={"done": True}))
    assert ok(client.get("/api/outbox")) == [], "unsaved previews send nothing (B18)"
    confirmed = ok(client.post(f"{BASE}/{session_id}/confirm",
                               json={"corrections": {"symptom_rash_tingling": 2, "symptom_fever_chills": 0}}))
    assert confirmed["day"]["assessment"]["level"] == "red" and confirmed["day"]["assessment"]["score"] == 77.2
    assert [p["id"] for p in ok(client.get("/api/outbox"))] == ["auto-AST-01-20270403"]


def test_health_lists_the_triage_modules(client):
    triage = ok(client.get("/api/health"))["triage"]
    assert triage == {"modules": {"extractor": "lexicon", "reasoner": "rules"},
                      "model_version": "lexicon-0.1+rules-0.1"}


# ---- errors ------------------------------------------------------------------------------


def test_404s(client):
    assert client.post("/api/crew/AST-99/triage", json={"text": "tired"}).status_code == 404
    assert client.get(f"{BASE}/tri-nope").status_code == 404
    assert client.post(f"{BASE}/tri-nope/answer", json={"done": True}).status_code == 404
    session_id = ok(client.post(BASE, json={"text": "tired", "timestamp": AT_1030}))["session_id"]
    assert client.get(f"/api/crew/AST-02/triage/{session_id}").status_code == 404, "another astronaut's chat"
    assert client.get("/api/crew/AST-99/triage").status_code == 404


def test_409s(client, clock):
    session_id, _ = run_chat(client)
    ok(client.post(f"{BASE}/{session_id}/confirm"))
    again = client.post(f"{BASE}/{session_id}/confirm")
    assert again.status_code == 409 and "confirmed" in again.json()["detail"]
    other = ok(client.post(BASE, json={"text": "tired", "timestamp": AT_1030}))["session_id"]
    ok(client.post(f"{BASE}/{other}/cancel"))
    assert client.post(f"{BASE}/{other}/answer", json={"done": True}).status_code == 409
    old = ok(client.post(BASE, json={"text": "tired", "timestamp": AT_1030}))["session_id"]
    clock.now = WALL + timedelta(hours=3)
    expired = client.post(f"{BASE}/{old}/answer", json={"text": "still tired"})
    assert expired.status_code == 409 and "expired" in expired.json()["detail"]


def test_422s(client):
    first = ok(client.post(BASE, json={"text": WORKED_EXAMPLE, "timestamp": AT_1030}))
    url = f"{BASE}/{first['session_id']}"
    bad_value = client.post(f"{url}/answer", json={"question_id": "rash-tingling", "value": "very"})
    assert bad_value.status_code == 422 and "not an answer" in bad_value.json()["detail"]
    wrong = client.post(f"{url}/answer", json={"question_id": "one-side", "value": True})
    assert wrong.status_code == 422 and "not the open question" in wrong.json()["detail"]
    assert client.post(f"{url}/answer", json={}).status_code == 422
    assert client.post(BASE, json={"text": "x" * 1001}).status_code == 422
    assert client.post(BASE, json={"text": ""}).status_code == 422
    not_symptom = client.post(f"{url}/confirm", json={"corrections": {"skin_temp": 1}})
    assert not_symptom.status_code == 422 and "not a symptom" in not_symptom.json()["detail"]
    assert client.post(f"{url}/confirm", json={"corrections": {"sneezing": 1}}).status_code == 422
    assert client.post(f"{url}/confirm", json={"corrections": {"symptom_fatigue": 9}}).status_code == 422
    assert ok(client.get(url))["status"] == "asking", "nothing changed by the bad requests"


@pytest.mark.parametrize("severity", [True, "2", 2.0])
def test_corrections_take_only_whole_numbers(client, severity):
    url = f"{BASE}/{ok(client.post(BASE, json={'text': 'tired', 'timestamp': AT_1030}))['session_id']}"
    response = client.post(f"{url}/confirm", json={"corrections": {"symptom_fatigue": severity}})
    assert response.status_code == 422, response.text
    assert ok(client.get(url))["status"] != "confirmed"
    assert ok(client.post(f"{url}/confirm", json={"corrections": {"symptom_fatigue": 2}}))["result"]["status"] \
        == "confirmed"


def test_triage_has_no_shared_view(client):
    session_id = ok(client.post(BASE, json={"text": "tired", "timestamp": AT_1030}))["session_id"]
    for url in (f"{BASE}/{session_id}", BASE):
        for view in ("shared", "full"):
            response = client.get(url, params={"view": view})
            assert response.status_code == 400 and response.json()["detail"] == \
                "Triage sessions have no shared view"
    response = client.post(f"{BASE}/{session_id}/answer", params={"view": "shared"}, json={"done": True})
    assert response.status_code == 400
    assert ok(client.get(f"{BASE}/{session_id}"))["status"] == "asking", "nothing happened"


# ---- the red-flag gate: no request shape can drop an urgent message -------------------------

T = AT_1030


def _start_bodies(phrase):
    return {
        "well-formed": {"text": phrase, "timestamp": T},
        "missing field": {"timestamp": T, "value": phrase},  # no text
        "unknown question_id": {"text": phrase, "timestamp": T, "question_id": "nope"},
        "wrong type": {"text": phrase, "timestamp": ["not", "a", "time"]},
        "text over 1,000": {"text": "x " * 600 + phrase + " now", "timestamp": T},
        "extra field": {"text": "tired", "timestamp": T, "comment": phrase},
        "text is a number": {"text": 42, "timestamp": T, "notes": [phrase]},
        "non-JSON": f"{phrase}, please help",
    }


def _answer_bodies(phrase, open_question):
    return {
        "well-formed": {"text": phrase},
        "missing field": {"value": phrase},  # a value without its question_id
        "unknown question_id": {"question_id": "nope", "value": "yes", "text": phrase},
        "wrong type": {"question_id": open_question, "value": {"details": phrase}},
        "text over 1,000": {"text": "x " * 600 + phrase + " now"},
        "extra field": {"question_id": open_question, "value": 2, "comment": phrase},
        "text is a number": {"text": 42, "notes": [phrase]},
        "non-JSON": f"{phrase}, please help",
    }


CASES = list(_start_bodies("x"))
PHRASES = {"I can't breathe": "breathing", "chest pain": "chest"}


def _post(client, url, body):
    if isinstance(body, str):
        return client.post(url, content=body.encode(), headers={"content-type": "text/plain"})
    return client.post(url, json=body)


def _red_flag_at(client, astronaut="AST-01"):
    return {row["astronaut_id"]: row["red_flag_at"] for row in ok(client.get("/api/overview"))}[astronaut]


@pytest.mark.parametrize("phrase", PHRASES)
@pytest.mark.parametrize("case", CASES)
def test_gate_on_start(client, phrase, case):
    assert _red_flag_at(client) is None
    result = ok(_post(client, BASE, _start_bodies(phrase)[case]))
    assert result["status"] == "escalated" and PHRASES[phrase] in result["red_flags"], result
    assert result["procedures"][0]["card_id"].startswith("rf-")
    stored = ok(client.get(f"{BASE}/{result['session_id']}"))  # a session exists and holds the flag
    assert stored["status"] == "escalated" and PHRASES[phrase] in stored["result"]["red_flags"]
    kept = [r["text"] for r in stored["reports"]]
    if case == "text over 1,000":
        assert kept[0].startswith("x x") and len(kept[0]) <= 1000  # the first 1,000 characters
    else:
        assert any(phrase.lower() in text.lower() for text in kept), kept
    assert _red_flag_at(client) is not None
    if case == "text over 1,000":
        assert any("cut to its first 1,000" in e for e in result["errors"])
    if case != "well-formed":
        assert result["errors"], "the problem is reported, not dropped"


@pytest.mark.parametrize("phrase", PHRASES)
@pytest.mark.parametrize("case", CASES)
def test_gate_on_answer(client, phrase, case):
    first = ok(client.post(BASE, json={"text": WORKED_EXAMPLE, "timestamp": T}))
    open_question = first["next_question"]["question_id"]
    assert _red_flag_at(client) is None
    response = _post(client, f"{BASE}/{first['session_id']}/answer", _answer_bodies(phrase, open_question)[case])
    result = ok(response)
    assert result["session_id"] == first["session_id"]
    assert result["status"] == "escalated" and PHRASES[phrase] in result["red_flags"], result
    stored = ok(client.get(f"{BASE}/{first['session_id']}"))
    assert stored["status"] == "escalated" and len(stored["reports"]) == 2, "the urgent words are kept"
    assert _red_flag_at(client) == "2027-04-02T10:30:00Z"


def test_structured_screening_answer_escalates_despite_invalid_text(client):
    first = ok(client.post(BASE, json={"text": "Fever since last night", "timestamp": T}))
    assert first["next_question"]["question_id"] == "screen-breathing"
    result = ok(client.post(f"{BASE}/{first['session_id']}/answer",
                            json={"question_id": "screen-breathing", "value": "yes", "text": 123}))
    assert result["status"] == "escalated" and result["red_flags"] == ["breathing"]
    assert any("text must be" in e for e in result["errors"])
    assert _red_flag_at(client) is not None


def test_flag_to_a_closed_or_unknown_session_starts_an_escalated_one(client):
    done = ok(client.post(BASE, json={"text": "tired", "timestamp": T}))["session_id"]
    ok(client.post(f"{BASE}/{done}/cancel"))
    for session_id in (done, "tri-nope"):
        result = ok(client.post(f"{BASE}/{session_id}/answer", json={"text": "chest pain"}))
        assert result["status"] == "escalated" and result["session_id"] != session_id
        assert any(e.startswith("session: ") for e in result["errors"])
    assert client.post(f"{BASE}/{done}/answer", json={"text": "tired"}).status_code == 409, "no flag: as before"


def test_flagged_confirm_and_cancel_bodies_escalate(client):
    session_id = ok(client.post(BASE, json={"text": "tired", "timestamp": T}))["session_id"]
    bad = ok(client.post(f"{BASE}/{session_id}/confirm",
                         json={"corrections": {"symptom_fatigue": "chest pain"}}))
    assert bad["day"] is None and bad["result"]["status"] == "escalated"
    assert ok(client.post(f"{BASE}/{session_id}/cancel", content=b"I can't breathe",
                          headers={"content-type": "text/plain"}))["status"] == "escalated"
    assert _red_flag_at(client) is not None


def test_flagged_body_is_not_refused_for_a_view_parameter(client):
    result = ok(client.post(BASE, params={"view": "shared"}, json={"text": "I can't breathe", "timestamp": T}))
    assert result["status"] == "escalated"
    assert client.post(BASE, params={"view": "shared"}, json={"text": "tired"}).status_code == 400


def test_default_app_has_a_built_in_triage_service(ran_pipeline):
    client = TestClient(create_app(ran_pipeline))
    result = ok(client.post(BASE, json={"text": WORKED_EXAMPLE, "timestamp": AT_1030}))
    assert result["next_question"]["question_id"] == "rash-tingling"
    assert ok(client.get("/api/health"))["triage"]["modules"] == {
        "extractor": "LexiconExtractor", "reasoner": "RulesReasoner"}
