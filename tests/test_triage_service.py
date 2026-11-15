"""M15 triage service, its [triage] config and the worked example end to end (task B23, step 6)."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import DAY_89, DAY_90, ROOT

from orbit.core import ConfigError, Pipeline, Store, create, load_settings
from orbit.schema import AlertLevel, SignalType, TriagePattern, TriageStatus
from orbit.triage.config import load_triage_settings
from orbit.triage.service import (
    BadAnswer,
    SessionClosed,
    SessionNotFound,
    TriageService,
    UnknownAstronaut,
)

UTC = timezone.utc
S = SignalType
AT_1030 = datetime(2027, 4, 2, 10, 30, tzinfo=UTC)  # day 89, mission time
WALL = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)  # real time, for session timeouts
WORKED_EXAMPLE = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return Clock(WALL)


@pytest.fixture
def service(settings, ran_pipeline, clock):
    return TriageService.from_settings(load_triage_settings(settings), ran_pipeline, clock=clock)


def ids(cards):
    return [c.card_id for c in cards]


def run_worked_example(service, when=AT_1030):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=when)
    results = [first]
    for reply in ("moderate", "yes", "none"):
        question = results[-1].next_question
        assert question is not None, results[-1]
        results.append(service.answer(first.session_id, question_id=question.question_id, value=reply))
    return results


# ---- the worked example ---------------------------------------------------------------


def test_worked_example_end_to_end(service, ran_pipeline):
    store = ran_pipeline.store
    before = {a.assessed_at: (a.level, a.score) for a in store.assessments("AST-01")}
    first, after_1, after_2, ready = run_worked_example(service)

    rash, fatigue = first.findings
    assert (rash.signal, rash.severity, rash.body_site, rash.onset_hours) == (S.SYMPTOM_RASH_TINGLING, None, "ribs", 12)
    assert (fatigue.signal, fatigue.severity) == (S.SYMPTOM_FATIGUE, 2)
    assert first.status is TriageStatus.ASKING and first.red_flags == () and first.procedures == ()
    assert [r.next_question.question_id for r in (first, after_1, after_2)] == \
        ["rash-tingling", "one-side", "fever-chills"]
    assert after_2.ranking[0].pattern is TriagePattern.VZV_LIKE and after_2.ranking[0].probability < 0.8
    assert after_2.ranking[0].label == "Signs that fit shingles (VZV)"

    assert ready.status is TriageStatus.READY and ready.next_question is None
    assert ready.ranking[0].pattern is TriagePattern.VZV_LIKE and ready.ranking[0].probability >= 0.8
    assert ids(ready.procedures) == ["saliva-test", "watch-patch", "rest-watch"]
    assert ready.model_version == "lexicon-0.1+rules-0.1" and ready.errors == ()

    # nothing saved before confirm
    assert store.observations("AST-01", start=AT_1030, end=AT_1030) == []
    assert store.assessments("AST-01", start=AT_1030, end=AT_1030) == []

    result, day = service.confirm(first.session_id)
    assert result.status is TriageStatus.CONFIRMED
    assert day.assessment.level is AlertLevel.YELLOW and day.assessment.score == 44.7
    assert ids(day.actions)[0] == "saliva-test"
    assert {"watch-patch", "rest-watch"} <= set(ids(day.actions))
    assert ids(store.recommendations(day.assessment.assessment_id)) == ids(day.actions), "saved with the run"
    assert ids(result.procedures) == ids(day.actions)

    saved = {o.observation_id: o for o in store.observations("AST-01", start=AT_1030, end=AT_1030)}
    assert {k: o.value for k, o in saved.items()} == {
        "AST-01-symptom_rash_tingling-20270402T103000": 2,
        "AST-01-symptom_fatigue-20270402T103000": 2,
        "AST-01-symptom_fever_chills-20270402T103000": 0,
    }
    assert all(o.note == f"triage {first.session_id}" and o.source.value == "checkin" for o in saved.values())

    after = {a.assessed_at: (a.level, a.score) for a in store.assessments("AST-01") if a.assessed_at != AT_1030}
    assert after == before, "the 10:00 runs do not change"
    assert before[DAY_89] == (AlertLevel.YELLOW, 27.7) and before[DAY_90] == (AlertLevel.ORANGE, 70.2)

    session = service.session(first.session_id)
    assert session.status is TriageStatus.CONFIRMED and session.confirmed_as_of == AT_1030
    assert [a.value for a in session.answers] == [2, True, 0]
    assert session.reports[0].text == WORKED_EXAMPLE  # the raw text stays in the session only


def test_same_chat_on_day_90_gives_red(service):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030 + timedelta(days=1))
    service.answer(first.session_id, done=True)
    _, day = service.confirm(first.session_id, corrections={"symptom_rash_tingling": 2,
                                                            "symptom_fever_chills": 0})
    assert day.assessment.level is AlertLevel.RED and day.assessment.score == 77.2


def test_turns_save_only_the_session(service, ran_pipeline):
    before = ran_pipeline.store.counts()
    run_worked_example(service)
    after = ran_pipeline.store.counts()
    assert after.pop("triage_sessions") == before.pop("triage_sessions") + 1
    assert after == before


def test_cancel_writes_nothing(service, ran_pipeline):
    before = ran_pipeline.store.counts()
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    cancelled = service.cancel(first.session_id)
    assert cancelled.status is TriageStatus.CANCELLED and cancelled.result.next_question is None
    after = ran_pipeline.store.counts()
    assert after.pop("triage_sessions") == 1
    before.pop("triage_sessions")
    assert after == before
    with pytest.raises(SessionClosed, match="cancelled"):
        service.answer(first.session_id, done=True)
    with pytest.raises(SessionClosed):
        service.confirm(first.session_id)
    with pytest.raises(SessionClosed):
        service.cancel(first.session_id)


# ---- red flags ---------------------------------------------------------------------------


def test_red_flag_text_escalates(service):
    result = service.start("AST-01", "Tingling near my eye and I feel confused", timestamp=AT_1030)
    assert result.status is TriageStatus.ESCALATED and result.next_question is None
    assert result.red_flags == ("confused", "eye")  # file order
    assert ids(result.procedures)[:2] == ["rf-confused", "rf-eye"]
    assert result.procedures[0].level is AlertLevel.RED  # above the yellow preview: red flags always come first

    calm = service.answer(result.session_id, text="It's calmer now, just a bit tired")
    assert calm.red_flags == ("confused", "eye"), "a red flag is never removed"
    assert calm.status is TriageStatus.ESCALATED

    _, day = service.confirm(result.session_id)
    assert ids(day.actions)[0] == "rf-confused"


def test_red_flag_answer_escalates(service):
    first = service.start("AST-01", "Fever since last night", timestamp=AT_1030)
    assert first.next_question.question_id == "screen-breathing"  # screening first
    escalated = service.answer(first.session_id, question_id="screen-breathing", value="yes")
    assert escalated.status is TriageStatus.ESCALATED and escalated.red_flags == ("breathing",)
    assert ids(escalated.procedures)[0] == "rf-breathing"
    with pytest.raises(BadAnswer, match="no question is open"):
        service.answer(first.session_id, question_id="fever-chills", value=1)


def test_red_flag_stays_after_cancel_and_shows_in_red_flag_at(service, clock):
    flagged = service.start("AST-01", "I fainted this morning", timestamp=AT_1030)
    service.cancel(flagged.session_id)
    assert service.red_flag_at("AST-01") == AT_1030
    assert service.red_flag_at("AST-02") is None
    clock.now = WALL + timedelta(hours=25)
    assert service.red_flag_at("AST-01") is None, "older than 24 h"


def test_urgent_words_in_an_invalid_answer_escalate(service):
    first = service.start("AST-01", "Fever since last night", timestamp=AT_1030)
    assert first.next_question.question_id == "screen-breathing"
    result = service.answer(first.session_id, question_id="screen-breathing", value="No, I can't breathe")
    assert result.status is TriageStatus.ESCALATED and result.red_flags == ("breathing",)
    assert ids(result.procedures)[0] == "rf-breathing"
    assert any(e.startswith("answer: ") and "not an answer" in e for e in result.errors)
    session = service.session(first.session_id)
    assert session.reports[-1].text == "No, I can't breathe", "the words are kept onboard"
    assert session.answers == (), "the invalid answer is not stored as an answer"


def test_wrong_question_with_urgent_text_escalates(service):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    result = service.answer(first.session_id, question_id="fever-chills", value=1, text="I can't breathe")
    assert result.status is TriageStatus.ESCALATED and result.red_flags == ("breathing",)
    assert any("not the open question" in e for e in result.errors)
    assert service.red_flag_at("AST-01") == AT_1030
    calm = service.start("AST-02", WORKED_EXAMPLE, timestamp=AT_1030)
    with pytest.raises(BadAnswer, match="not the open question"):  # no red flag: still a 422
        service.answer(calm.session_id, question_id="fever-chills", value=1, text="tired")


def test_parallel_turns_never_lose_a_red_flag(service, ran_pipeline, monkeypatch):
    import threading
    import time

    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    started, release = threading.Event(), threading.Event()
    real_assess = ran_pipeline.assess

    def slow_assess(*args, **kwargs):
        if threading.current_thread().name == "benign" and not started.is_set():
            started.set()
            release.wait(5)  # pause the benign turn half-way
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(ran_pipeline, "assess", slow_assess)
    failures = []

    def run(call):
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    benign = threading.Thread(name="benign", target=run, args=(lambda: service.answer(
        first.session_id, question_id="rash-tingling", value=2),))
    urgent = threading.Thread(name="urgent", target=run, args=(lambda: service.answer(
        first.session_id, text="I can't breathe"),))
    benign.start()
    assert started.wait(5)
    urgent.start()
    time.sleep(0.3)  # the urgent turn now waits for the session's lock
    release.set()
    benign.join(5)
    urgent.join(5)
    assert failures == []
    stored = service.session(first.session_id)
    assert stored.status is TriageStatus.ESCALATED and stored.result.red_flags == ("breathing",)
    assert [r.text for r in stored.reports] == [WORKED_EXAMPLE, "I can't breathe"]
    assert [a.question_id for a in stored.answers] == ["rash-tingling"]


def test_save_merges_red_flags_and_reports_with_the_store(service, ran_pipeline):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    stale = service.session(first.session_id)
    service.answer(first.session_id, text="I can't breathe")
    service._save(stale.model_copy(update={"done": True}))  # an old copy written last
    stored = service.session(first.session_id)
    assert stored.result.red_flags == ("breathing",) and stored.status is TriageStatus.ESCALATED
    assert len(stored.reports) == 2


def test_failing_step_logs_no_chat_text(ran_pipeline, clock, caplog):
    from orbit.schema import SymptomFinding

    class QuotingExtractor:
        def extract(self, report, ctx):
            return [SymptomFinding(label=report.text)]  # a real pydantic error: label over 80 chars

    secret = "SECRET-WORDS my private worry " + "x" * 80
    with caplog.at_level("DEBUG", logger="orbit.triage"):
        first = TriageService(ran_pipeline, extractor=QuotingExtractor(), clock=clock).start(
            "AST-01", secret, timestamp=AT_1030)
    assert first.errors[0].startswith("extractor: ValidationError")
    assert "SECRET-WORDS" not in caplog.text and "private worry" not in caplog.text
    assert f"triage step extractor failed: ValidationError (session {first.session_id})" in caplog.text
    assert all(r.exc_info is None for r in caplog.records), "no traceback either"


# ---- session rules -------------------------------------------------------------------------


def test_session_expires_after_the_timeout(service, clock):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    clock.now = WALL + timedelta(minutes=119)
    second = service.answer(first.session_id, question_id="rash-tingling", value=2)  # resets the timer
    assert second.status is TriageStatus.ASKING
    clock.now += timedelta(minutes=119)
    assert service.session(first.session_id).status is TriageStatus.ASKING
    clock.now += timedelta(minutes=2)
    expired = service.session(first.session_id)
    assert expired.status is TriageStatus.EXPIRED and expired.result.status is TriageStatus.EXPIRED
    with pytest.raises(SessionClosed, match="expired"):
        service.answer(first.session_id, question_id="one-side", value=True)
    assert [s.status for s in service.sessions("AST-01")] == [TriageStatus.EXPIRED]


def test_done_ends_the_questions(service):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    done = service.answer(first.session_id, done=True)
    assert done.status is TriageStatus.READY and done.next_question is None and done.procedures
    more = service.answer(first.session_id, text="Also a headache")
    assert more.next_question is None and S.SYMPTOM_HEADACHE in {f.signal for f in more.findings}
    assert service.session(first.session_id).done


def test_skipped_question_is_stored_as_none(service):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    skipped = service.answer(first.session_id, question_id="rash-tingling", value=None)
    assert skipped.next_question.question_id != "rash-tingling"
    assert service.session(first.session_id).answers[0].value is None


def test_bad_requests(service):
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    with pytest.raises(BadAnswer, match="not the open question"):
        service.answer(first.session_id, question_id="one-side", value=True)
    with pytest.raises(BadAnswer, match="not an answer"):
        service.answer(first.session_id, question_id="rash-tingling", value="very")
    with pytest.raises(BadAnswer, match="send a question_id"):
        service.answer(first.session_id)
    with pytest.raises(BadAnswer, match="1 to 1,000"):
        service.answer(first.session_id, text="")
    with pytest.raises(BadAnswer, match="not a symptom"):
        service.confirm(first.session_id, corrections={"skin_temp": 1})
    with pytest.raises(BadAnswer, match="0-3"):
        service.confirm(first.session_id, corrections={"symptom_fatigue": 5})
    with pytest.raises(BadAnswer, match="not a signal"):
        service.confirm(first.session_id, corrections={"sneezing": 1})
    with pytest.raises(SessionNotFound):
        service.session("tri-nope")
    with pytest.raises(UnknownAstronaut):
        service.start("AST-99", "tired", timestamp=AT_1030)
    with pytest.raises(BadAnswer, match="timezone"):
        service.start("AST-01", "tired", timestamp=datetime(2027, 4, 2, 10, 30))


def test_corrections_unrated_symptoms_and_other_complaints(service, ran_pipeline):
    first = service.start("AST-01", "Tired, a headache and some nausea", timestamp=AT_1030)
    service.answer(first.session_id, done=True)
    result, _ = service.confirm(first.session_id, corrections={"symptom_headache": 0,
                                                               "symptom_mouth_sores": 1})
    saved = {o.signal: o.value for o in ran_pipeline.store.observations("AST-01", start=AT_1030, end=AT_1030)}
    assert saved == {S.SYMPTOM_FATIGUE: 1, S.SYMPTOM_HEADACHE: 0, S.SYMPTOM_MOUTH_SORES: 1}
    assert "Nausea" in {f.label for f in result.findings if f.signal is None}, "kept in the session only"


# ---- failures stay contained ---------------------------------------------------------------


class BrokenReasoner:
    questions = ()
    max_questions = 5

    def rank(self, evidence, ctx):
        raise RuntimeError("bad weights")

    def next_question(self, evidence, ranking, ctx):
        raise RuntimeError("no bank")


def test_failing_reasoner_leaves_the_reassessment_cards(settings, ran_pipeline, clock):
    service = TriageService(ran_pipeline, reasoner=BrokenReasoner(), clock=clock)
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    assert first.status is TriageStatus.READY and first.ranking == ()
    assert first.errors == ("rank: RuntimeError: bad weights", "next_question: RuntimeError: no bank")
    result, day = service.confirm(first.session_id, corrections={"symptom_rash_tingling": 2,
                                                                 "symptom_fever_chills": 0})
    assert result.errors == ("rank: RuntimeError: bad weights",)
    assert day.assessment.score == 44.7
    assert ids(day.actions) == ["saliva-test", "rest-watch"], "the protocol engine's cards remain"


def test_failing_extractor_is_recorded(ran_pipeline, clock):
    class BrokenExtractor:
        def extract(self, report, ctx):
            raise ValueError("lexicon missing")

    first = TriageService(ran_pipeline, extractor=BrokenExtractor(), clock=clock).start(
        "AST-01", "tired", timestamp=AT_1030)
    assert first.errors == ("extractor: ValueError: lexicon missing",) and first.findings == ()


# ---- config ---------------------------------------------------------------------------------


def test_triage_config_from_orbit_toml(settings):
    triage = load_triage_settings(settings)
    assert triage.extractor.use == "lexicon" and triage.reasoner.use == "rules"
    assert triage.session_timeout_minutes == 120
    assert triage.reasoner.options["max_questions"] == 5
    assert triage.reasoner.options["stop_probability"] == 0.8
    for path in (triage.patterns_path, triage.triage_cards_path, triage.red_flags_path,
                 triage.extractor.options["lexicon_path"], triage.reasoner.options["questions_path"]):
        assert path.startswith(str(ROOT)) and (ROOT / path).is_file()
    assert set(settings.modules) == {"baseline", "detector", "scorer", "actions", "sync"}, \
        "the triage slots are not analytics slots"


def test_triage_config_defaults_and_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORBIT_CONFIG", raising=False)
    defaults = load_triage_settings(load_settings())
    assert defaults.extractor.use == "lexicon" and defaults.patterns_path is None
    plain = tmp_path / "plain.toml"
    plain.write_text("[mission]\nname = 'x'\n", encoding="utf-8")
    assert load_triage_settings(load_settings(plain)).reasoner.use == "rules"
    for body, problem in (("[triage]\npatern_path = 'x'\n", "unknown keys"),
                          ("[triage]\nsession_timeout_minutes = 0\n", "between 1 and 1440"),
                          ("[triage.reasoner]\nmax_questions = 3\n", "use =")):
        bad = tmp_path / "bad.toml"
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(ConfigError, match=problem):
            load_triage_settings(load_settings(bad))


def test_built_in_service_works_without_config(loaded_pipeline, clock):
    service = TriageService(loaded_pipeline, clock=clock)
    first = service.start("AST-01", WORKED_EXAMPLE, timestamp=AT_1030)
    assert first.next_question.question_id == "rash-tingling"
    assert service.module_names == {"extractor": "LexiconExtractor", "reasoner": "RulesReasoner"}


def test_pipeline_still_builds_only_the_analytics(settings):
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    assert set(pipeline.module_names) == {"baseline", "detector", "scorer", "actions", "sync"}
    assert create("extractor", "lexicon") and create("reasoner", "rules")
