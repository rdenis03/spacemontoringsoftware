"""M15 symptom extractor ``lexicon`` and its library (task B23, step 3)."""

import pytest
from conftest import ROOT

from orbit.modules.extractor import (
    LexiconEntry,
    LexiconExtractor,
    is_negated,
    parse_duration,
    tokenize,
)
from orbit.schema import SchemaError, SignalType

S = SignalType
LEXICON = ROOT / "cards" / "symptom_lexicon.jsonl"
WORKED_EXAMPLE = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."


@pytest.fixture(scope="module")
def extractor():
    return LexiconExtractor(lexicon_path=str(LEXICON))


def by_signal(findings):
    return {f.signal: f for f in findings if f.signal is not None}


def test_worked_example(extractor):
    findings = extractor.read(WORKED_EXAMPLE)
    assert [f.signal for f in findings] == [S.SYMPTOM_RASH_TINGLING, S.SYMPTOM_FATIGUE]
    rash, fatigue = findings
    assert rash.severity is None and not rash.negated
    assert rash.body_site == "ribs" and rash.onset_hours == 12
    assert rash.evidence == ("burning", "tingly patch")
    assert fatigue.severity == 2 and fatigue.evidence == ("Pretty wiped out",)
    assert fatigue.body_site is None and fatigue.onset_hours is None  # "ribs" is the rash's


def test_built_in_lexicon_reads_the_worked_example_too():
    assert LexiconExtractor().read(WORKED_EXAMPLE) == LexiconExtractor(str(LEXICON)).read(WORKED_EXAMPLE)


@pytest.mark.parametrize("text, negated, positive", [
    ("Fever since yesterday, no sore throat", [S.SYMPTOM_SORE_THROAT], [S.SYMPTOM_FEVER_CHILLS]),
    ("No fever or chills, but a really bad headache", [S.SYMPTOM_FEVER_CHILLS], [S.SYMPTOM_HEADACHE]),
    ("I don't have a sore throat, just tired", [S.SYMPTOM_SORE_THROAT], [S.SYMPTOM_FATIGUE]),
    ("Without any rash, just a headache", [S.SYMPTOM_RASH_TINGLING], [S.SYMPTOM_HEADACHE]),
    ("Not tired, but muscle aches", [S.SYMPTOM_FATIGUE], [S.SYMPTOM_MUSCLE_ACHES]),
    ("Not tired and no muscle aches", [S.SYMPTOM_FATIGUE, S.SYMPTOM_MUSCLE_ACHES], []),
    ("No fever this morning, but now chills", [], [S.SYMPTOM_FEVER_CHILLS]),
])
def test_negation(extractor, text, negated, positive):
    found = by_signal(extractor.read(text))
    for signal in negated:
        assert found[signal].negated and found[signal].severity == 0, (text, signal)
    for signal in positive:
        assert not found[signal].negated, (text, signal)


def test_a_cue_three_words_away_is_too_far(extractor):
    # "never" is 4 words before "headache": "Never had one like this headache" stays a headache
    assert not by_signal(extractor.read("Never had one like this headache"))[S.SYMPTOM_HEADACHE].negated
    assert by_signal(extractor.read("Never had a headache"))[S.SYMPTOM_HEADACHE].negated


@pytest.mark.parametrize("text, severity", [
    ("a bit tired", 1), ("slightly achy", 1), ("quite tired", 2), ("pretty sore throat", 2),
    ("severe headache", 3), ("my headache is really bad", 3), ("tired", None),
    ("tired, really bad", None),  # punctuation ends the search
])
def test_severity_words(extractor, text, severity):
    [finding] = extractor.read(text)
    assert finding.severity == severity


def test_complaints_outside_the_8_signals_are_kept(extractor):
    findings = extractor.read("A bit of nausea and I feel dizzy. Blurry vision, a stuffy nose "
                              "and my back hurts. No cough.")
    others = {f.label: f for f in findings if f.signal is None}
    assert set(others) == {"Nausea", "Dizziness", "Blurry vision", "Congestion", "Back pain", "Cough"}
    assert others["Nausea"].severity == 1
    assert others["Cough"].negated and not others["Back pain"].negated
    assert not by_signal(findings), "none of these is one of the 8 signals"


