"""B17: the plain-language report for Earth that travels with every packet."""

from datetime import datetime, timezone

import pytest
from conftest import DAY_90
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.api.earth_report import MAX_LENGTH, build_report
from orbit.core.interfaces import EarthPacket
from orbit.modules.consent import PRIVATE_LABEL
from orbit.schema import ActionCard, Contributor, RiskAssessment, SignalCategory

PERIOD = {"start": "2027-03-27T00:00:00Z", "end": "2027-04-03T23:59:00Z"}
START = datetime(2027, 3, 27, tzinfo=timezone.utc)
END = datetime(2027, 4, 3, 23, 59, tzinfo=timezone.utc)


def report_for(pipeline, astronaut_id="AST-01", share=None) -> str:
    """Report for the demo period, optionally after changing what is shared."""
    member = pipeline.store.member(astronaut_id)
    if share is not None:
        member = member.model_copy(update={"share_with_earth": frozenset(share)})
        pipeline.store.upsert_crew([member])
    packet = pipeline.earth_packet(astronaut_id, START, END)
    latest = max(packet.assessments, key=lambda a: a.assessed_at)
    return build_report(member, packet, pipeline.store.recommendations(latest.assessment_id))


def test_default_sharing_gives_status_and_keeps_symptoms_private(ran_pipeline):
    text = report_for(ran_pipeline)
    assert text.startswith("AST-01 Vega · ORANGE (70) · mission day 90 · ")
    assert "Skin temperature" in text and "VZV in saliva: 850" in text
    assert "your" not in text, "written for the flight surgeon, not the astronaut"
    lowered = text.lower()
    assert "rash" not in lowered and "fatigue" not in lowered
    assert "2 private reasons" in text and "1 private action" in text
    assert "Reduce workload: VZV is active (crew medical officer)" in text
    assert "Withheld by the astronaut: symptom (" in text and "wellbeing (" in text
    assert PRIVATE_LABEL not in text
    assert "\n" not in text and len(text) <= MAX_LENGTH


def test_sharing_symptoms_shows_the_rash(ran_pipeline):
    everything = set(ran_pipeline.store.member("AST-01").share_with_earth)
    text = report_for(ran_pipeline, share=everything | {SignalCategory.SYMPTOM})
    assert "Rash or tingling: mild in the check-in" in text
    assert "Look after the rash (crew medical officer)" in text
    assert "private" not in text
    assert "symptom (" not in text and "wellbeing (" in text
    assert len(text) <= MAX_LENGTH


def test_sharing_nothing_still_sends_the_status(ran_pipeline):
    text = report_for(ran_pipeline, share=set())
    assert "ORANGE (70)" in text and "mission day 90" in text
    assert "Skin temperature" not in text and "VZV" not in text
    assert "private reasons" in text
    assert "Tell the crew medical officer" in text, "a card without triggers reveals nothing"


def test_same_input_gives_the_same_text(ran_pipeline):
    member = ran_pipeline.store.member("AST-01")
    packet = ran_pipeline.earth_packet("AST-01", START, END)
    assert build_report(member, packet) == build_report(member, packet)
    assert report_for(ran_pipeline) == report_for(ran_pipeline)


def test_healthy_astronaut_and_empty_packet(ran_pipeline):
    text = report_for(ran_pipeline, "AST-02")
    assert text.startswith("AST-02 Altair · GREEN (")
    assert "Actions: Keep your routine" in text

    member = ran_pipeline.store.member("AST-02")
    empty = EarthPacket(astronaut_id="AST-02", created_at=DAY_90)
    assert build_report(member, empty) == (
        "AST-02 Altair · No assessment in this period · Nothing withheld by the astronaut")


def test_long_reasons_and_titles_still_fit(ran_pipeline):
    member = ran_pipeline.store.member("AST-01")
    reasons = tuple(Contributor(label=f"{name} " + "x" * 150, points=10 - i, signal=signal)
                    for i, (name, signal) in enumerate(
                        [("Vital", "skin_temp"), ("Sleep", "sleep_duration"), ("Lab", "crp")]))
    assessment = RiskAssessment(astronaut_id="AST-01", assessed_at=DAY_90, score=60,
                                contributors=reasons)
    packet = EarthPacket(astronaut_id="AST-01", created_at=DAY_90, assessments=(assessment,),
                         withheld={"symptom": 8})
    cards = [ActionCard(card_id=f"card-{i}", level="orange", title="T" * 80, steps=("Do it",),
                        rationale="Because", escalate_to="crew_medical_officer")
             for i in range(3)]
    text = build_report(member, packet, cards)
    assert len(text) <= MAX_LENGTH
    assert "ORANGE (60)" in text and "Actions: 3 actions" in text
    assert text.endswith("Withheld by the astronaut: symptom (8)")


@pytest.fixture
def client(ran_pipeline):
    return TestClient(create_app(ran_pipeline, comms_delay_minutes=20))


def test_send_fills_the_summary_and_the_outbox_shows_it(client):
    response = client.post("/api/crew/AST-01/earth-packet/send", params=PERIOD)
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary.startswith("AST-01 Vega · ORANGE (70)")
    assert "rash" not in summary.lower()
    [listed] = client.get("/api/outbox", params={"astronaut_id": "AST-01"}).json()
    assert listed["summary"] == summary
