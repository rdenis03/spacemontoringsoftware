"""B24 step 4: the triage evaluation, on a tiny config (one seed, 60 days, 2 crew)."""

from __future__ import annotations

import json
import random

import pytest
from conftest import ROOT

from orbit.core import create
from orbit.evaluation import triage as ev
from orbit.learning.train_reasoner import ChatDay
from orbit.learning.utterances import describe
from orbit.schema import SignalType, TriagePattern, TriageQuestion, parse_jsonl
from orbit.triage.red_flags import RedFlagRules

BASE = str(ROOT / "orbit.toml")
LEARNED = str(ROOT / "experiments" / "triage_learned.toml")
BANK = {q.question_id: q for q in parse_jsonl(ROOT / "cards" / "questions.jsonl", TriageQuestion).valid}
S = SignalType


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("triage_eval") / "report.json"
    doc = ev.main(["--config", BASE, "--config", LEARNED, "--seeds", "2", "--days", "60",
                   "--crew", "2", "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(json.dumps(doc))
    return doc


def test_report_has_the_documented_parts(report):
    assert report["simulated"] is True
    assert "hand-set" in report["note"] and "provisional" in report["note"]
    assert report["settings"]["seeds"] == [2]
    base, learned = report["configs"]
    assert base["modules"] == {"extractor": "lexicon", "reasoner": "rules"}
    assert learned["modules"] == {"extractor": "text_linear", "reasoner": "bayes"}
    for config in report["configs"]:
        assert config["extractor"]["provisional"] is True
        assert config["red_flags"]["recall"] == 1.0
        r = config["reasoner"]
        assert r["extractor_used"] == "lexicon"
        for key in ("without_answers", "with_answers"):
            assert r[key]["n"] > 0
            assert 0 <= r[key]["top1"] <= r[key]["top3"] <= 1
            assert 0 <= r[key]["brier"] <= 2
        assert r["chat_errors"] == 0 and config["confirmed_chat_errors"] == 0
        assert set(config["m9"]) == {"m9_without_chats", "m9_with_chats"}


def test_switch_rules_are_checked_and_text_linear_waits_for_human_sentences(report):
    rules = report["switch"][LEARNED.replace("\\", "/")]
    assert set(rules) == {"extractor", "reasoner", "m9", "demo_story"}
    assert rules["extractor"]["human_sentences_are_the_stub"] is True
    assert rules["extractor"]["recommend_switch"] is False
    assert "human-written" in rules["extractor"]["why"]
    assert set(rules["reasoner"]) >= {"without_answers", "with_answers", "no_more_questions",
                                      "recommend_switch"}
    assert rules["reasoner"]["main_comparison"].startswith("without_answers")


def test_the_evaluation_is_deterministic(report):
    again = ev.run_all([BASE, LEARNED], [2], days=60, crew=2, progress=None)
    assert json.loads(json.dumps(again)) == json.loads(json.dumps(report))


def test_extractor_metrics_on_a_tiny_file(tmp_path):
    lines = [{"text": "Pretty tired, no fever.", "source": "stub",
              "findings": {"symptom_fatigue": {"severity": 2, "negated": False},
                           "symptom_fever_chills": {"severity": 0, "negated": True}}},
             {"text": "All good today.", "source": "stub", "findings": {}}]
    path = tmp_path / "h.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    m = ev.extractor_metrics(create("extractor", "lexicon"), path)
    assert m["provisional"] and m["sentences"] == 2
    assert m["f1"]["symptom_fatigue"] == 1.0 and m["f1"]["symptom_mouth_sores"] is None
    assert m["negation_accuracy"] == 1.0 and m["severity_within_one"] == 1.0


def test_red_flag_metrics():
    m = ev.red_flag_metrics(RedFlagRules.load(str(ROOT / "cards" / "red_flags.jsonl")))
    assert m["recall"] == 1.0 and m["missed"] == [] and m["false_fires"] == 0


def test_simulated_answers():
    chat = ChatDay("AST-01", 30, TriagePattern.VZV_LIKE, None)
    levels = {S.SYMPTOM_RASH_TINGLING: 2}
    assert ev._answer(BANK["rash-tingling"], chat, levels, 1, 0) == 2
    assert ev._answer(BANK["fatigue"], chat, levels, 1, 0) == 0  # not in the check-in
    assert ev._answer(BANK["screen-eye"], chat, levels, 1, 0) is False  # red flags are part 2
    first = ev._answer(BANK["one-side"], chat, levels, 1, 0)
    assert isinstance(first, bool) and first == ev._answer(BANK["one-side"], chat, levels, 1, 0)


def test_describe_uses_the_day_s_symptoms():
    text = describe({S.SYMPTOM_FATIGUE: 2, S.SYMPTOM_HEADACHE: 0}, random.Random(1))
    found = {f.signal for f in create("extractor", "lexicon",
                                      lexicon_path=str(ROOT / "cards" / "symptom_lexicon.jsonl")).read(text)}
    assert S.SYMPTOM_FATIGUE in found and S.SYMPTOM_HEADACHE not in found
    assert describe({}, random.Random(1))  # no symptoms: a complaint outside the 8 signals


def test_brier_score():
    one = [type("S", (), {"pattern": p, "probability": float(p is TriagePattern.STRESS)})()
           for p in TriagePattern]
    assert ev._brier(one, TriagePattern.STRESS) == 0
    assert ev._brier(one, TriagePattern.OTHER) == 2


def test_committed_report_is_simulated_and_relative():
    doc = json.loads((ROOT / "reports" / "triage_eval.json").read_text(encoding="utf-8"))
    assert doc["simulated"] is True and doc["settings"]["seeds"] == [101, 102, 103, 104, 105]
    assert [c["config"] for c in doc["configs"]] == ["orbit.toml", "experiments/triage_learned.toml"]
    assert "hand-set" in doc["note"]
