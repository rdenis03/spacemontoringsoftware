"""Symptom extractor ``lexicon`` (slot ``extractor``, team module M15).

Turns the astronaut's own words into ``SymptomFinding``s for the 8 symptom
signals, with severity, negation, onset, body site and side. Complaints
outside the 8 signals (nausea, dizziness ...) become findings with
``signal=None`` so the medical officer still sees them; they are never dropped.

How it reads "Weird burning, tingly patch on my ribs since last night.
Pretty wiped out too.":

1. **Tokens.** Lower-case words and punctuation, each with its place in the
   text, so every ``evidence`` string is a slice of the original text.
2. **Phrases**, longest first, left to right: "tingly patch" and "burning"
   are rash or tingling, "wiped out" is fatigue. Several mentions of one
   signal become one finding.
3. **Severity words** within 3 words before or after a phrase: "a bit" 1,
   "pretty" or "quite" 2, "really bad" or "severe" 3 ("Pretty wiped out" =
   fatigue 2). Not said means ``severity=None``.
4. **Negation**: a cue (no, not, without, never, don't ...) within 3 words
   before the phrase, unless punctuation or a scope breaker ("but", "and")
   comes in between. A denied symptom has ``negated=True`` and severity 0.
5. **Onset**, per sentence: "since last night" about 12 h, "since this
   morning" 4 h, "since yesterday" 24 h, "for 2 days" 48 h.
6. **Body site and side**, given to the nearest finding in the same sentence
   ("ribs" goes to the rash, not to the fatigue).

The phrases live in a hand-written JSONL library (``cards/symptom_lexicon.jsonl``),
one record per line with a ``kind``: ``symptom`` (signal + phrases),
``other`` (label + phrases), ``severity`` (level 1-3 + phrases),
``negation``, ``scope_break``, ``body_site`` (label + phrases) and ``side``
(side + phrases). The file is checked when the module starts: a phrase may
mean only one thing. The words are illustrative, not clinical.

Options:
    lexicon_path: the JSONL library. Default: a small built-in lexicon that
        covers every signal, so the contract tests can build the module.

Pure: no clock, no I/O after loading, same text gives the same findings.
The helpers ``tokenize``, ``is_negated`` and ``parse_duration`` are shared
with the learned text model (B24).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import (
    SignalCategory,
    SignalType,
    SymptomFinding,
    SymptomReport,
    get_spec,
    parse_jsonl,
    parse_records,
)

PUNCTUATION = frozenset(".,;:!?")
SENTENCE_ENDS = frozenset(".!?;")
WINDOW = 3
"""Words looked at before (negation, severity) or after (severity) a phrase."""

NEGATION_CUES = frozenset({
    "no", "not", "without", "never", "none", "nor", "don't", "dont", "doesn't", "doesnt",
    "didn't", "didnt", "haven't", "havent", "hasn't", "hasnt", "isn't", "isnt", "wasn't",
    "wasnt", "aren't", "arent",
})
SCOPE_BREAKERS = frozenset({"but", "and", "though", "although", "however", "yet", "except"})
EVIDENCE_LIMIT = 200
"""Longest evidence string a ``SymptomFinding`` accepts; longer spans are cut at a word boundary."""


def _cap(span: str, limit: int = EVIDENCE_LIMIT) -> str:
    """The span, or its start cut at the last space within ``limit`` (still a slice of the text)."""
    if len(span) <= limit:
        return span
    head = span[:limit]
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else head).rstrip()

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[.,;:!?]")


# ---- shared text helpers (also used by B24's text model) ------------------------------


@dataclass(frozen=True)
class Token:
    text: str  # lower case
    start: int  # position in the original text
    end: int


def _normalise(text: str) -> str:
    """Lower case with plain apostrophes, keeping every character in place."""
    lowered = "".join(low if len(low := ch.lower()) == 1 else ch for ch in text)
    return lowered.replace("’", "'").replace("‘", "'")


def tokenize(text: str) -> list[Token]:
    """Words and punctuation marks, lower case, with their place in ``text``."""
    return [Token(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(_normalise(text))]


def is_negated(
    tokens: Sequence[str | Token],
    index: int,
    *,
    cues: frozenset[str] = NEGATION_CUES,
    breakers: frozenset[str] = SCOPE_BREAKERS,
    window: int = WINDOW,
) -> bool:
    """True if a negation cue is within ``window`` words before ``tokens[index]``.

    Punctuation or a scope breaker ("but", "and") ends the search: in "no
    fever, but a sore throat" the throat is not negated.
    """
    seen = 0
    for i in range(index - 1, -1, -1):
        word = tokens[i] if isinstance(tokens[i], str) else tokens[i].text
        if word in PUNCTUATION or word in breakers:
            return False
        if word in cues:
            return True
        seen += 1
        if seen >= window:
            return False
    return False


_COUNT = (r"(\d+|a couple of|a few|few|several|an?|one|two|three|four|five|six|seven|eight|nine|ten)"
          r"\s+(hours?|days?|nights?|weeks?)")
_COUNT_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a couple of": 2, "a few": 3,
                "few": 3, "several": 3}
_UNIT_HOURS = {"hour": 1, "day": 24, "night": 24, "week": 168}
_SPANS = (
    re.compile(rf"\bfor (?:about |around |nearly |almost |the (?:last|past) )?{_COUNT}\b"),
    re.compile(rf"\b{_COUNT} ago\b"),
    re.compile(rf"\b(?:the )?(?:last|past) {_COUNT}\b"),
)
_FIXED = (
    (re.compile(r"\b(?:since |from )?last night\b|\bovernight\b"), 12.0),
    (re.compile(r"\b(?:since |from )?(?:early )?this morning\b|\bsince (?:i )?woke up\b|\bsince waking\b"), 4.0),
    (re.compile(r"\b(?:since |from )?yesterday\b"), 24.0),
    (re.compile(r"\b(?:since |from )?(?:this|today) afternoon\b"), 2.0),
)


def parse_duration(text: str) -> float | None:
    """How many hours ago something started, from words like 'since last night'.

    The first duration in the text wins. Fixed phrases are rough: "since
    last night" 12 h, "since this morning" 4 h, "since yesterday" 24 h;
    "for 3 days" or "2 days ago" count exactly. None if no duration is said.
    """
    lowered = _normalise(text)
    found: list[tuple[int, float]] = []
    for pattern in _SPANS:
        for m in pattern.finditer(lowered):
            count, unit = m.group(1), m.group(2).rstrip("s")
            number = float(count) if count.isdigit() else float(_COUNT_WORDS[count])
            found.append((m.start(), number * _UNIT_HOURS[unit]))
    for pattern, hours in _FIXED:
        if m := pattern.search(lowered):
            found.append((m.start(), hours))
    return min(found)[1] if found else None


# ---- the lexicon --------------------------------------------------------------------


Kind = Literal["symptom", "other", "severity", "negation", "scope_break", "body_site", "side"]


class LexiconEntry(BaseModel):
    """One line of ``cards/symptom_lexicon.jsonl``."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: Kind
    phrases: tuple[str, ...] = Field(min_length=1)
    signal: SignalType | None = None  # kind symptom
    label: str | None = Field(default=None, max_length=80)  # kind other and body_site
    level: int | None = Field(default=None, ge=1, le=3)  # kind severity
    side: Literal["left", "right", "both", "one_side"] | None = None  # kind side

    @model_validator(mode="after")
    def _fields_for_kind(self) -> Self:
        need = {"symptom": "signal", "other": "label", "body_site": "label",
                "severity": "level", "side": "side"}.get(self.kind)
        if need and getattr(self, need) is None:
            raise ValueError(f"a '{self.kind}' entry needs '{need}'")
        if self.kind == "symptom" and get_spec(self.signal).category is not SignalCategory.SYMPTOM:
            raise ValueError(f"{self.signal.value} is not a symptom signal")
        for phrase in self.phrases:
            words = [t.text for t in tokenize(phrase)]
            if not words or any(w in PUNCTUATION for w in words):
                raise ValueError(f"phrase '{phrase}' must be words without punctuation")
            if self.kind in ("negation", "scope_break") and len(words) != 1:
                raise ValueError(f"'{self.kind}' phrases are single words; got '{phrase}'")
        return self


