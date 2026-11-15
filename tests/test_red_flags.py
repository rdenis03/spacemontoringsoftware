"""M15 red-flag rules and how procedures are merged (task B23, step 5)."""

import json

import pytest
from conftest import ROOT

from orbit.modules.actions import ProtocolActionEngine
from orbit.modules.reasoner import RulesReasoner
from orbit.schema import ActionCard, AlertLevel, TriageQuestion
from orbit.triage.library import TriageLibrary, merge_procedures
from orbit.triage.red_flags import RedFlagRule, RedFlagRules

CARDS = ROOT / "cards"
SENTENCES = ROOT / "tests" / "fixtures" / "triage" / "red_flag_sentences.jsonl"


def _lines():
    records = [json.loads(line) for line in SENTENCES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in records if "text" in r]


POSITIVE = [r for r in _lines() if r["fires"]]
NEGATIVE = [r for r in _lines() if not r["fires"]]


@pytest.fixture(scope="module")
def rules():
    return RedFlagRules.load(str(CARDS / "red_flags.jsonl"))


def test_test_set_has_both_kinds():
    assert len(POSITIVE) >= 30 and len(NEGATIVE) >= 10
    assert {r["rule"] for r in POSITIVE} == {"breathing", "chest", "faint", "confused", "eye", "headache",
                                             "swallow", "bleeding"}


def test_recall_is_100_percent(rules):
    missed = [r["text"] for r in POSITIVE if r["rule"] not in [h.rule_id for h in rules.check_text(r["text"])]]
    assert missed == [], f"red flags missed: {missed}"


def test_negated_lines_do_not_fire(rules):
    fired = {r["text"]: [h.rule_id for h in rules.check_text(r["text"])] for r in NEGATIVE}
    assert {text: ids for text, ids in fired.items() if ids} == {}


def test_when_in_doubt_it_fires(rules):
    assert [h.rule_id for h in rules.check_text("no fever, but chest pain")] == ["chest"]
    assert [h.rule_id for h in rules.check_text("no cough or chest pain")] == ["chest"]
    assert rules.check_text("no chest pain, but chest pain now")  # one plain mention is enough
    hit = rules.check_text("I can’t breathe")[0]  # typographic apostrophe
    assert hit.rule_id == "breathing" and hit.evidence == "can't breathe"


@pytest.mark.parametrize("text, rule", [
    ("No I can't breathe", "breathing"),
    ("No—I can't breathe", "breathing"),
    ("No, I can't breathe", "breathing"),
    ("no - I can't breathe", "breathing"),
    ("not only chest pain", "chest"),
    ("not sure but chest pain", "chest"),
    ("I don't think it's serious but I can't breathe", "breathing"),
    ("I don't know if it matters, I cannot breathe well", "breathing"),
    ("Not–chest pain, I mean yes chest pain", "chest"),
])
def test_cue_denies_only_directly_before_and_never_a_negative_phrase(rules, text, rule):
    assert rule in [h.rule_id for h in rules.check_text(text)], text


@pytest.mark.parametrize("text", ["no chest pain", "without chest pain", "I have no chest pain",
                                  "not short of breath", "I don't have any trouble breathing"])
def test_direct_denial_does_not_fire(rules, text):
    assert rules.check_text(text) == [], text


def test_several_rules_in_one_message_follow_file_order(rules):
    hits = rules.check_text("I fainted and now I have chest pain and can't breathe")
    assert [h.rule_id for h in hits] == ["breathing", "chest", "faint"]


def test_answers_fire_rules(rules):
    bank = {q.question_id: q for q in RulesReasoner(questions_path=str(CARDS / "questions.jsonl")).questions}
    assert [h.rule_id for h in rules.check_answer(bank["screen-breathing"], True)] == ["breathing"]
    assert [h.rule_id for h in rules.check_answer(bank["screen-eye"], "yes")] == ["eye"]
    assert rules.check_answer(bank["screen-breathing"], False) == []
    assert rules.check_answer(bank["screen-breathing"], None) == []  # skipped
    assert rules.check_answer(bank["one-side"], True) == []


def test_every_bank_red_flag_answer_has_a_rule_and_card(rules):
    rules.check_bank(RulesReasoner(questions_path=str(CARDS / "questions.jsonl")).questions)
    day_cards = ProtocolActionEngine(cards_path=str(CARDS / "action_cards.jsonl")).cards
    library = TriageLibrary.load(str(CARDS / "patterns.jsonl"), str(CARDS / "triage_cards.jsonl"), day_cards)
    rules.check_cards(library.has_card)
    assert all(library.card(r.card_id).level is AlertLevel.RED for r in rules.rules)


def test_built_in_rules_fit_the_built_in_bank_and_cards():
    built_in = RedFlagRules.load()
    built_in.check_bank(RulesReasoner().questions)
    built_in.check_cards(TriageLibrary.load().has_card)
    assert built_in.check_text("I can't breathe")[0].rule_id == "breathing"


def test_rules_are_checked():
    lonely = TriageQuestion(question_id="screen-x", text="Any x?", answer_type="yes_no", feature="x",
                            signal="symptom_headache", screening=True, red_flag_answers=("yes",))
    with pytest.raises(ValueError, match="screen-x=yes"):
        RedFlagRules.load().check_bank([lonely])
    with pytest.raises(ValueError, match="unknown cards"):
        RedFlagRules.load().check_cards(lambda card_id: False)
    with pytest.raises(ValueError, match="start with 'rf-'"):
        RedFlagRule(rule_id="x", label="X", phrases=("x",), card_id="tell-cmo")
    with pytest.raises(ValueError, match="needs phrases"):
        RedFlagRule(rule_id="x", label="X", card_id="rf-x")
    rule = {"label": "X", "phrases": ("chest pain",), "card_id": "rf-x"}
    with pytest.raises(ValueError, match="in both"):
        RedFlagRules([RedFlagRule(rule_id="a", **rule), RedFlagRule(rule_id="b", **rule)])


# ---- merge_procedures ------------------------------------------------------------------


def card(card_id: str, level: str = "yellow") -> ActionCard:
    escalate = "crew_medical_officer" if level in ("orange", "red") else "self"
    return ActionCard(card_id=card_id, level=level, title=card_id, steps=("Do it",), rationale="r",
                      escalate_to=escalate)


def ids(cards):
    return [c.card_id for c in cards]


def test_worked_example_order():
    merged = merge_procedures([], [card("saliva-test"), card("watch-patch")],
                              [card("saliva-test"), card("rest-watch")], "yellow")
    assert ids(merged) == ["saliva-test", "watch-patch", "rest-watch"]


def test_red_flag_cards_come_first_whatever_the_level():
    merged = merge_procedures([card("rf-chest", "red")], [card("watch-patch")], [card("keep-routine", "green")],
                              AlertLevel.GREEN)
    assert ids(merged) == ["rf-chest", "keep-routine"], "red-flag card above level stays; yellow card goes"


def test_no_card_above_the_level_except_red_flags():
    merged = merge_procedures([], [card("tell-cmo", "orange"), card("watch-patch")], [card("rest-watch")],
                              "yellow")
    assert ids(merged) == ["watch-patch", "rest-watch"]


def test_duplicates_dropped_and_at_most_four():
    merged = merge_procedures([card("rf-a", "red"), card("rf-a", "red")],
                              [card("p1"), card("p2"), card("d1")],
                              [card("d1"), card("d2"), card("d3")], "red")
    assert ids(merged) == ["rf-a", "p1", "p2", "d1"]
    assert len(merge_procedures([], [], [card(f"d{i}") for i in range(6)], "yellow", max_cards=2)) == 2
