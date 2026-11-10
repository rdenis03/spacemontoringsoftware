"""M10 action engine (``protocol``) and the hand-written card library (task B19)."""

import re
from pathlib import Path

import pytest
from conftest import DAY_89, DAY_90, ROOT

from orbit.core import create
from orbit.modules.actions import CardLibraryError, ProtocolActionEngine, check_library
from orbit.schema import (
    ActionCard,
    AlertLevel,
    Contributor,
    EscalationTarget,
    RiskAssessment,
    get_spec,
    parse_jsonl,
)

LIBRARY = ROOT / "cards" / "action_cards.jsonl"


@pytest.fixture
def ctx(loaded_pipeline):
    return loaded_pipeline.context("AST-01", DAY_90)


@pytest.fixture
def engine():
    return ProtocolActionEngine(cards_path=str(LIBRARY))


def assessment(score: float, *reasons: tuple[str | None, float]) -> RiskAssessment:
    return RiskAssessment(
        astronaut_id="AST-01",
        assessed_at=DAY_90,
        score=score,
        contributors=tuple(
            Contributor(label=f"reason {i}", points=points, signal=signal) for i, (signal, points) in enumerate(reasons)
        ),
    )


# ---- the library ----------------------------------------------------------------


def test_library_validates_and_meets_the_rules():
    cards = tuple(parse_jsonl(LIBRARY, ActionCard).raise_if_errors())
    check_library(cards)  # raises if a rule is broken
    assert {c.level for c in cards} == set(AlertLevel)


def test_library_text_is_short_and_has_no_doses():
    for card in parse_jsonl(LIBRARY, ActionCard).raise_if_errors():
        assert all(len(step) < 200 for step in card.steps), card.card_id
        assert not any(re.search(r"\d\s*mg", step, re.IGNORECASE) for step in card.steps), card.card_id
        text = " ".join((card.title, card.rationale, *card.steps)).lower()
        assert not any(word in text for word in ("tablet", "dose", "pill")), card.card_id


def test_each_card_triggers_one_category():
    # B15's shared view hides a card with any private trigger; one category per card
    # keeps the harmless lab and vital cards visible to the crew.
    for card in parse_jsonl(LIBRARY, ActionCard).raise_if_errors():
        assert len({get_spec(s).category for s in card.triggers}) <= 1, card.card_id


def test_virus_specific_cards_exist():
    triggers = {s for card in parse_jsonl(LIBRARY, ActionCard).raise_if_errors() for s in card.triggers}
    assert {"saliva_vzv_dna", "saliva_hsv1_dna", "saliva_ebv_dna", "symptom_rash_tingling",
            "symptom_mouth_sores", "symptom_swollen_glands", "symptom_fever_chills", "crp"} <= triggers


def test_config_points_at_the_library(settings):
    actions = settings.modules["actions"]
    assert actions.use == "protocol"
    assert Path(actions.options["cards_path"]) == LIBRARY


@pytest.mark.parametrize(
    "cards, problem",
    [
        (
            [ActionCard(card_id="g", level="green", title="t", steps=("s",), rationale="r")],
            "no general card",
        ),
        (
            [
                ActionCard(card_id=lvl, level=lvl, title="t", steps=("s",), rationale="r",
                           escalate_to="crew_medical_officer" if lvl in ("orange", "red") else "self")
                for lvl in ("green", "yellow", "orange", "red")
            ]
            + [ActionCard(card_id="mixed", level="orange", title="t", steps=("s",), rationale="r",
                          escalate_to="crew_medical_officer",
                          triggers=("saliva_vzv_dna", "symptom_rash_tingling"))],
            "triggers mix categories",
        ),
        (
            [
                ActionCard(card_id=lvl, level=lvl, title="t", steps=("s",), rationale="r",
                           escalate_to="crew_medical_officer" if lvl in ("orange", "red") else "self")
                for lvl in ("green", "yellow", "orange", "red")
            ]
            + [ActionCard(card_id="quiet", level="red", title="t", steps=("s",), rationale="r")],
            "must set escalate_to",
        ),
    ],
)
def test_check_library_rejects_broken_libraries(cards, problem):
    with pytest.raises(CardLibraryError, match=problem):
        check_library(tuple(cards))