@dataclass(frozen=True)
class Lexicon:
    """The checked library, as lookup tables keyed by word tuples."""

    mentions: dict[tuple[str, ...], tuple[SignalType | None, str]]
    severity: dict[tuple[str, ...], int]
    body_sites: dict[tuple[str, ...], str]
    sides: dict[tuple[str, ...], str]
    negation: frozenset[str]
    breakers: frozenset[str]

    @classmethod
    def build(cls, entries: Sequence[LexiconEntry]) -> Lexicon:
        tables: dict[str, dict[tuple[str, ...], Any]] = {
            "mentions": {}, "severity": {}, "body_sites": {}, "sides": {}}
        negation: set[str] = set()
        breakers: set[str] = set()
        problems: list[str] = []
        for entry in entries:
            for phrase in entry.phrases:
                key = tuple(t.text for t in tokenize(phrase))
                if entry.kind == "negation":
                    negation.add(key[0])
                    continue
                if entry.kind == "scope_break":
                    breakers.add(key[0])
                    continue
                table, value = {
                    "symptom": ("mentions", (entry.signal, get_spec(entry.signal).label)
                                if entry.signal else None),
                    "other": ("mentions", (None, entry.label)),
                    "severity": ("severity", entry.level),
                    "body_site": ("body_sites", entry.label),
                    "side": ("sides", entry.side),
                }[entry.kind]
                old = tables[table].get(key)
                if old is not None and old != value:
                    problems.append(f"'{phrase}' means both {old} and {value}")
                tables[table][key] = value
        if problems:
            raise ValueError("symptom lexicon: " + "; ".join(problems))
        if not tables["mentions"]:
            raise ValueError("symptom lexicon: no symptom phrases")
        return cls(negation=frozenset(negation) or NEGATION_CUES,
                   breakers=frozenset(breakers) or SCOPE_BREAKERS, **tables)


