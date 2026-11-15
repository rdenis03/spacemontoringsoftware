"""Symptom extractor ``text_linear`` (slot ``extractor``, team module M15, task B24).

The learned version of the ``lexicon`` extractor. A small linear text model
reads each clause of the astronaut's words and says which of the 8 symptom
signals it mentions and how strongly. No machine-learning library at run
time: it adds up weights from a JSON file, so it runs offline and is
deterministic. ``orbit/learning/train_text.py`` writes the weights.

How it reads "Weird burning, tingly patch on my ribs since last night.
Pretty wiped out too.":

1. **Clauses.** ``tokenize`` (shared with ``lexicon``) gives words and
   punctuation; punctuation and "but", "though", "however" ... end a clause
   ("and" does not: "hot and cold" is one phrase).
2. **Features** of a clause (``features``): every word (``w:wiped``), every
   pair of neighbouring words (``w:wiped out``) and the 3- to 5-letter pieces
   of each word padded with spaces (``c: wip``, ``c:iped``), so "tingle" and
   "tingly" share most of their features. Each feature counts once.
3. **One logistic regression per symptom signal**: probability =
   sigmoid(bias + sum of the weights of the clause's features). A clause
   mentions the signal when that reaches ``threshold`` (default: the file's,
   0.5).
4. **Where in the clause.** Each word's share of the score (its own word and
   letter features, half of each word pair it is in); the words with at least
   ``ANCHOR_SHARE`` of the best word's share are the mention.
5. **Negation** reuses ``is_negated`` from ``lexicon`` (a cue such as "no" or
   "don't" within 3 words before the mention, not across "and", "but" or
   punctuation). Anchors split by "and" are separate mentions, each checked
   on its own; if any is positive, so is the finding (as in ``lexicon``):
   "No rash and a burning patch." is a positive rash, read from "a burning
   patch". A denied symptom has ``negated=True`` and severity 0.
6. **Severity head**: one more linear model per level (not said, 1, 2, 3)
   on the words around the mention (up to 3 before and after, inside the
   clause, not across "and"); the highest score wins.
7. **Evidence** is that window, a slice of the original text. If the window
   is over 200 characters (a very long word), it falls back to the mention's
   own words, and any span is cut to 200 characters at a word boundary
   (``_cap``, the B23 fix), so it is always a substring of the text.
8. **Everything else comes from the lexicon**: onset (``parse_duration`` per
   sentence), body site and side (nearest finding in the sentence), and
   complaints outside the 8 signals (nausea, chest pain ...) as findings with
   ``signal=None``, never dropped.

Weights file (JSON; default ``orbit/learning/text_weights.json``)::

    {
      "version": "text-s1-n4000",        # model_version part: "text_linear-text-s1-n4000"
      "threshold": 0.5,
      "signals": {"symptom_fatigue": {"bias": -4.1, "weights": {"w:tired": 5.2, ...}}, ...},
      "severity": {"0": {"bias": ..., "weights": {...}}, "1": ..., "2": ..., "3": ...},
      "trained_on": {...}, "notes": "..."
    }

``signals`` must have exactly the 8 symptom signals; severity levels are "0"
(not said) to "3". Anything else raises ``ValueError`` on load.

Options:
    weights_path: the weights JSON. Default: the shipped file.
    lexicon_path: lexicon for onsets, body sites, sides and other complaints
        (``cards/symptom_lexicon.jsonl``). Default: ``lexicon``'s small built-in one.
    threshold: override the file's probability threshold (0 to 1).

Pure: no clock, no I/O after loading, same text gives the same findings.

Evaluation (B24; ``reports/triage_eval.json``, README *Results*, SPEC M15) on
``tests/fixtures/triage/human_sentences.jsonl``, weights ``text-s1-n4000``:

                                  lexicon   text_linear
    macro F1 of "present"         0.957     0.964
    negation accuracy             0.906     0.938
    severity within one level     0.875     0.875
    red-flag recall               1.00      1.00     (the gate runs before any model)

**Provisional.** That file is a 20-line stub written by the same author as the
templates, not by people who never saw them, so it cannot show how the model
does on real astronauts' words. ``text_linear`` passes the switch rule on it,
but no switch is recommended until about 200 independent sentences exist.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import SignalCategory, SignalType, SymptomFinding, SymptomReport, get_spec

from .extractor import (
    EVIDENCE_LIMIT,
    PUNCTUATION,
    SENTENCE_ENDS,
    WINDOW,
    LexiconExtractor,
    _cap,
    _match,
    _Mention,
    is_negated,
    tokenize,
)

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[1] / "learning" / "text_weights.json"
CLAUSE_BREAKERS = frozenset({"but", "though", "although", "however", "yet", "except"})
"""Words that end a clause (with punctuation). Not "and": "hot and cold" is one phrase."""
ANCHOR_SHARE = 0.3
"""A word is part of the mention if its share of the score is at least this part of the best word's."""
CHAR_SIZES = (3, 4, 5)
SEVERITY_LEVELS = ("0", "1", "2", "3")  # "0" = not said
SYMPTOM_SIGNALS = tuple(s for s in SignalType if get_spec(s).category is SignalCategory.SYMPTOM)


