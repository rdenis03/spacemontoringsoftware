"""M15 reasoner ``rules``, the question bank and the triage library (task B23, step 4)."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from conftest import DAY_90, ROOT

from orbit.core import TriageEvidence
from orbit.modules.actions import ProtocolActionEngine
from orbit.modules.extractor import LexiconExtractor
from orbit.modules.reasoner import RulesReasoner
from orbit.schema import (
    ActionCard,
    SignalType,
    SymptomFinding,
    TriageAnswer,
    TriagePattern,
    parse_jsonl,
)
from orbit.triage.library import (
    BUILT_IN_PATTERNS,
    PatternInfo,
    TriageLibrary,
    TriageLibraryError,
    check_cards,
)

S, P = SignalType, TriagePattern
CARDS = ROOT / "cards"
AT_1030 = datetime(2027, 4, 2, 10, 30, tzinfo=timezone.utc)  # day 89
WORKED_EXAMPLE = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."


@pytest.fixture(scope="module")
def reasoner():
    return RulesReasoner(questions_path=str(CARDS / "questions.jsonl"))


@pytest.fixture
def day89(loaded_pipeline):
    """Context and preview at 10:30 on day 89, the worked example's moment."""
    preview = loaded_pipeline.assess("AST-01", AT_1030, save=False)
    return loaded_pipeline.context("AST-01", AT_1030), preview


def finding(signal, severity=None, **extra):
    return SymptomFinding(signal=signal, label=signal.value, severity=severity, **extra)


def ask(reasoner, ctx, evidence):
    return reasoner.next_question(evidence, reasoner.rank(evidence, ctx), ctx)


def probabilities(reasoner, ctx, evidence):
    return {s.pattern: s.probability for s in reasoner.rank(evidence, ctx)}


def test_worked_example_asks_severity_then_one_side_then_fever(reasoner, day89):
    ctx, preview = day89
    findings = LexiconExtractor(str(CARDS / "symptom_lexicon.jsonl")).read(WORKED_EXAMPLE)
    base = TriageEvidence(findings=tuple(findings), preview=preview.assessment, anomalies=preview.anomalies)
    first = ask(reasoner, ctx, base)
    assert first.question_id == "rash-tingling" and first.signal is S.SYMPTOM_RASH_TINGLING

    rated = (findings[0].model_copy(update={"severity": 2}), findings[1])
    after_1 = replace(base, findings=rated, asked=("rash-tingling",),
                      answers=(TriageAnswer(question_id="rash-tingling", value=2, answered_at=AT_1030),))
    second = ask(reasoner, ctx, after_1)
    assert second.text == "Is it on one side of your body only?"

    after_2 = replace(after_1, asked=after_1.asked + ("one-side",), answers=after_1.answers + (
        TriageAnswer(question_id="one-side", value=True, answered_at=AT_1030),))
    ranking = reasoner.rank(after_2, ctx)
    assert ranking[0].pattern is P.VZV_LIKE and ranking[0].probability < 0.8
    third = reasoner.next_question(after_2, ranking, ctx)
    assert third.text == "Any fever or chills?"

    after_3 = replace(after_2, findings=rated + (finding(S.SYMPTOM_FEVER_CHILLS, 0, negated=True),),
                      asked=after_2.asked + ("fever-chills",))
    ranking = reasoner.rank(after_3, ctx)
    assert ranking[0].pattern is P.VZV_LIKE and ranking[0].probability >= 0.8
    assert reasoner.next_question(after_3, ranking, ctx) is None  # ready
    reasons = ranking[0].reasons
    assert reasons[0].label == "Rash or tingling: moderate" and reasons[0].signal is S.SYMPTOM_RASH_TINGLING
    assert any(r.signal is S.SYMPTOM_RASH_TINGLING and "one side" in r.label for r in reasons)


def test_spacewalk_question_is_skipped_on_day_89(reasoner, day89):
    ctx, preview = day89
    assert any(e.event_type.value == "eva" for e in ctx.events)
    evidence = TriageEvidence(findings=(finding(S.SYMPTOM_MUSCLE_ACHES, 2), finding(S.SYMPTOM_FATIGUE, 1)),
                              preview=preview.assessment, anomalies=preview.anomalies)

    def all_questions(context):
        asked = []
        while (q := ask(reasoner, context, replace(evidence, asked=tuple(asked)))) is not None:
            asked.append(q.question_id)
        return asked

    assert "recent-exertion" not in all_questions(ctx)
    assert "recent-exertion" in all_questions(replace(ctx, events=()))  # ORBIT does not know of an EVA


