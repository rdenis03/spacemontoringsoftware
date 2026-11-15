"""M15 triage schema and the ``triage_sessions`` table (task B23, step 2)."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from orbit.core import Store
from orbit.schema import (
    OPEN_STATUSES,
    SCHEMA_VERSION,
    ActionCard,
    Contributor,
    PatternScore,
    SymptomFinding,
    SymptomReport,
    TriageAnswer,
    TriagePattern,
    TriageQuestion,
    TriageResult,
    TriageSession,
    TriageStatus,
    get_spec,
)

UTC = timezone.utc
T0 = datetime(2027, 4, 2, 10, 30, tzinfo=UTC)
P = TriagePattern


def rash_question(**extra) -> TriageQuestion:
    return TriageQuestion(question_id="rash-tingling", text="How strong is the burning or tingling?",
                          answer_type="scale_0_3", signal="symptom_rash_tingling", **extra)


def one_side(**extra) -> TriageQuestion:
    return TriageQuestion(question_id="one-side", text="Is it on one side of your body only?",
                          answer_type="yes_no", feature="one_side", signal="symptom_rash_tingling",
                          **extra)


def test_schema_version_is_a_minor_bump():
    assert SCHEMA_VERSION == "1.1.0"


def test_patterns_and_statuses():
    assert [p.value for p in TriagePattern] == [
        "vzv_like", "hsv1_like", "ebv_like", "respiratory", "exertion", "sleep_loss", "stress", "other"]
    assert OPEN_STATUSES == {TriageStatus.ASKING, TriageStatus.READY, TriageStatus.ESCALATED}


def test_report_text_is_1_to_1000_characters_with_a_timezone():
    assert SymptomReport(astronaut_id="AST-01", reported_at=T0, text="x" * 1000).channel == "text"
    for bad in ("", "x" * 1001):
        with pytest.raises(ValidationError):
            SymptomReport(astronaut_id="AST-01", reported_at=T0, text=bad)
    with pytest.raises(ValidationError, match="timezone"):
        SymptomReport(astronaut_id="AST-01", reported_at=datetime(2027, 4, 2), text="tired")
    with pytest.raises(ValidationError):
        SymptomReport(astronaut_id="AST-01", reported_at=T0, text="tired", channel="email")


def test_finding_signal_must_be_a_symptom():
    assert SymptomFinding(signal="symptom_fatigue", label="Fatigue", severity=2).severity == 2
    assert SymptomFinding(label="Nausea").signal is None  # a complaint outside the 8 signals
    for bad in ({"signal": "skin_temp"}, {"severity": 4}, {"side": "up"}, {"confidence": 1.5}):
        with pytest.raises(ValidationError):
            SymptomFinding(**{"signal": "symptom_fatigue", "label": "Fatigue", **bad})


def test_symptom_question_takes_scale_words_from_the_registry():
    question = rash_question()
    assert question.choices == get_spec("symptom_rash_tingling").scale_labels
    assert question.is_symptom_question
    assert question.answer_keys == ("0", "1", "2", "3")
    assert one_side().choices == ("yes", "no") and not one_side().is_symptom_question


def test_normalize_and_answer_keys():
    scale = rash_question()
    assert [scale.normalize(v) for v in ("Moderate", 2, "none", "3", 1.0)] == [2, 2, 0, 3, 1]
    assert scale.answer_key("severe") == "3" and scale.answer_word(2) == "moderate"
    assert scale.normalize(None) is None and scale.answer_key(None) is None
    for bad in ("very", 4, True, 1.5):
        with pytest.raises(ValueError, match="not an answer"):
            scale.normalize(bad)

    yes_no = one_side()
    assert yes_no.normalize("Yes") is True and yes_no.normalize(False) is False
    assert yes_no.answer_key(True) == "yes" and yes_no.answer_word(False) == "no"
    with pytest.raises(ValueError):
        yes_no.normalize("maybe")

    reading = TriageQuestion(question_id="temp", text="Your temperature?", answer_type="reading",
                             feature="temperature", category="vital")
    assert reading.normalize("37.5") == 37.5 and reading.answer_key(37.5) is None
    choice = TriageQuestion(question_id="side", text="Which side?", answer_type="choice",
                            choices=("left", "right"), feature="which_side")
    assert choice.normalize("LEFT") == "left" and choice.answer_key("right") == "right"


def test_likelihoods_default_to_uninformative_and_are_checked():
    question = one_side(likelihoods={"vzv_like": {"yes": 0.9, "no": 0.1}})
    assert question.likelihood(P.VZV_LIKE, "yes") == 0.9
    assert question.likelihood(P.EXERTION, "yes") == 0.5
    assert rash_question().likelihood(P.OTHER, "2") == 0.25
    for bad in ({"vzv_like": {"yes": 0.9}}, {"vzv_like": {"yes": 0.9, "no": 0.3}},
                {"vzv_like": {"yes": 1.2, "no": -0.2}}):
        with pytest.raises(ValidationError, match="likelihoods"):
            one_side(likelihoods=bad)
    with pytest.raises(ValidationError, match="red_flag_answers"):
        one_side(red_flag_answers=("maybe",))


@pytest.mark.parametrize("fields, problem", [
    ({"answer_type": "yes_no"}, "needs a signal, a feature"),
    ({"answer_type": "scale_0_3", "signal": "skin_temp"}, "not a symptom signal"),
    ({"answer_type": "yes_no", "signal": "symptom_fatigue"}, "must be scale_0_3"),
    ({"answer_type": "yes_no", "feature": "breathing", "screening": True}, "screening question needs"),
    ({"answer_type": "choice", "feature": "x"}, "unique choices"),
])
def test_bad_questions_are_rejected(fields, problem):
    with pytest.raises(ValidationError, match=problem):
        TriageQuestion(question_id="q", text="Question?", **fields)
    with pytest.raises(ValidationError):
        TriageQuestion(question_id="q", text="x" * 121, answer_type="yes_no", feature="f")


def _result(*probabilities: float, **extra) -> TriageResult:
    ranking = tuple(PatternScore(pattern=p, probability=x) for p, x in zip(TriagePattern, probabilities))
    return TriageResult(session_id="s1", astronaut_id="AST-01", as_of=T0, status="ready",
                        ranking=ranking, **extra)


def test_result_ranking_must_sum_to_one():
    assert _result(0.5, 0.5).status is TriageStatus.READY
    assert _result().ranking == ()  # empty ranking is allowed
    with pytest.raises(ValidationError, match="sum to"):
        _result(0.5, 0.4)
    with pytest.raises(ValidationError):
        _result(1.0, model_version="x" * 65)
    with pytest.raises(ValidationError):
        PatternScore(pattern="vzv_like", probability=1.0,
                     reasons=[Contributor(label=f"r{i}", points=1) for i in range(4)])


def _session(session_id: str, started: datetime, **extra) -> TriageSession:
    question = one_side(likelihoods={"vzv_like": {"yes": 0.9, "no": 0.1}})
    result = TriageResult(
        session_id=session_id, astronaut_id="AST-01", as_of=T0, status="asking",
        findings=(SymptomFinding(signal="symptom_rash_tingling", label="Rash or tingling",
                                 evidence=("tingly patch",), body_site="ribs", onset_hours=12),),
        ranking=(PatternScore(pattern="vzv_like", label="Signs that fit shingles (VZV)",
                              probability=0.7,
                              reasons=(Contributor(label="Rash or tingling", points=2.1,
                                                   signal="symptom_rash_tingling"),)),
                 PatternScore(pattern="other", probability=0.3)),
        next_question=question,
        procedures=(ActionCard(card_id="watch-patch", level="yellow", title="Watch the patch",
                               steps=("Photograph it",), rationale="r"),),
    )
    return TriageSession(
        session_id=session_id, astronaut_id="AST-01", started_at=started, updated_at=started,
        as_of=T0, reports=(SymptomReport(astronaut_id="AST-01", reported_at=T0, text="tingly patch"),),
        answers=(TriageAnswer(question_id="rash-tingling", value=2, answered_at=started),
                 TriageAnswer(question_id="one-side", value=True, answered_at=started),
                 TriageAnswer(question_id="fever-chills", value=None, answered_at=started)),
        result=result, **extra)


def test_session_round_trips_as_json():
    session = _session("s1", T0)
    again = TriageSession.model_validate_json(session.model_dump_json())
    assert again == session
    assert [a.value for a in again.answers] == [2, True, None]
    assert again.answers[1].value is True  # stays a bool, not 1
    assert again.is_open and not again.done


def test_store_saves_lists_and_replaces_sessions():
    store = Store(":memory:")
    first, second = _session("s1", T0), _session("s2", T0 + timedelta(hours=1))
    store.save_session(first)
    store.save_session(second)
    assert store.session("s1") == first
    assert store.session("nope") is None
    assert [s.session_id for s in store.sessions("AST-01")] == ["s2", "s1"]  # newest first
    assert [s.session_id for s in store.sessions("AST-01", start=T0 + timedelta(minutes=30))] == ["s2"]
    assert [s.session_id for s in store.sessions("AST-01", end=T0)] == ["s1"]
    assert store.sessions("AST-02") == []

    store.save_session(first.model_copy(update={"status": TriageStatus.CANCELLED}))
    assert store.session("s1").status is TriageStatus.CANCELLED
    assert store.counts()["triage_sessions"] == 2


def test_old_database_opens_and_gains_the_table(tmp_path):
    path = tmp_path / "old.db"
    Store(path).close()
    db = sqlite3.connect(path)  # make it look like a 1.0.0 database from before B23
    db.execute("DROP TABLE triage_sessions")
    db.execute("UPDATE meta SET value='1.0.0' WHERE key='schema_version'")
    db.commit()
    db.close()

    store = Store(path)  # minor version difference: opens
    assert store.counts()["triage_sessions"] == 0
    store.save_session(_session("s1", T0))
    assert store.session("s1").session_id == "s1"