# ---- features (shared with orbit/learning/train_text.py) -------------------------------


def word_features(words: Sequence[str], i: int) -> list[str]:
    """The word and letter features of ``words[i]`` (no word pairs)."""
    word = words[i]
    padded = f" {word} "
    out = [f"w:{word}"]
    for n in CHAR_SIZES:
        out += [f"c:{padded[k:k + n]}" for k in range(len(padded) - n + 1)]
    return out


def features(words: Sequence[str]) -> set[str]:
    """Every feature of a clause: words, neighbouring word pairs, 3-5 letter pieces."""
    out: set[str] = set()
    for i in range(len(words)):
        out.update(word_features(words, i))
        if i + 1 < len(words):
            out.add(f"w:{words[i]} {words[i + 1]}")
    return out


def clauses(words: Sequence[str]) -> list[tuple[int, int]]:
    """Token ranges [start, end) of the clauses, split at punctuation and CLAUSE_BREAKERS."""
    out, start = [], 0
    for i, word in enumerate(words):
        if word in PUNCTUATION or word in CLAUSE_BREAKERS:
            if i > start:
                out.append((start, i))
            start = i + 1
    if len(words) > start:
        out.append((start, len(words)))
    return out


def mention_window(words: Sequence[str], start: int, end: int, lo: int, hi: int,
                   breakers: frozenset[str]) -> tuple[int, int]:
    """Up to WINDOW words before and after [start, end), inside [lo, hi), not across a breaker."""
    a = start
    while a > lo and start - a < WINDOW and words[a - 1] not in breakers \
            and words[a - 1] not in PUNCTUATION:
        a -= 1
    b = end
    while b < hi and b - end < WINDOW and words[b] not in breakers and words[b] not in PUNCTUATION:
        b += 1
    return a, b


# ---- the weights -------------------------------------------------------------------


@dataclass(frozen=True)
class Linear:
    """bias + sum of weights of the features present."""

    bias: float
    weights: dict[str, float]

    def score(self, feats: set[str]) -> float:
        get = self.weights.get
        return self.bias + sum(get(f, 0.0) for f in feats)

    def word_share(self, words: Sequence[str], i: int) -> float:
        get = self.weights.get
        share = sum(get(f, 0.0) for f in set(word_features(words, i)))
        if i > 0:
            share += 0.5 * get(f"w:{words[i - 1]} {words[i]}", 0.0)
        if i + 1 < len(words):
            share += 0.5 * get(f"w:{words[i]} {words[i + 1]}", 0.0)
        return share


def _linear(raw: Any, where: str) -> Linear:
    if not isinstance(raw, dict) or set(raw) != {"bias", "weights"}:
        raise ValueError(f"{where}: needs exactly 'bias' and 'weights'")
    bias, weights = raw["bias"], raw["weights"]
    if not isinstance(bias, (int, float)) or not math.isfinite(bias):
        raise ValueError(f"{where}: bias must be a number")
    if not isinstance(weights, dict) or not all(
            isinstance(k, str) and k[:2] in ("w:", "c:") and isinstance(v, (int, float))
            and math.isfinite(v) for k, v in weights.items()):
        raise ValueError(f"{where}: weights must map 'w:' or 'c:' features to numbers")
    return Linear(float(bias), {k: float(v) for k, v in weights.items()})