def test_exertion_leads_after_a_spacewalk(reasoner, day89):
    ctx, preview = day89
    evidence = TriageEvidence(findings=(finding(S.SYMPTOM_MUSCLE_ACHES, 2), finding(S.SYMPTOM_FATIGUE, 1)),
                              preview=preview.assessment, anomalies=preview.anomalies)
    ranking = reasoner.rank(evidence, ctx)
    assert ranking[0].pattern is P.EXERTION
    eva_reason = next(r for r in ranking[0].reasons if r.event_id)
    assert eva_reason.event_id == "eva-20270401" and "Spacewalk" in eva_reason.label
    without_eva = probabilities(reasoner, replace(ctx, events=()), evidence)
    assert without_eva[P.EXERTION] < ranking[0].probability


def test_stop_rules(reasoner, day89):
    ctx, _ = day89
    rash = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING),))
    assert ask(reasoner, ctx, rash) is not None
    sure = RulesReasoner(questions_path=str(CARDS / "questions.jsonl"), stop_probability=0.2)
    assert ask(sure, ctx, rash) is None, "top pattern above stop_probability"
    two = RulesReasoner(questions_path=str(CARDS / "questions.jsonl"), max_questions=2)
    assert ask(two, ctx, replace(rash, asked=("a", "b"))) is None, "max_questions reached"


def test_no_question_left(tmp_path, day89):
    ctx, _ = day89
    bank = tmp_path / "one.jsonl"
    bank.write_text('{"question_id":"fatigue","text":"How tired?","answer_type":"scale_0_3",'
                    '"signal":"symptom_fatigue"}\n', encoding="utf-8")
    small = RulesReasoner(questions_path=str(bank))
    tired = TriageEvidence(findings=(finding(S.SYMPTOM_FATIGUE),))
    assert ask(small, ctx, tired).question_id == "fatigue"
    assert ask(small, ctx, replace(tired, asked=("fatigue",))) is None


def test_screening_comes_first_and_skips_what_is_known(reasoner, day89):
    ctx, _ = day89
    fever = TriageEvidence(findings=(finding(S.SYMPTOM_FEVER_CHILLS),))
    assert ask(reasoner, ctx, fever).question_id == "screen-breathing"
    face = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING, body_site="face"),))
    assert ask(reasoner, ctx, face).question_id == "screen-eye"
    unknown_site = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING),))
    assert ask(reasoner, ctx, unknown_site).question_id == "screen-eye"
    ribs = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING, 2, body_site="ribs"),))
    assert ask(reasoner, ctx, ribs).question_id == "one-side"
    known_side = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING, 2, body_site="ribs", side="left"),))
    assert ask(reasoner, ctx, known_side).question_id != "one-side"


def test_a_denied_symptom_weighs_against_its_patterns(reasoner, day89):
    ctx, _ = day89
    throat = TriageEvidence(findings=(finding(S.SYMPTOM_SORE_THROAT, 2),))
    no_fever = replace(throat, findings=throat.findings + (finding(S.SYMPTOM_FEVER_CHILLS, 0, negated=True),))
    assert probabilities(reasoner, ctx, no_fever)[P.RESPIRATORY] < \
        probabilities(reasoner, ctx, throat)[P.RESPIRATORY]


def test_other_complaints_point_to_other(reasoner, day89):
    ctx, _ = day89
    ranking = reasoner.rank(TriageEvidence(findings=(SymptomFinding(label="Nausea"),
                                                     SymptomFinding(label="Dizziness"))), ctx)
    assert ranking[0].pattern is P.OTHER
    assert [r.label for r in ranking[0].reasons] == ["Nausea", "Dizziness"]
    quiet = replace(ctx, events=())  # day 89 has the EVA, which points to exertion
    assert reasoner.rank(TriageEvidence(), quiet)[0].pattern is P.OTHER, "nothing known: other leads"


def test_viral_dna_from_the_preview_counts(reasoner, loaded_pipeline):
    preview = loaded_pipeline.assess("AST-01", DAY_90, save=False)
    ctx = loaded_pipeline.context("AST-01", DAY_90)
    assert any(c.signal is S.SALIVA_VZV_DNA for c in preview.assessment.contributors)
    with_lab = TriageEvidence(preview=preview.assessment, anomalies=preview.anomalies)
    ranking = reasoner.rank(with_lab, ctx)
    vzv = next(s for s in ranking if s.pattern is P.VZV_LIKE)
    assert any(r.signal is S.SALIVA_VZV_DNA for r in vzv.reasons)
    assert vzv.probability > probabilities(reasoner, ctx, TriageEvidence())[P.VZV_LIKE]


