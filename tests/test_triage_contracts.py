"""Contract tests for the M15 slots: every registered extractor and reasoner must pass.

Like ``tests/test_contracts.py``: a new ``@register("extractor", ...)`` or
``@register("reasoner", ...)`` module is picked up here automatically, and
must work with its default options (its small built-in library).
"""

import pytest
from conftest import DAY_89

from orbit.core import TriageEvidence, available, create
from orbit.schema import (
    Contributor,
    PatternScore,
    SignalType,
    SymptomFinding,
    SymptomReport,
    TriagePattern,
    TriageQuestion,
)

S = SignalType
TEXTS = (
    "Fever since yesterday, no sore throat",
    "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too.",
    "A bit of a headache and really bad muscle aches after the EVA, but no fever or chills.",
)


@pytest.fixture
def ctx(loaded_pipeline):
    return loaded_pipeline.context("AST-01", DAY_89)


def report(text: str) -> SymptomReport:
    return SymptomReport(astronaut_id="AST-01", reported_at=DAY_89, text=text)


def finding(signal: SignalType, severity: int | None = None) -> SymptomFinding:
    return SymptomFinding(signal=signal, label=signal.value, severity=severity)


# ---- extractor ------------------------------------------------------------------


@pytest.mark.parametrize("name", available("extractor"))
def test_extractor_finds_symptoms_and_negation(name, ctx):
    extractor = create("extractor", name)
    findings = extractor.extract(report(TEXTS[0]), ctx)
    assert all(isinstance(f, SymptomFinding) for f in findings)
    by_signal = {f.signal: f for f in findings if f.signal is not None}
    assert by_signal[S.SYMPTOM_FEVER_CHILLS].negated is False
    assert by_signal[S.SYMPTOM_SORE_THROAT].negated is True


@pytest.mark.parametrize("name", available("extractor"))
def test_extractor_empty_text_gives_nothing(name, ctx):
    empty = report("x").model_copy(update={"text": ""})  # the model refuses "", the slot must cope
    assert create("extractor", name).extract(empty, ctx) == []


@pytest.mark.parametrize("name", available("extractor"))
@pytest.mark.parametrize("text", TEXTS)
def test_extractor_is_deterministic_and_quotes_the_text(name, text, ctx):
    extractor = create("extractor", name)
    findings = extractor.extract(report(text), ctx)
    assert findings == create("extractor", name).extract(report(text), ctx)
    for f in findings:
        assert all(words.lower() in text.lower() for words in f.evidence), f


# ---- reasoner ---------------------------------------------------------------------


EVIDENCE = (
    TriageEvidence(),
    TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING, 2),)),
    TriageEvidence(findings=(SymptomFinding(label="Nausea"), finding(S.SYMPTOM_FATIGUE, 1))),
)


@pytest.mark.parametrize("name", available("reasoner"))
@pytest.mark.parametrize("evidence", EVIDENCE)
def test_reasoner_rank_contract(name, evidence, ctx):
    reasoner = create("reasoner", name)
    ranking = reasoner.rank(evidence, ctx)
    assert all(isinstance(score, PatternScore) for score in ranking)
    assert sorted(s.pattern for s in ranking) == sorted(TriagePattern), "every pattern once"
    assert sum(s.probability for s in ranking) == pytest.approx(1.0, abs=1e-6)
    probabilities = [s.probability for s in ranking]
    assert probabilities == sorted(probabilities, reverse=True)
    assert all(isinstance(r, Contributor) for s in ranking for r in s.reasons)
    assert reasoner.rank(evidence, ctx) == ranking, "must be deterministic"


@pytest.mark.parametrize("name", available("reasoner"))
def test_reasoner_rash_points_to_vzv(name, ctx):
    ranking = create("reasoner", name).rank(EVIDENCE[1], ctx)
    probability = {s.pattern: s.probability for s in ranking}
    assert probability[TriagePattern.VZV_LIKE] > probability[TriagePattern.EXERTION]


@pytest.mark.parametrize("name", available("reasoner"))
def test_reasoner_never_asks_twice(name, ctx):
    reasoner = create("reasoner", name)
    assert reasoner.questions and all(isinstance(q, TriageQuestion) for q in reasoner.questions)
    assert reasoner.max_questions >= 1
    findings = (finding(S.SYMPTOM_RASH_TINGLING), finding(S.SYMPTOM_FATIGUE),
                finding(S.SYMPTOM_FEVER_CHILLS))
    asked: list[str] = []
    for _ in range(len(reasoner.questions) + 1):
        evidence = TriageEvidence(findings=findings, asked=tuple(asked))
        ranking = reasoner.rank(evidence, ctx)
        question = reasoner.next_question(evidence, ranking, ctx)
        assert question == reasoner.next_question(evidence, ranking, ctx), "must be deterministic"
        if question is None:
            break
        assert question.question_id not in asked
        asked.append(question.question_id)
    assert len(asked) <= reasoner.max_questions


@pytest.mark.parametrize("name", available("reasoner"))
def test_reasoner_stops_after_max_questions(name, ctx):
    reasoner = create("reasoner", name)
    asked = tuple(q.question_id for q in reasoner.questions[: reasoner.max_questions])
    evidence = TriageEvidence(findings=(finding(S.SYMPTOM_RASH_TINGLING),), asked=asked)
    assert reasoner.next_question(evidence, reasoner.rank(evidence, ctx), ctx) is None
