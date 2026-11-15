"""Training sentences for the ``text_linear`` extractor (M15, task B24).

Two sources, both with labels:

* ``generate(n, seed)``: seeded template sentences built from the hand-written
  lexicon (``cards/symptom_lexicon.jsonl``): 1 to 3 clauses, each a symptom
  phrase (with or without a severity word, sometimes denied: "no fever",
  "I don't have a headache"), a complaint outside the 8 signals, or filler
  ("otherwise fine"). Every symptom mention keeps its character span, so the
  trainer knows which clause and which words it is in.
* ``load_extra()``: hand-written paraphrases in ``utterances_extra.jsonl``
  (one clause each, words the lexicon does not have: "I feel like a zombie").

Same seed, same sentences. ``tests/fixtures/triage/human_sentences.jsonl`` is
never used here: it is the test set. The sentences are illustrative.

Extra file format, one JSON object per line::

    {"text": "my whole body is aching", "labels": {"symptom_muscle_aches": {"severity": null, "negated": false}}}

``labels`` may be empty (a sentence with no symptom).
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from orbit.schema import SignalType, parse_jsonl

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEXICON = ROOT / "cards" / "symptom_lexicon.jsonl"
DEFAULT_EXTRA = Path(__file__).resolve().parent / "utterances_extra.jsonl"

OPENERS = ("", "", "", "I feel ", "I'm feeling ", "I have ", "I've got ", "got ", "woke up with ",
           "feeling ", "having ", "there's some ", "I noticed ", "still ", "honestly ", "today ",
           "since the spacewalk ")
NEGATED = ("no {p}", "not {p}", "without {p}", "I don't have {p}", "I don't have any {p}",
           "never had {p}", "no {p} at all", "I haven't got {p}", "there's no {p}", "not really {p}",
           "didn't get {p}")
TAILS = ("", "", "", " since last night", " since this morning", " for two days", " for a few days",
         " since yesterday", " today", " on my left side", " on my ribs", " on one side",
         " around my waist", " this morning", " after the workout", " all day")
FILLERS = ("otherwise fine", "slept okay", "work was busy", "feeling fine", "nothing else",
           "all good otherwise", "the experiment went well", "ate normally", "had a good workout",
           "mood is okay", "just checking in", "the view is amazing today", "a long day of tasks",
           "talked to family", "no other complaints", "everything else is normal")
SEPARATORS = (", ", ", ", ". ", " and ", " but ", "; ", " plus ", " also ", ", and ")
ENDINGS = (".", ".", ".", "!", "")


@dataclass(frozen=True)
class Mention:
    """One symptom in a generated sentence: its character span covers the phrase and any severity word."""

    signal: SignalType
    negated: bool
    severity: int | None
    start: int
    end: int


@dataclass(frozen=True)
class Utterance:
    text: str
    mentions: tuple[Mention, ...]  # empty for hand-written extras (one clause each)
    labels: dict[SignalType, tuple[bool, int | None]]  # signal -> (negated, severity)
    source: str  # "template" or "extra"


@dataclass
class _Lexicon:
    symptoms: dict[SignalType, list[str]]
    others: list[str]
    severity: dict[int, list[str]]


def _load_lexicon(path: str | Path) -> _Lexicon:
    from orbit.modules.extractor import LexiconEntry  # orbit.learning is never imported by modules

    entries = parse_jsonl(path, LexiconEntry).raise_if_errors()
    lex = _Lexicon({}, [], {})
    for e in entries:
        if e.kind == "symptom":
            lex.symptoms.setdefault(e.signal, []).extend(e.phrases)
        elif e.kind == "other":
            lex.others.extend(e.phrases)
        elif e.kind == "severity":
            lex.severity.setdefault(e.level, []).extend(e.phrases)
    return lex


def _merge(mentions: Sequence[Mention]) -> dict[SignalType, tuple[bool, int | None]]:
    """Per signal, like the extractors: denied only if every mention is denied; strongest severity."""
    out: dict[SignalType, tuple[bool, int | None]] = {}
    for signal in dict.fromkeys(m.signal for m in mentions):
        group = [m for m in mentions if m.signal is signal]
        positive = [m for m in group if not m.negated]
        levels = [m.severity for m in positive if m.severity is not None]
        out[signal] = (not positive, 0 if not positive else (max(levels) if levels else None))
    return out


def generate(n: int, seed: int = 1, lexicon_path: str | Path = DEFAULT_LEXICON) -> list[Utterance]:
    """``n`` labelled template sentences; the same seed gives the same sentences."""
    lex = _load_lexicon(lexicon_path)
    rng = random.Random(seed)
    signals = sorted(lex.symptoms, key=lambda s: s.value)
    out: list[Utterance] = []
    for _ in range(n):
        text, mentions = "", []
        for k in range(rng.choice((1, 1, 2, 2, 2, 3))):
            if k:
                text += rng.choice(SEPARATORS)
            roll = rng.random()
            if roll < 0.75:
                signal = rng.choice(signals)
                phrase = rng.choice(lex.symptoms[signal])
                if rng.random() < 0.25:
                    template = rng.choice(NEGATED)
                    clause = template.format(p=phrase)
                    offset = len(text) + template.index("{p}")
                    mentions.append(Mention(signal, True, None, offset, offset + len(phrase)))
                    text += clause
                else:
                    level = rng.choice((None, None, 1, 2, 3))
                    opener = rng.choice(OPENERS)
                    if level is None:
                        body, rel = phrase, 0
                    elif rng.random() < 0.85:
                        body, rel = f"{rng.choice(lex.severity[level])} {phrase}", 0
                    else:
                        body, rel = f"{phrase} {rng.choice(lex.severity[level])}", 0
                    start = len(text) + len(opener) + rel
                    mentions.append(Mention(signal, False, level, start, start + len(body)))
                    text += opener + body
                text += rng.choice(TAILS)
            elif roll < 0.87:
                text += rng.choice(OPENERS) + rng.choice(lex.others) + rng.choice(TAILS)
            else:
                text += rng.choice(FILLERS)
        text += rng.choice(ENDINGS)
        if text[:1].isalpha() and rng.random() < 0.7:
            text = text[0].upper() + text[1:]  # same length, spans stay valid
        out.append(Utterance(text, tuple(mentions), _merge(mentions), "template"))
    return out


_LEXICONS: dict[str, _Lexicon] = {}


def describe(levels: dict[SignalType, int], rng: random.Random,
             lexicon_path: str | Path = DEFAULT_LEXICON, unrated_share: float = 0.4) -> str:
    """A chat message for a simulated day (B24 evaluation): its symptoms in the lexicon's words.

    Each symptom above 0 gets a phrase; with chance ``unrated_share`` no severity
    word, so the reasoner has a severity to ask. A day without symptoms describes a
    complaint outside the 8 signals ("a bit dizzy").
    """
    key = str(lexicon_path)
    if key not in _LEXICONS:
        _LEXICONS[key] = _load_lexicon(lexicon_path)
    lex = _LEXICONS[key]
    parts = []
    for signal in sorted((s for s, v in levels.items() if v > 0), key=lambda s: s.value):
        phrase = rng.choice(lex.symptoms[signal])
        if rng.random() >= unrated_share:
            phrase = f"{rng.choice(lex.severity[levels[signal]])} {phrase}"
        parts.append(phrase)
    if not parts:
        parts.append(rng.choice(lex.others))
    rng.shuffle(parts)
    text = rng.choice(("I feel ", "I have ", "")) + ", ".join(parts[:-1])
    text += (" and " if len(parts) > 1 else "") + parts[-1] + "."
    return text[0].upper() + text[1:]


def load_extra(path: str | Path = DEFAULT_EXTRA) -> list[Utterance]:
    """The hand-written paraphrases (one clause each)."""
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if set(raw) != {"text", "labels"} or not isinstance(raw["text"], str):
            raise ValueError(f"{path}:{n}: needs exactly 'text' and 'labels'")
        labels = {}
        for name, value in raw["labels"].items():
            severity = value.get("severity")
            if severity is not None and severity not in (1, 2, 3):
                raise ValueError(f"{path}:{n}: severity must be 1-3 or null")
            labels[SignalType(name)] = (bool(value.get("negated", False)),
                                        0 if value.get("negated") else severity)
        out.append(Utterance(raw["text"], (), labels, "extra"))
    return out