BUILT_IN_LEXICON: tuple[dict[str, Any], ...] = (
    {"kind": "symptom", "signal": "symptom_fatigue", "phrases": ["tired", "exhausted", "fatigue", "wiped out", "worn out"]},
    {"kind": "symptom", "signal": "symptom_fever_chills", "phrases": ["fever", "feverish", "chills", "shivering"]},
    {"kind": "symptom", "signal": "symptom_sore_throat", "phrases": ["sore throat", "throat hurts"]},
    {"kind": "symptom", "signal": "symptom_swollen_glands", "phrases": ["swollen glands", "swollen neck"]},
    {"kind": "symptom", "signal": "symptom_mouth_sores", "phrases": ["mouth sores", "cold sore", "mouth ulcer"]},
    {"kind": "symptom", "signal": "symptom_rash_tingling", "phrases": ["rash", "tingling", "tingly patch", "burning"]},
    {"kind": "symptom", "signal": "symptom_headache", "phrases": ["headache", "head hurts"]},
    {"kind": "symptom", "signal": "symptom_muscle_aches", "phrases": ["muscle aches", "aching", "sore muscles"]},
    {"kind": "other", "label": "Nausea", "phrases": ["nausea", "nauseous", "queasy"]},
    {"kind": "other", "label": "Dizziness", "phrases": ["dizzy", "dizziness", "lightheaded"]},
    {"kind": "other", "label": "Blurry vision", "phrases": ["blurry vision", "blurred vision"]},
    {"kind": "other", "label": "Congestion", "phrases": ["congestion", "stuffy nose", "blocked nose"]},
    {"kind": "other", "label": "Back pain", "phrases": ["back pain", "backache"]},
    {"kind": "severity", "level": 1, "phrases": ["a bit", "a little", "slightly", "mild"]},
    {"kind": "severity", "level": 2, "phrases": ["pretty", "quite", "moderate"]},
    {"kind": "severity", "level": 3, "phrases": ["really bad", "severe", "terrible"]},
    {"kind": "negation", "phrases": ["no", "not", "without", "never", "don't", "dont"]},
    {"kind": "scope_break", "phrases": ["but", "and", "though", "however"]},
    {"kind": "body_site", "label": "ribs", "phrases": ["ribs", "rib"]},
    {"kind": "body_site", "label": "face", "phrases": ["face", "forehead"]},
    {"kind": "body_site", "label": "eye", "phrases": ["eye", "eyes"]},
    {"kind": "side", "side": "left", "phrases": ["left", "left side"]},
    {"kind": "side", "side": "right", "phrases": ["right side"]},
    {"kind": "side", "side": "one_side", "phrases": ["one side"]},
)
"""Small fallback lexicon. The full, hand-edited one is cards/symptom_lexicon.jsonl."""


# ---- the extractor ----------------------------------------------------------------------


@dataclass
class _Mention:
    start: int  # token index
    end: int  # token index after the phrase
    signal: SignalType | None
    label: str
    negated: bool
    severity: int | None
    evidence: str
    sentence: int
    multi_word: bool


def _match(words: list[str], table: dict[tuple[str, ...], Any]) -> list[tuple[int, int, Any]]:
    """Phrases from ``table`` in ``words``: longest first, left to right, no overlaps."""
    longest = max((len(k) for k in table), default=0)
    found, i = [], 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 0, -1):
            key = tuple(words[i:i + n])
            if key in table:
                found.append((i, i + n, table[key]))
                i += n
                break
        else:
            i += 1
    return found