def test_feature_answers_use_the_bank_likelihoods(reasoner, day89):
    ctx, _ = day89
    rash = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING, 1),))
    yes = replace(rash, answers=(TriageAnswer(question_id="one-side", value=True, answered_at=AT_1030),))
    no = replace(rash, answers=(TriageAnswer(question_id="one-side", value=False, answered_at=AT_1030),))
    skipped = replace(rash, answers=(TriageAnswer(question_id="one-side", value=None, answered_at=AT_1030),))
    assert probabilities(reasoner, ctx, yes)[P.VZV_LIKE] > probabilities(reasoner, ctx, rash)[P.VZV_LIKE] \
        > probabilities(reasoner, ctx, no)[P.VZV_LIKE]
    assert probabilities(reasoner, ctx, skipped) == probabilities(reasoner, ctx, rash)


def test_question_bank(reasoner):
    ids = [q.question_id for q in reasoner.questions]
    assert ids[:5] == ["screen-breathing", "screen-swallow", "screen-eye", "screen-headache", "one-side"]
    symptom_questions = {q.signal for q in reasoner.questions if q.is_symptom_question}
    assert symptom_questions == {s for s in SignalType if s.value.startswith("symptom_")}
    assert {q.feature for q in reasoner.questions} >= {"one_side", "recent_exertion", "short_sleep",
                                                       "high_stress", "breathing_trouble"}
    for q in reasoner.questions:
        assert len(q.text) <= 120
        if q.screening:
            assert q.red_flag_answers == ("yes",)
        if q.answer_type != "reading":
            assert set(q.likelihoods) == set(TriagePattern), f"{q.question_id} lists every pattern"
    with pytest.raises(ValueError, match="max_questions"):
        RulesReasoner(max_questions=0)
    with pytest.raises(ValueError, match="stop_probability"):
        RulesReasoner(stop_probability=0)


# ---- the triage library ----------------------------------------------------------------


@pytest.fixture(scope="module")
def day_cards():
    return ProtocolActionEngine(cards_path=str(CARDS / "action_cards.jsonl")).cards


def test_shipped_library_loads(day_cards):
    library = TriageLibrary.load(str(CARDS / "patterns.jsonl"), str(CARDS / "triage_cards.jsonl"), day_cards)
    assert set(library.patterns) == set(TriagePattern)
    assert library.label(P.VZV_LIKE) == "Signs that fit shingles (VZV)"
    assert [c.card_id for c in library.pattern_cards(P.VZV_LIKE)] == ["saliva-test", "watch-patch"]
    assert [c.card_id for c in library.pattern_cards(P.SLEEP_LOSS)] == ["recover-sleep"]
    assert [c.card_id for c in library.pattern_cards(P.STRESS)] == ["ease-stress"]
    other = library.pattern_cards(P.OTHER)[0]
    assert other.card_id == "describe-to-cmo" and other.escalate_to.value == "crew_medical_officer"
    assert library.card("watch-patch").level.value == "yellow"
    assert all(c.card_id.startswith("rf-") for c in library.cards if c.level.value == "red")


def test_triage_cards_are_not_in_the_daily_library(day_cards):
    triage_ids = {c.card_id for c in parse_jsonl(CARDS / "triage_cards.jsonl", ActionCard).raise_if_errors()}
    assert not triage_ids & {c.card_id for c in day_cards}


def test_built_in_library_needs_no_files():
    library = TriageLibrary.load()
    assert set(library.patterns) == set(TriagePattern)
    assert library.pattern_cards(P.VZV_LIKE)[0].card_id == "watch-patch"


def _card(card_id="c", **extra):
    fields = {"card_id": card_id, "level": "yellow", "title": "t", "steps": ("Do it",), "rationale": "r"}
    return ActionCard(**{**fields, **extra})


@pytest.mark.parametrize("cards, problem", [
    ([_card("a"), _card("a")], "duplicate card ids"),
    ([_card(steps=("Take 200 mg of something",))], "doses"),
    ([_card(steps=("Take 5mg",))], "doses"),
    ([_card(triggers=("saliva_vzv_dna", "symptom_rash_tingling"))], "mix categories"),
    ([_card(level="red")], "must set escalate_to"),
    ([_card(steps=("x" * 200,))], "under 200"),
    ([_card("saliva-test")], "already in the action card library"),
])
def test_check_rejects_broken_cards(cards, problem, day_cards):
    with pytest.raises(TriageLibraryError, match=problem):
        check_cards(cards, day_cards)


def test_patterns_are_checked(day_cards):
    patterns = [PatternInfo.model_validate(p) for p in BUILT_IN_PATTERNS]
    cards = TriageLibrary.load().cards
    with pytest.raises(TriageLibraryError, match="no entry for other"):
        TriageLibrary(patterns[:-1], cards)
    unknown = patterns[:-1] + [PatternInfo(pattern="other", label="Other", card_ids=("nope",))]
    with pytest.raises(TriageLibraryError, match="unknown card 'nope'"):
        TriageLibrary(unknown, cards)
    with pytest.raises(TriageLibraryError, match="listed twice"):
        TriageLibrary(patterns + patterns[:1], cards)