def test_body_site_and_side_go_to_the_nearest_finding(extractor):
    [rash] = extractor.read("Tingling on my left side, near my eye.")
    assert rash.side == "left" and rash.body_site == "eye"
    findings = by_signal(extractor.read("Headache all day. A rash on my back, one side only."))
    assert findings[S.SYMPTOM_HEADACHE].body_site is None
    assert findings[S.SYMPTOM_RASH_TINGLING].body_site == "back"
    assert findings[S.SYMPTOM_RASH_TINGLING].side == "one_side"
    # "throat" inside "sore throat" is not a body site of the next finding
    assert by_signal(extractor.read("sore throat and a rash"))[S.SYMPTOM_RASH_TINGLING].body_site is None


def test_several_mentions_make_one_finding(extractor):
    [rash] = extractor.read("A rash, tingling and a burning patch")
    assert rash.signal is S.SYMPTOM_RASH_TINGLING
    assert rash.evidence == ("rash", "tingling", "burning patch")


def test_evidence_is_always_a_slice_of_the_text(extractor):
    text = "Pretty WIPED OUT, kind of achy… and a SEVERE headache since this morning!"
    findings = extractor.read(text)
    assert {f.signal for f in findings} == {S.SYMPTOM_FATIGUE, S.SYMPTOM_MUSCLE_ACHES, S.SYMPTOM_HEADACHE}
    assert all(e in text for f in findings for e in f.evidence)
    assert by_signal(findings)[S.SYMPTOM_HEADACHE].onset_hours == 4


def test_long_reports_extract_without_errors(extractor):
    report_244 = "I feel pretty " + "x" * 218 + " tired today"
    assert len(report_244) == 244
    [fatigue] = extractor.read(report_244)
    assert fatigue.severity == 2 and len(fatigue.evidence[0]) <= 200
    assert fatigue.evidence[0] in report_244 and fatigue.evidence[0].startswith("pretty")

    chunk = "Really " + "y" * 120 + " bad headache, a bit " + "z" * 150 + " achy and pretty tired. "
    report_1000 = (chunk * 4)[:1000]
    assert len(report_1000) == 1000
    findings = extractor.read(report_1000)
    assert findings and all(len(e) <= 200 and e in report_1000 for f in findings for e in f.evidence)


@pytest.mark.parametrize("text, hours", [
    ("since last night", 12), ("since this morning", 4), ("since yesterday", 24),
    ("for 3 days", 72), ("for two days", 48), ("a few hours ago", 3), ("for a week", 168),
    ("2 days ago, then since last night", 48), ("all good", None),
])
def test_parse_duration(text, hours):
    assert parse_duration(text) == hours


def test_is_negated_helper():
    words = [t.text for t in tokenize("No fever, but chills and no aches")]
    assert words == ["no", "fever", ",", "but", "chills", "and", "no", "aches"]
    assert is_negated(words, 1) and not is_negated(words, 4) and is_negated(words, 7)
    assert not is_negated(words, 0)


def test_tokens_keep_their_place_in_the_text():
    text = "I can’t sleep. Tired!"
    tokens = tokenize(text)
    assert [t.text for t in tokens] == ["i", "can't", "sleep", ".", "tired", "!"]
    assert [text[t.start:t.end] for t in tokens][1] == "can’t"


def test_library_is_checked_on_load(tmp_path):
    clash = tmp_path / "clash.jsonl"
    clash.write_text(
        '{"kind":"symptom","signal":"symptom_fatigue","phrases":["tired"]}\n'
        '{"kind":"symptom","signal":"symptom_headache","phrases":["tired"]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="'tired' means both"):
        LexiconExtractor(lexicon_path=str(clash))

    not_symptom = tmp_path / "vital.jsonl"
    not_symptom.write_text('{"kind":"symptom","signal":"skin_temp","phrases":["hot"]}\n', encoding="utf-8")
    with pytest.raises(SchemaError, match="not a symptom signal"):
        LexiconExtractor(lexicon_path=str(not_symptom))

    for bad in ({"kind": "severity", "phrases": ["very"]},  # no level
                {"kind": "negation", "phrases": ["not at all"]},  # one word only
                {"kind": "other", "label": "X", "phrases": ["a, b"]}):  # punctuation
        with pytest.raises(ValueError):
            LexiconEntry.model_validate(bad)


def test_shipped_lexicon_covers_every_symptom_signal(extractor):
    signals = {signal for signal, _ in extractor.lexicon.mentions.values() if signal is not None}
    assert signals == {s for s in SignalType if s.value.startswith("symptom_")}