def test_engine_refuses_a_broken_library(tmp_path):
    bad = tmp_path / "cards.jsonl"
    bad.write_text(
        '{"card_id":"only","level":"green","title":"t","steps":["s"],"rationale":"r"}\n', encoding="utf-8"
    )
    with pytest.raises(CardLibraryError):
        ProtocolActionEngine(cards_path=str(bad))


# ---- choosing cards ---------------------------------------------------------------


def test_card_explaining_most_of_the_score_comes_first(engine, ctx):
    # Mouth sores outweigh the fever, so the HSV-1 card leads.
    cards = engine.recommend(assessment(60, ("symptom_mouth_sores", 30), ("symptom_fever_chills", 10)), ctx)
    assert [c.card_id for c in cards][:2] == ["mouth-care", "limit-spread"]
    cards = engine.recommend(assessment(60, ("symptom_mouth_sores", 5), ("symptom_fever_chills", 30)), ctx)
    assert [c.card_id for c in cards][:2] == ["limit-spread", "mouth-care"]


def test_general_card_follows_specific_ones(engine, ctx):
    cards = engine.recommend(assessment(60, ("symptom_rash_tingling", 20)), ctx)
    assert [c.card_id for c in cards] == ["protect-rash", "tell-cmo"]


def test_red_day_without_red_specific_card_keeps_the_specific_steps(engine, ctx):
    # No red card fits a rash and fever, so the general red card leads and
    # the most relevant orange cards follow, still never above red.
    cards = engine.recommend(assessment(90, ("symptom_rash_tingling", 20), ("symptom_fever_chills", 10)), ctx)
    assert [c.card_id for c in cards] == ["isolate-consult", "protect-rash", "limit-spread"]


def test_red_specific_card_comes_first_when_it_fits(engine, ctx):
    cards = engine.recommend(assessment(90, ("spo2", 20), ("symptom_rash_tingling", 20)), ctx)
    assert [c.card_id for c in cards] == ["check-oxygen", "isolate-consult"]


def test_no_reasons_gives_the_general_card(engine, ctx):
    cards = engine.recommend(assessment(30), ctx)
    assert [c.card_id for c in cards] == ["rest-watch"]


@pytest.mark.parametrize("score", [0, 10, 30, 45, 60, 74, 80, 100])
def test_never_above_level_and_at_most_max_cards(engine, ctx, score):
    many = [(s, 5.0) for s in ("skin_temp", "spo2", "sleep_duration", "stress", "crp", "symptom_mouth_sores")]
    a = assessment(score, *many)
    cards = engine.recommend(a, ctx)
    assert 1 <= len(cards) <= 3
    assert all(c.level.rank <= a.level.rank for c in cards)


def test_orange_and_red_cards_say_who_to_tell(engine, ctx):
    for score in (60, 90):
        for card in engine.recommend(assessment(score, ("spo2", 20), ("skin_temp", 10)), ctx):
            if card.level.rank >= AlertLevel.ORANGE.rank:
                assert card.escalate_to is not EscalationTarget.SELF


def test_max_cards_option(ctx):
    engine = ProtocolActionEngine(cards_path=str(LIBRARY), max_cards=1)
    assert len(engine.recommend(assessment(60, ("symptom_rash_tingling", 20)), ctx)) == 1
    with pytest.raises(ValueError):
        ProtocolActionEngine(max_cards=0)


def test_built_in_cards_work_without_a_library(ctx):
    cards = create("actions", "protocol").recommend(assessment(90), ctx)
    assert cards and cards[0].level is AlertLevel.RED


# ---- the demo story -------------------------------------------------------------------


def test_demo_days_get_fitting_cards(loaded_pipeline):
    day_89 = loaded_pipeline.assess("AST-01", DAY_89, save=False)
    assert [c.card_id for c in day_89.actions] == ["saliva-test", "rest-watch"]

    day_90 = loaded_pipeline.assess("AST-01", DAY_90, save=False)
    ids = [c.card_id for c in day_90.actions]
    assert ids == ["reduce-load", "protect-rash", "tell-cmo"]
    assert "saliva_vzv_dna" in day_90.actions[0].triggers  # the VZV-specific card comes first
    assert all(c.escalate_to is EscalationTarget.CREW_MEDICAL_OFFICER for c in day_90.actions)
