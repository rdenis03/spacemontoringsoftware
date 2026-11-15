"""B24 step 2: the ``text_linear`` extractor, its training sentences and its trainer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orbit.core import create
from orbit.learning.train_reasoner import HELD_OUT_SEEDS
from orbit.learning.utterances import generate, load_extra
from orbit.modules import extractor_learned
from orbit.modules.extractor import EVIDENCE_LIMIT
from orbit.modules.extractor_learned import (
    DEFAULT_WEIGHTS,
    TextLinearExtractor,
    clauses,
    features,
    load_text_weights,
)
from orbit.schema import SignalType

S = SignalType
ROOT = Path(__file__).resolve().parents[1]
LEXICON = str(ROOT / "cards" / "symptom_lexicon.jsonl")
HUMAN = ROOT / "tests" / "fixtures" / "triage" / "human_sentences.jsonl"
WORKED = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."


@pytest.fixture(scope="module")
def extractor() -> TextLinearExtractor:
    module = create("extractor", "text_linear", lexicon_path=LEXICON)
    assert isinstance(module, TextLinearExtractor)
    return module


def by_signal(findings):
    return {f.signal: f for f in findings if f.signal is not None}


# ---- the extractor ------------------------------------------------------------------


def test_builds_with_no_options_from_the_shipped_weights():
    module = create("extractor", "text_linear")
    version, threshold, signals, severity = load_text_weights(DEFAULT_WEIGHTS)
    assert module.version == f"text_linear-{version}"
    assert set(signals) == {s for s in S if s.value.startswith("symptom_")}
    assert 0 < threshold < 1 and set(severity) == {"0", "1", "2", "3"}


def test_worked_example(extractor):
    found = by_signal(extractor.read(WORKED))
    assert set(found) == {S.SYMPTOM_RASH_TINGLING, S.SYMPTOM_FATIGUE}
    rash, fatigue = found[S.SYMPTOM_RASH_TINGLING], found[S.SYMPTOM_FATIGUE]
    assert rash.severity is None and not rash.negated
    assert rash.body_site == "ribs" and rash.onset_hours == 12.0
    assert fatigue.severity == 2 and not fatigue.negated
    assert fatigue.body_site is None  # "ribs" goes to the rash, not the fatigue
    for f in found.values():
        assert all(e.lower() in WORKED.lower() for e in f.evidence)


@pytest.mark.parametrize("text, signal", [
    ("Fever since yesterday, no sore throat", S.SYMPTOM_SORE_THROAT),
    ("I don't have a headache but I'm tired", S.SYMPTOM_HEADACHE),
    ("Nauseous and a bit dizzy, no fever.", S.SYMPTOM_FEVER_CHILLS),
    ("Without any chills today", S.SYMPTOM_FEVER_CHILLS),
])
def test_negation(extractor, text, signal):
    finding = by_signal(extractor.read(text))[signal]
    assert finding.negated and finding.severity == 0


def test_negation_stops_at_but_and_and(extractor):
    found = by_signal(extractor.read("I don't have a headache but I'm tired"))
    assert not found[S.SYMPTOM_FATIGUE].negated
    found = by_signal(extractor.read("no fever and a sore throat"))
    assert found[S.SYMPTOM_FEVER_CHILLS].negated
    assert not found[S.SYMPTOM_SORE_THROAT].negated


@pytest.mark.parametrize("text, signal, negated", [
    ("No rash and a burning patch.", S.SYMPTOM_RASH_TINGLING, False),
    ("I have a burning patch on my side but no rash.", S.SYMPTOM_RASH_TINGLING, False),
    ("No rash.", S.SYMPTOM_RASH_TINGLING, True),
    ("No fever and I have chills.", S.SYMPTOM_FEVER_CHILLS, False),
    ("no tingling in that patch", S.SYMPTOM_RASH_TINGLING, True),  # one mention: still denied
])
def test_a_denied_and_a_positive_mention_of_one_symptom(extractor, text, signal, negated):
    """Review fix: each mention has its own negation; any positive one makes the finding positive."""
    found = by_signal(extractor.read(text))[signal]
    assert found.negated is negated
    assert (found.severity == 0) is negated
    lexicon = by_signal(create("extractor", "lexicon", lexicon_path=LEXICON).read(text))[signal]
    assert lexicon.negated is negated  # the same answer as the starter


def test_complaints_outside_the_8_signals_are_kept(extractor):
    findings = extractor.read("Nauseous and a bit dizzy, no fever.")
    others = {f.label: f for f in findings if f.signal is None}
    assert {"Nausea", "Dizziness"} <= set(others)
    assert others["Dizziness"].severity == 1


def test_nothing_in_a_healthy_text(extractor):
    assert extractor.read("Feeling great today, slept well.") == []


def test_empty_text_gives_nothing(extractor):
    assert extractor.read("   ") == []
    assert extractor.read("...!") == []


def test_report_of_244_characters(extractor):
    """B23 fix: a long word must not push the evidence over the 200-character cap."""
    report = "I feel pretty " + "x" * 218 + " tired today"
    assert len(report) == 244
    fatigue = by_signal(extractor.read(report))[S.SYMPTOM_FATIGUE]
    assert all(len(e) <= EVIDENCE_LIMIT and e in report for e in fatigue.evidence)
    assert any("tired" in e for e in fatigue.evidence)  # the mention's own words survive the cap


def test_report_of_1000_characters(extractor):
    chunk = "Pretty wiped out and a sore throat since last night, no fever. "
    report = (chunk * 20)[:1000]
    assert len(report) == 1000
    findings = extractor.read(report)
    assert findings
    assert all(len(e) <= EVIDENCE_LIMIT and e in report for f in findings for e in f.evidence)
    found = by_signal(findings)
    assert found[S.SYMPTOM_FATIGUE].severity == 2
    assert found[S.SYMPTOM_FEVER_CHILLS].negated


def test_one_word_of_1000_characters(extractor):
    report = "tired" + "y" * 995
    assert len(report) == 1000
    for f in extractor.read(report):
        assert all(len(e) <= EVIDENCE_LIMIT and e in report for e in f.evidence)


def test_deterministic(extractor):
    assert extractor.read(WORKED) == create("extractor", "text_linear",
                                            lexicon_path=LEXICON).read(WORKED)


def test_threshold_option():
    strict = create("extractor", "text_linear", threshold=0.999)
    assert strict.threshold == 0.999
    with pytest.raises(ValueError):
        create("extractor", "text_linear", threshold=1.5)


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(version=""), "version"),
    (lambda d: d.update(threshold=2), "threshold"),
    (lambda d: d["signals"].update(mood={"bias": 0, "weights": {}}), "not a symptom"),
    (lambda d: d["signals"].update(nonsense={"bias": 0, "weights": {}}), "unknown signal"),
    (lambda d: d["signals"]["symptom_fatigue"]["weights"].update(tired=1.0), "features"),
    (lambda d: d["severity"].pop("3"), "severity"),
    (lambda d: d["signals"].pop("symptom_fever_chills"), "missing symptom signals"),
])
def test_bad_weights_files_are_refused(tmp_path, change, message):
    doc = json.loads(DEFAULT_WEIGHTS.read_text(encoding="utf-8"))
    change(doc)
    path = tmp_path / "w.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_text_weights(path)


def test_modules_never_import_orbit_learning_at_the_top():
    source = Path(extractor_learned.__file__).read_text(encoding="utf-8")
    assert "import orbit.learning" not in source and "from orbit.learning" not in source


def test_features_and_clauses():
    assert {"w:wiped", "w:wiped out", "c: wi", "c:iped "} <= features(["wiped", "out"])
    words = ["hot", "and", "cold", ",", "tired", "but", "fine"]
    assert clauses(words) == [(0, 3), (4, 5), (6, 7)]  # "and" does not end a clause


# ---- training sentences ----------------------------------------------------------------


def test_generator_is_seeded_and_spans_are_right():
    first, again = generate(200, seed=3), generate(200, seed=3)
    assert [u.text for u in first] == [u.text for u in again]
    assert [u.text for u in first] != [u.text for u in generate(200, seed=4)]
    for u in first:
        for m in u.mentions:
            assert 0 <= m.start < m.end <= len(u.text)
            assert u.text[m.start:m.end].strip() == u.text[m.start:m.end]
        assert set(u.labels) == {m.signal for m in u.mentions}


def test_extra_paraphrases_load_and_stay_out_of_the_test_set():
    extra = load_extra()
    assert len(extra) >= 50
    human = {json.loads(line)["text"].lower() for line in HUMAN.read_text(encoding="utf-8").splitlines()}
    assert not human & {u.text.lower() for u in extra}
    assert not human & {u.text.lower() for u in generate(4000, seed=1)}


def test_human_sentences_stub_is_marked():
    lines = [json.loads(line) for line in HUMAN.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 20  # a stub: about 200 must come from people who never saw the templates
    assert all(line["source"] == "stub-claude" for line in lines)
    for line in lines:
        for name, gold in line["findings"].items():
            assert S(name).value.startswith("symptom_")
            assert gold["negated"] == (gold["severity"] == 0)


# ---- the trainer -----------------------------------------------------------------------


def test_trainer_is_deterministic(tmp_path):
    pytest.importorskip("sklearn")
    from orbit.learning.train_text import train

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    doc = train(seed=2, n=400, out=a)
    train(seed=2, n=400, out=b)
    assert a.read_bytes() == b.read_bytes()
    assert doc["version"] == "text-s2-n400"
    module = TextLinearExtractor(weights_path=str(a))
    assert module.read("I am so tired")  # a small model still finds plain fatigue


@pytest.mark.parametrize("seed", sorted(HELD_OUT_SEEDS))
def test_trainer_refuses_the_held_out_seeds(seed, tmp_path):
    pytest.importorskip("sklearn")
    from orbit.learning import train_text

    out = tmp_path / "w.json"
    with pytest.raises(ValueError, match="held out"):
        train_text.train(seed=seed, n=50, out=out)
    with pytest.raises(SystemExit) as stop:
        train_text.main(["--seed", str(seed), "--n", "50", "--out", str(out)])
    assert stop.value.code == 2  # argparse error
    assert not out.exists()


def test_shipped_weights_match_the_trainer_arguments():
    doc = json.loads(DEFAULT_WEIGHTS.read_text(encoding="utf-8"))
    assert doc["version"] == "text-s1-n4000"
    assert doc["trained_on"]["simulated"] is True
    assert DEFAULT_WEIGHTS.read_bytes().count(b"\r\n") == 0  # LF line ends