@register("extractor", "lexicon")
class LexiconExtractor:
    version = "lexicon-0.1"

    def __init__(self, lexicon_path: str | None = None):
        entries = (parse_jsonl(lexicon_path, LexiconEntry) if lexicon_path
                   else parse_records(BUILT_IN_LEXICON, LexiconEntry)).raise_if_errors()
        self.lexicon = Lexicon.build(entries)

    def extract(self, report: SymptomReport, ctx: AssessmentContext) -> list[SymptomFinding]:
        return self.read(report.text)

    def read(self, text: str) -> list[SymptomFinding]:
        """The findings in one text (``extract`` without the report around it)."""
        lex = self.lexicon
        tokens = tokenize(text)
        words = [t.text for t in tokens]
        if not words:
            return []
        sentence_of, sentence = [], 0
        for word in words:
            sentence_of.append(sentence)
            sentence += word in SENTENCE_ENDS

        severities = _match(words, lex.severity)
        mentions: list[_Mention] = []
        for start, end, (signal, label) in _match(words, lex.mentions):
            negated = is_negated(words, start, cues=lex.negation, breakers=lex.breakers)
            level, first, last = None, start, end
            near = self._severity_near(words, start, end, severities)
            if near is not None and not negated:
                level, s_start, s_end = near
                first, last = min(first, s_start), max(last, s_end)
            mentions.append(_Mention(
                start, end, signal, label, negated, level,
                evidence=_cap(text[tokens[first].start:tokens[last - 1].end]),
                sentence=sentence_of[start], multi_word=end - start > 1))

        covered = {i for m in mentions for i in range(m.start, m.end)}
        sites = self._assign(_match(words, lex.body_sites), mentions, covered, sentence_of)
        sides = self._assign(_match(words, lex.sides), mentions, covered, sentence_of)
        onsets = self._onsets(text, tokens, sentence_of)

        groups: dict[Any, list[_Mention]] = {}
        for m in mentions:  # one finding per signal (or per label for other complaints)
            groups.setdefault(m.signal or m.label, []).append(m)
        findings = []
        for group in groups.values():
            positive = [m for m in group if not m.negated]
            negated = not positive
            levels = [m.severity for m in positive if m.severity is not None]
            evidence = tuple(dict.fromkeys(m.evidence for m in group))
            findings.append(SymptomFinding(
                signal=group[0].signal,
                label=group[0].label,
                severity=0 if negated else (max(levels) if levels else None),
                negated=negated,
                confidence=0.9 if any(m.multi_word for m in group) or levels else 0.75,
                evidence=evidence,
                onset_hours=next((onsets[m.sentence] for m in positive
                                  if onsets.get(m.sentence) is not None), None),
                body_site=next((sites[id(m)] for m in positive if id(m) in sites), None),
                side=next((sides[id(m)] for m in positive if id(m) in sides), None),
            ))
        return findings

    def _severity_near(self, words, start, end, severities) -> tuple[int, int, int] | None:
        """The closest severity phrase within WINDOW words, not across punctuation or 'but'."""
        best = None
        for s_start, s_end, level in severities:
            if s_end <= start:
                between, gap = words[s_end:start], start - s_end
            elif s_start >= end:
                between, gap = words[end:s_start], s_start - end
            else:
                continue
            if gap >= WINDOW or any(w in PUNCTUATION or w in self.lexicon.breakers for w in between):
                continue
            if best is None or gap < best[0]:
                best = (gap, level, s_start, s_end)
        return None if best is None else best[1:]

    @staticmethod
    def _assign(matches, mentions, covered, sentence_of) -> dict[int, str]:
        """Give each body site (or side) to the nearest non-negated mention in its sentence."""
        out: dict[int, str] = {}
        for start, end, value in matches:
            if any(i in covered for i in range(start, end)):
                continue  # "throat" inside "sore throat" is not a separate body site
            same = [m for m in mentions if not m.negated and m.sentence == sentence_of[start]]
            if not same:
                continue
            nearest = min(same, key=lambda m: start - m.end if start >= m.end else m.start - end)
            out.setdefault(id(nearest), value)
        return out

    @staticmethod
    def _onsets(text: str, tokens: list[Token], sentence_of: list[int]) -> dict[int, float | None]:
        spans: dict[int, list[int]] = {}
        for index, sentence in enumerate(sentence_of):
            spans.setdefault(sentence, []).append(index)
        return {sentence: parse_duration(text[tokens[idx[0]].start:tokens[idx[-1]].end])
                for sentence, idx in spans.items()}