def load_text_weights(path: str | Path) -> tuple[str, float, dict[SignalType, Linear], dict[str, Linear]]:
    """(version, threshold, per-signal models, severity models); ValueError if malformed."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    version, threshold = doc.get("version"), doc.get("threshold")
    if not isinstance(version, str) or not version:
        raise ValueError("text weights: 'version' must be a non-empty string")
    if not isinstance(threshold, (int, float)) or not 0 < threshold < 1:
        raise ValueError("text weights: 'threshold' must be between 0 and 1")
    signals: dict[SignalType, Linear] = {}
    for name, raw in (doc.get("signals") or {}).items():
        try:
            signal = SignalType(name)
        except ValueError:
            raise ValueError(f"text weights: unknown signal {name!r}") from None
        if get_spec(signal).category is not SignalCategory.SYMPTOM:
            raise ValueError(f"text weights: {name} is not a symptom signal")
        signals[signal] = _linear(raw, f"text weights: {name}")
    missing = [s.value for s in SYMPTOM_SIGNALS if s not in signals]
    if missing:  # a missing head would silently turn off that symptom and its screening
        raise ValueError(f"text weights: missing symptom signals {missing}; "
                         "every one of the 8 needs a model")
    severity_raw = doc.get("severity") or {}
    if set(severity_raw) != set(SEVERITY_LEVELS):
        raise ValueError(f"text weights: severity needs levels {list(SEVERITY_LEVELS)}")
    severity = {lvl: _linear(severity_raw[lvl], f"text weights: severity {lvl}")
                for lvl in SEVERITY_LEVELS}
    return version, float(threshold), signals, severity


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


# ---- the extractor -----------------------------------------------------------------


@register("extractor", "text_linear")
class TextLinearExtractor:
    def __init__(self, weights_path: str | None = None, lexicon_path: str | None = None,
                 threshold: float | None = None):
        version, file_threshold, self.signals, self.severity = load_text_weights(
            weights_path or DEFAULT_WEIGHTS)
        if threshold is not None and not 0 < threshold < 1:
            raise ValueError("threshold must be between 0 and 1")
        self.threshold = file_threshold if threshold is None else threshold
        self.weights_version = version
        self.version = f"text_linear-{version}"[:40]
        self._lexicon_reader = LexiconExtractor(lexicon_path)
        self.lexicon = self._lexicon_reader.lexicon

    def extract(self, report: SymptomReport, ctx: AssessmentContext) -> list[SymptomFinding]:
        return self.read(report.text)

    def read(self, text: str) -> list[SymptomFinding]:
        """The findings in one text (``extract`` without the report around it)."""
        lex = self.lexicon
        tokens = tokenize(text)
        words = [t.text for t in tokens]
        if not words:
            return []
        breakers = lex.breakers | CLAUSE_BREAKERS
        sentence_of, sentence = [], 0
        for word in words:
            sentence_of.append(sentence)
            sentence += word in SENTENCE_ENDS

        mentions: list[tuple[_Mention, float]] = []
        for lo, hi in clauses(words):
            clause = words[lo:hi]
            feats = features(clause)
            for signal, model in self.signals.items():
                p = _sigmoid(model.score(feats))
                if p < self.threshold:
                    continue
                shares = [model.word_share(clause, i) for i in range(len(clause))]
                best = max(shares)
                picked = [i for i, s in enumerate(shares) if best > 0 and s >= ANCHOR_SHARE * best] \
                    or list(range(len(clause)))
                # One mention per run of anchors not split by "and" (a scope breaker), each
                # with its own negation: in "no rash and a burning patch" the patch is positive.
                runs = [[picked[0]]]
                for i in picked[1:]:
                    if any(w in lex.breakers for w in clause[runs[-1][-1] + 1:i]):
                        runs.append([i])
                    else:
                        runs[-1].append(i)
                denied = [is_negated(words, lo + r[0], cues=lex.negation, breakers=lex.breakers)
                          for r in runs]
                negated = all(denied)
                kept = runs if negated else [r for r, d in zip(runs, denied) if not d]
                start, end = lo + kept[0][0], lo + kept[-1][-1] + 1
                a, b = mention_window(words, start, end, lo, hi, breakers)
                level = None if negated else self._severity(words[a:b])
                evidence = text[tokens[a].start:tokens[b - 1].end]
                if len(evidence) > EVIDENCE_LIMIT:  # keep the mention's own words, then cap
                    evidence = text[tokens[start].start:tokens[end - 1].end]
                mentions.append((_Mention(
                    start, end, signal, get_spec(signal).label, negated, level,
                    evidence=_cap(evidence),
                    sentence=sentence_of[start], multi_word=end - start > 1), p))

        plain = [m for m, _ in mentions]
        covered = {i for m in plain for i in range(m.start, m.end)}
        sites = LexiconExtractor._assign(_match(words, lex.body_sites), plain, covered, sentence_of)
        sides = LexiconExtractor._assign(_match(words, lex.sides), plain, covered, sentence_of)
        onsets = LexiconExtractor._onsets(text, tokens, sentence_of)

        groups: dict[SignalType, list[tuple[_Mention, float]]] = {}
        for m, p in sorted(mentions, key=lambda item: item[0].start):
            groups.setdefault(m.signal, []).append((m, p))
        findings = []
        for signal, group in groups.items():
            positive = [m for m, _ in group if not m.negated]
            negated = not positive
            levels = [m.severity for m in positive if m.severity is not None]
            findings.append(SymptomFinding(
                signal=signal,
                label=group[0][0].label,
                severity=0 if negated else (max(levels) if levels else None),
                negated=negated,
                confidence=round(max(p for _, p in group), 3),
                evidence=tuple(dict.fromkeys(m.evidence for m, _ in group)),
                onset_hours=next((onsets[m.sentence] for m in positive
                                  if onsets.get(m.sentence) is not None), None),
                body_site=next((sites[id(m)] for m in positive if id(m) in sites), None),
                side=next((sides[id(m)] for m in positive if id(m) in sides), None),
            ))
        # Complaints outside the 8 signals come from the lexicon, never dropped.
        findings += [f for f in self._lexicon_reader.read(text) if f.signal is None]
        return findings

    def _severity(self, window: Sequence[str]) -> int | None:
        feats = features(window)
        scores = {lvl: model.score(feats) for lvl, model in self.severity.items()}
        best = max(SEVERITY_LEVELS, key=lambda lvl: (scores[lvl], -int(lvl)))
        return None if best == "0" else int(best)
