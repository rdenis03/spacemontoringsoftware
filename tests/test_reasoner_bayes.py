"""B24 step 3: the ``bayes`` reasoner and its trainer."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from conftest import ROOT

from orbit.core import Pipeline, SourceBatch, Store, create, load_settings
from orbit.core.interfaces import TriageEvidence
from orbit.learning.train_reasoner import (
    HELD_OUT_SEEDS,
    chat_days,
    checkin_findings,
    iter_training,
    lab_values,
    parse_seeds,
    train,
)
from orbit.learning.train_reasoner import main as train_main
from orbit.modules.reasoner_bayes import (
    DEFAULT_WEIGHTS,
    OTHER_CLUE,
    OTHER_COMPLAINT_TABLE,
    CONTRIBUTOR_CLUES,
    BayesReasoner,
    clue_names,
    clue_values,
    load_reasoner_weights,
    observe,
)
from orbit.schema import (
    Contributor,
    CrewMember,
    Observation,
    SignalType,
    SymptomFinding,
    TriageAnswer,
    TriagePattern,
    TriageQuestion,
    get_spec,
    parse_jsonl,
)
from orbit.triage.config import load_triage_settings
from orbit.triage.service import TriageService

P = TriagePattern
S = SignalType
UTC = timezone.utc
AT_1030 = datetime(2027, 4, 2, 10, 30, tzinfo=UTC)  # day 89, the worked example
QUESTIONS = str(ROOT / "cards" / "questions.jsonl")
BANK = {q.question_id: q for q in parse_jsonl(QUESTIONS, TriageQuestion).raise_if_errors()}
WORKED = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."


def finding(signal, severity=None, negated=False, **extra):
    return SymptomFinding(signal=signal, label=get_spec(signal).label, severity=severity,
                          negated=negated, **extra)


def answer(question_id, value):
    return TriageAnswer(question_id=question_id, value=value, answered_at=AT_1030)


def evidence(findings=(), answers=(), asked=(), preview=None, anomalies=()):
    return TriageEvidence(findings=tuple(findings), answers=tuple(answers), asked=tuple(asked),
                          preview=preview, anomalies=tuple(anomalies))


def _uniform(values):
    return {v: round(1 / len(values), 6) for v in values}


@pytest.fixture(scope="module")
def test_weights(tmp_path_factory):
    """A deterministic hand-made weights file: uninformative, except a rash points to vzv_like."""
    features = {n: {p.value: _uniform(clue_values(n)) for p in P} for n in clue_names()}
    features[OTHER_CLUE] = OTHER_COMPLAINT_TABLE
    rash = {p.value: {"0": 0.85, "1": 0.07, "2": 0.05, "3": 0.03} for p in P}
    rash["vzv_like"] = {"0": 0.1, "1": 0.3, "2": 0.4, "3": 0.2}
    rash["hsv1_like"] = {"0": 0.6, "1": 0.2, "2": 0.15, "3": 0.05}
    features["sym:symptom_rash_tingling"] = rash
    doc = {
        "version": "test-1",
        "priors": {p.value: 0.125 for p in P},
        "features": features,
        "answers": {qid: {p.value: {k: q.likelihood(p, k) for k in q.answer_keys} for p in P}
                    for qid, q in BANK.items() if not q.is_symptom_question and q.likelihoods},
    }
    path = tmp_path_factory.mktemp("bayes") / "weights.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


@pytest.fixture
def ctx(ran_pipeline):
    return ran_pipeline.context("AST-01", AT_1030)


@pytest.fixture
def shipped():
    return create("reasoner", "bayes", questions_path=QUESTIONS)


# ---- ranking -----------------------------------------------------------------------


def test_builds_with_no_options_and_names_its_version():
    module = create("reasoner", "bayes")
    version, priors, features, answers = load_reasoner_weights(DEFAULT_WEIGHTS)
    assert module.version == f"bayes-{version}"
    assert set(features) == set(clue_names())
    assert abs(sum(priors.values()) - 1) < 1e-3


def test_probabilities_sum_to_one_and_are_sorted(shipped, ctx):
    ev = evidence([finding(S.SYMPTOM_RASH_TINGLING, 2), finding(S.SYMPTOM_FATIGUE, 2)])
    ranking = shipped.rank(ev, ctx)
    assert {s.pattern for s in ranking} == set(P)
    assert abs(sum(s.probability for s in ranking) - 1) < 1e-6
    assert [s.probability for s in ranking] == sorted((s.probability for s in ranking), reverse=True)
    assert ranking == shipped.rank(ev, ctx)
    assert ranking[0].pattern is P.VZV_LIKE


def test_reasons_are_the_top_three_present_clues(shipped, ctx):
    ev = evidence([finding(S.SYMPTOM_RASH_TINGLING, 2), finding(S.SYMPTOM_FATIGUE, 2),
                   finding(S.SYMPTOM_FEVER_CHILLS, 0, negated=True)])
    for score in shipped.rank(ev, ctx):
        assert len(score.reasons) <= 3
        assert all(isinstance(r, Contributor) and r.points > 0 for r in score.reasons)
        assert all(r.signal is not None or r.event_id is not None for r in score.reasons)
        assert [r.points for r in score.reasons] == sorted((r.points for r in score.reasons), reverse=True)
        assert all("Fever" not in r.label for r in score.reasons)  # a denied symptom is never a reason


def test_the_eva_is_a_clue_for_exertion(shipped, ctx):
    ev = evidence([finding(S.SYMPTOM_MUSCLE_ACHES, 2), finding(S.SYMPTOM_FATIGUE, 1)])
    exertion = next(s for s in shipped.rank(ev, ctx) if s.pattern is P.EXERTION)
    assert any(r.event_id and "Spacewalk" in r.label for r in exertion.reasons)


def test_symptom_answers_are_not_counted_twice(test_weights, ctx):
    """B23 hand-off: the service already merges symptom answers into the findings."""
    module = BayesReasoner(weights_path=test_weights, questions_path=QUESTIONS)
    merged = [finding(S.SYMPTOM_RASH_TINGLING, 2)]
    with_answer = evidence(merged, [answer("rash-tingling", 2)], asked=["rash-tingling"])
    without = evidence(merged, asked=["rash-tingling"])
    assert module.rank(with_answer, ctx) == module.rank(without, ctx)
    assert not [c for c in observe(with_answer, ctx, module._by_id) if c.name.startswith("ans:")]
    # ... while a non-symptom answer counts:
    one_side = evidence(merged, [answer("one-side", True)], asked=["one-side"])
    clues = observe(one_side, ctx, module._by_id)
    assert [c.name for c in clues if c.name.startswith("ans:")] == ["ans:one-side"]
    assert module.rank(one_side, ctx) != module.rank(without, ctx)


def test_unmentioned_symptoms_are_unknown_not_denied(shipped, ctx):
    clues = observe(evidence([finding(S.SYMPTOM_FATIGUE)]), ctx)
    symptoms = {c.name: c.value for c in clues if c.name.startswith("sym:")}
    assert symptoms == {"sym:symptom_fatigue": "present"}


# ---- next question -----------------------------------------------------------------


def test_severity_first_then_the_one_side_question(test_weights, ctx):
    """Worked example with the hand-made weights: severity, then the most informative question."""
    module = BayesReasoner(weights_path=test_weights, questions_path=QUESTIONS, stop_probability=1.0)
    found = [finding(S.SYMPTOM_RASH_TINGLING, body_site="ribs", onset_hours=12.0),
             finding(S.SYMPTOM_FATIGUE, 2)]
    first = evidence(found)
    assert module.next_question(first, module.rank(first, ctx), ctx).question_id == "rash-tingling"
    second = evidence([found[0].model_copy(update={"severity": 2}), found[1]],
                      [answer("rash-tingling", 2)],
                      asked=["rash-tingling"])
    ranking = module.rank(second, ctx)
    q = module.next_question(second, ranking, ctx)
    assert q.question_id == "one-side"
    gains = {q.question_id: module.information_gain(q, ranking) for q in module.questions}
    assert gains["one-side"] == max(g for qid, g in gains.items() if qid not in ("rash-tingling",)
                                    and not BANK[qid].screening)
    assert gains["recent-exertion"] > 0  # informative, but known: the EVA is in ctx.events


def test_spacewalk_question_is_skipped_when_the_eva_is_known(test_weights, ctx):
    module = BayesReasoner(weights_path=test_weights, questions_path=QUESTIONS, stop_probability=1.0)
    ev = evidence([finding(S.SYMPTOM_MUSCLE_ACHES, 2)])
    seen = []
    for _ in range(5):
        q = module.next_question(ev, module.rank(ev, ctx), ctx)
        if q is None:
            break
        seen.append(q.question_id)
        ev = replace(ev, asked=ev.asked + (q.question_id,))
    assert "recent-exertion" not in seen


def test_screening_comes_first(shipped, ctx):
    ev = evidence([finding(S.SYMPTOM_FEVER_CHILLS, 2)])
    assert shipped.next_question(ev, shipped.rank(ev, ctx), ctx).question_id == "screen-breathing"


def test_screening_and_severity_come_before_the_stop_rule(shipped, ctx):
    """On purpose (docstring): a confident model still asks the safety screening question."""
    ev = evidence([finding(S.SYMPTOM_RASH_TINGLING, 2), finding(S.SYMPTOM_FATIGUE, 2)])
    ranking = shipped.rank(ev, ctx)
    assert ranking[0].probability >= 0.8
    assert shipped.next_question(ev, ranking, ctx).question_id == "screen-eye"


def test_stop_rules(shipped, test_weights, ctx):
    ev = evidence([finding(S.SYMPTOM_RASH_TINGLING, 2, body_site="ribs"), finding(S.SYMPTOM_FATIGUE, 2)])
    assert shipped.next_question(ev, shipped.rank(ev, ctx), ctx) is None  # vzv_like above 0.8
    asked = evidence(ev.findings, asked=("a", "b", "c", "d", "e"))
    assert shipped.next_question(asked, shipped.rank(asked, ctx), ctx) is None  # max_questions
    picky = BayesReasoner(weights_path=test_weights, questions_path=QUESTIONS,
                          stop_probability=1.0, min_gain_bits=10.0)
    assert picky.next_question(ev, picky.rank(ev, ctx), ctx) is None  # nothing gains 10 bits


def test_information_gain_is_in_bits(test_weights):
    module = BayesReasoner(weights_path=test_weights, questions_path=QUESTIONS)
    flat = [type("S", (), {"pattern": p, "probability": 1 / 8})() for p in P]
    assert module.information_gain(BANK["mouth-sores"], flat) == pytest.approx(0, abs=1e-9)
    gain = module.information_gain(BANK["one-side"], flat)
    assert 0 < gain <= 1  # a yes/no answer gives at most 1 bit
    assert module.information_gain(BANK["one-side"], [flat[0]]) == pytest.approx(0, abs=1e-9)


def test_worked_example_through_the_service(settings, ran_pipeline):
    """Shipped weights: severity first, then vzv_like is above 0.8, so the session is ready."""
    ts = load_triage_settings(settings)
    ts = replace(ts, reasoner=replace(ts.reasoner, use="bayes"))
    service = TriageService.from_settings(ts, ran_pipeline)
    first = service.start("AST-01", WORKED, timestamp=AT_1030)
    assert first.next_question.question_id == "rash-tingling"
    assert "bayes-" in first.model_version
    ready = service.answer(first.session_id, question_id="rash-tingling", value="moderate")
    assert ready.status.value == "ready" and ready.ranking[0].pattern is P.VZV_LIKE
    result, day = service.confirm(first.session_id)
    assert (day.assessment.level.value, day.assessment.score) == ("yellow", 44.7)
    assert [c.card_id for c in result.procedures][0] == "saliva-test"


# ---- weights files -----------------------------------------------------------------


def _rename_key(row, old, new):
    row[new] = row.pop(old)


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(version=""), "version"),
    (lambda d: d["priors"].update(vzv_like=0.9), "priors"),
    (lambda d: d["features"].pop("event:eva"), "features"),
    (lambda d: d["features"]["event:eva"]["stress"].update(yes=0.0), "row stress"),
    (lambda d: d["answers"]["one-side"].pop("other"), "8 patterns"),
    # answer keys must match the question bank (else KeyError mid-chat in information_gain):
    # missing ("yes" renamed to "maybe" in every row)
    (lambda d: [_rename_key(r, "yes", "maybe") for r in d["answers"]["one-side"].values()],
     "question bank"),
    # extra (an answer the question does not have, in every row)
    (lambda d: [r.update(maybe=0.0001, no=r["no"] - 0.0001) for r in d["answers"]["one-side"].values()],
     "question bank"),
    # inconsistent (one row differs from the others)
    (lambda d: _rename_key(d["answers"]["one-side"]["stress"], "yes", "maybe"), "same answer keys"),
])
def test_bad_weights_files_are_refused(tmp_path, change, message):
    doc = json.loads(DEFAULT_WEIGHTS.read_text(encoding="utf-8"))
    change(doc)
    path = tmp_path / "w.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        BayesReasoner(weights_path=str(path), questions_path=QUESTIONS)


# ---- trainer ----------------------------------------------------------------------


@pytest.mark.parametrize("seeds", [[101], [1, 103], list(HELD_OUT_SEEDS)])
def test_held_out_seeds_are_refused(seeds, tmp_path):
    with pytest.raises(ValueError, match="held out"):
        train(seeds, days=30, crew=1, out=tmp_path / "w.json")
    assert not (tmp_path / "w.json").exists()


def test_trainer_is_deterministic(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    doc = train([2], days=60, crew=2, out=a)
    train([2], days=60, crew=2, out=b)
    assert a.read_bytes() == b.read_bytes()
    assert doc["version"] == "s2-d60-c2"
    BayesReasoner(weights_path=str(a))  # loads
    assert b"\r\n" not in a.read_bytes()


def test_shipped_weights_match_a_retrain(tmp_path):
    """The shipped file is exactly what the trainer writes with its default arguments."""
    out = tmp_path / "w.json"
    assert train_main(["--out", str(out)]) == 0
    assert out.read_bytes() == DEFAULT_WEIGHTS.read_bytes()


LAB_DAY = datetime(2027, 6, 1, 10, 30, tzinfo=UTC)


def lab_day(*readings):
    """``lab_values`` and ``observe``'s lab clues at LAB_DAY, through a real pipeline.

    ``readings`` are (signal, value, days before LAB_DAY) for one astronaut with no other data.
    """
    settings = replace(load_settings(ROOT / "orbit.toml"), sources=())
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    member = CrewMember(astronaut_id="AST-09", callsign="Lab",
                        mission_start=LAB_DAY - timedelta(days=60))
    pipeline.ingest(SourceBatch(source_name="test", crew=(member,), observations=tuple(
        Observation(astronaut_id="AST-09", timestamp=LAB_DAY - timedelta(days=days), signal=signal,
                    value=value, unit=get_spec(signal).unit, source="lab")
        for signal, value, days in readings)))
    preview = pipeline.assess("AST-09", LAB_DAY, save=False)
    ctx = pipeline.context("AST-09", LAB_DAY)
    ev = TriageEvidence(findings=checkin_findings(ctx), answers=(), asked=(),
                        preview=preview.assessment, anomalies=tuple(preview.anomalies))
    clues = observe(ev, ctx)
    return lab_values(clues, ctx), {c.name: c.value for c in clues if c.name.startswith("lab:")}, ctx


def test_a_positive_lab_in_the_recent_window_counts_yes_like_at_run_time():
    counted, emitted, ctx = lab_day((S.SALIVA_VZV_DNA, 850.0, 2))  # 2 days before, inside 3
    assert ctx.recent_days == 3
    assert counted == {"lab:saliva_vzv_dna": "yes"}  # the other labs were not measured: skipped
    assert emitted == {"lab:saliva_vzv_dna": "yes"}  # the live clue sees the same reading


def test_a_measured_negative_lab_counts_as_no():
    counted, emitted, _ = lab_day((S.SALIVA_HSV1_DNA, 20.0, 1))  # below the detection limit
    assert counted == {"lab:saliva_hsv1_dna": "no"}
    assert emitted == {}  # at run time a negative is not a clue (unknown), only in training


def test_a_lab_older_than_the_recent_window_is_skipped():
    _, _, ctx = lab_day()
    counted, emitted, _ = lab_day((S.SALIVA_EBV_DNA, 5000.0, ctx.recent_days + 1),
                                  (S.CRP, 2.0, ctx.recent_days + 1))
    assert counted == {} and emitted == {}


def test_lab_counting_matches_the_run_time_clue_on_a_small_run():
    """Every lab "yes" observe() emits is counted, and every counted lab is in the recent window."""
    counted_any = 0
    for _, ev, ctx in iter_training([2], 60, 2, ROOT / "orbit.toml", 0.3):
        clues = observe(ev, ctx)
        counted = lab_values(clues, ctx)
        for c in clues:
            if c.name.startswith("lab:"):
                assert c.value == "yes" and counted[c.name] == "yes"
        for name in counted:
            signal = next(s for s, n in CONTRIBUTOR_CLUES.items() if n == name)
            reading = ctx.latest(signal)
            assert reading is not None and ctx.recent_start <= reading.timestamp <= ctx.as_of
        counted_any += len(counted)
    assert counted_any > 0  # the run has lab readings, so the checks above ran


@pytest.mark.parametrize("lab, own", [
    ("lab:saliva_vzv_dna", "vzv_like"), ("lab:saliva_hsv1_dna", "hsv1_like"),
    ("lab:saliva_ebv_dna", "ebv_like")])
def test_a_positive_saliva_result_points_to_its_virus(lab, own):
    table = json.loads(DEFAULT_WEIGHTS.read_text(encoding="utf-8"))["features"][lab]
    others = max(row["yes"] for pattern, row in table.items() if pattern != own)
    assert table[own]["yes"] / others >= 10


def test_chat_days_map_labels_to_patterns():
    sim = create("source", "simulator", days=180, seed=1, symptom_lookalikes=True,
                 mild_illness_rate=0.3)
    days = chat_days(sim)
    expected = {P.RESPIRATORY, P.EXERTION, P.SLEEP_LOSS, P.STRESS, P.OTHER} | {
        {"vzv": P.VZV_LIKE, "hsv1": P.HSV1_LIKE, "ebv": P.EBV_LIKE}[e.virus]
        for e in sim.episodes if e.virus}
    assert {c.pattern for c in days} == expected
    keys = [(c.astronaut_id, c.mission_day) for c in days]
    assert len(keys) == len(set(keys))  # one pattern per astronaut-day
    for e in sim.episodes:
        on_day0 = next(c for c in days if (c.astronaut_id, c.mission_day) == (e.astronaut_id, e.symptom_day))
        assert on_day0.label_id == e.label(sim.day_start).label_id


def test_parse_seeds_matches_the_scorer_trainer():
    sklearn_train = pytest.importorskip("orbit.learning.train")
    for text in ("1-20", "1,2,5", "1-3,7", " 4 , 2 "):
        assert parse_seeds(text) == sklearn_train.parse_seeds(text)
    assert HELD_OUT_SEEDS == sklearn_train.HELD_OUT_SEEDS


def test_shipped_weights_document_their_training():
    doc = json.loads(DEFAULT_WEIGHTS.read_text(encoding="utf-8"))
    info = doc["trained_on"]
    assert doc["version"] == "s1-20-d180-c4"
    assert info["simulated"] and info["seeds"] == list(range(1, 21))
    assert info["symptom_lookalikes"] and info["mild_illness_rate"] == 0.3
    assert "hand-set" in info["answers_from"]
    assert all(math.isfinite(v) for v in doc["priors"].values())
