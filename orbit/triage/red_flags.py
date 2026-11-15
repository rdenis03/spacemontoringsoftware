"""Red flags (M15, not a slot): fixed rules that escalate before any model runs.

Each rule (``cards/red_flags.jsonl``) has an id, a plain label, text
``phrases`` ("can't breathe", "chest pain", "fainted", "confused", "a rash
near my eye"), red-flag ``answers`` to bank questions (``{"screen-breathing":
["yes"]}``) and the ``rf-`` card to show first. The triage service checks
every message and every answer with these rules before the extractor or
reasoner runs. A match sets the session to ``escalated``, stops the
questions and puts the rule's card first, whatever the score. Red flags of a
session only grow: a model may add one (a bank answer listed in a
question's ``red_flag_answers``) but nothing removes one.

Negation: a cue (no, not, never, without, don't ...) denies a phrase only
when it comes directly before it, in the same clause: "no chest pain",
"without chest pain", "not short of breath", "I have no chest pain". At most
two filler words may sit between ("I don't have any trouble breathing").
Punctuation and dashes (— – - , ; . : ! ?) end a clause. A phrase that is
itself negative ("can't breathe", "cannot breathe") is never denied by a cue
before it, so "No, I can't breathe" fires. Uncertainty is not denial: in "not
sure but chest pain", "not only chest pain" or "I don't know if ... I can't
breathe" the cue is not right before the phrase, so it fires. When in doubt,
fire. Deliberately separate from the extractor's negation, because a missed
red flag costs more than a needless one.

**The gate.** ``screen_payload(raw, rules, questions)`` is the one safety
gate: it collects every string in a request body (every key, every value,
nested lists and objects, or the raw text of a body that is not JSON) and
scans all of them, and it also checks a structured answer to a bank question
(``{"question_id": "screen-breathing", "value": "yes"}``). The triage service
calls it first on every write, before any validation, type check, length
check or question lookup, so no error can drop a detected flag.

Recall on ``tests/fixtures/triage/red_flag_sentences.jsonl`` must be 100 %.
The phrases and that file are a first draft for a person to review; they are
illustrative, not a clinical triage protocol.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbit.schema import TriageQuestion, parse_jsonl, parse_records
from orbit.schema.models import Slug

from .library import RED_FLAG_PREFIX

NEGATION_CUES = frozenset({
    "no", "not", "without", "never", "nor", "don't", "dont", "doesn't", "doesnt", "didn't", "didnt",
    "haven't", "havent", "hasn't", "hasnt", "isn't", "isnt", "wasn't", "wasnt", "aren't", "arent",
})
NEGATIVE_WORDS = NEGATION_CUES | {"can't", "cant", "cannot", "couldn't", "couldnt", "won't", "wont"}
"""A phrase containing one of these is itself negative and is never denied."""
FILLERS = frozenset({"any", "a", "an", "have", "has", "had", "got", "having", "feel", "felt", "feeling"})
"""Words that may sit between a cue and its phrase: 'don't have any trouble breathing'."""
MAX_FILLERS = 2
# Words, plus clause boundaries: punctuation, em and en dashes, and a hyphen not inside a word.
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[.,;:!?—–]|(?<![a-z0-9])-|-(?![a-z0-9])")
_BOUNDARIES = frozenset(".,;:!?—–-")


def _words(text: str) -> list[str]:
    plain = "".join(low if len(low := ch.lower()) == 1 else ch for ch in text)
    return _TOKEN.findall(plain.replace("’", "'").replace("‘", "'"))


def _negated(words: Sequence[str], start: int, phrase: Sequence[str]) -> bool:
    """True only if a cue comes directly before the phrase (fillers aside) in the same clause."""
    if any(word in NEGATIVE_WORDS for word in phrase):
        return False
    i, skipped = start - 1, 0
    while i >= 0 and words[i] in FILLERS and skipped < MAX_FILLERS:
        i, skipped = i - 1, skipped + 1
    return i >= 0 and words[i] in NEGATION_CUES


class RedFlagRule(BaseModel):
    """One line of ``cards/red_flags.jsonl``."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    rule_id: Slug
    label: str = Field(min_length=1, max_length=80)
    phrases: tuple[str, ...] = ()
    answers: dict[Slug, tuple[str, ...]] = Field(default_factory=dict)
    card_id: Slug

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.phrases and not self.answers:
            raise ValueError("a red-flag rule needs phrases, answers or both")
        if not self.card_id.startswith(RED_FLAG_PREFIX):
            raise ValueError(f"red-flag card ids start with '{RED_FLAG_PREFIX}'; got '{self.card_id}'")
        for phrase in self.phrases:
            words = _words(phrase)
            if not words or any(w in _BOUNDARIES for w in words):
                raise ValueError(f"phrase '{phrase}' must be words without punctuation")
        return self


@dataclass(frozen=True)
class RedFlagHit:
    rule_id: str
    evidence: str  # the phrase found, or "question_id=answer"


BUILT_IN_RULES: tuple[dict[str, Any], ...] = (
    {"rule_id": "breathing", "label": "Trouble breathing", "card_id": "rf-breathing",
     "phrases": ["can't breathe", "cant breathe", "cannot breathe", "trouble breathing", "short of breath",
                 "hard to breathe"],
     "answers": {"screen-breathing": ["yes"]}},
    {"rule_id": "chest", "label": "Chest pain", "card_id": "rf-chest",
     "phrases": ["chest pain", "pain in my chest", "chest pressure", "tight chest"]},
    {"rule_id": "faint", "label": "Fainting", "card_id": "rf-faint",
     "phrases": ["fainted", "passed out", "blacked out"]},
    {"rule_id": "confused", "label": "Confusion", "card_id": "rf-confused",
     "phrases": ["confused", "confusion", "disoriented"]},
    {"rule_id": "eye", "label": "Rash or tingling near the eye", "card_id": "rf-eye",
     "phrases": ["near my eye", "around my eye", "on my eyelid"],
     "answers": {"screen-eye": ["yes"]}},
)
"""Small fallback set. The full, hand-edited one is cards/red_flags.jsonl."""


class RedFlagRules:
    """The checked rules, ready to look at text and answers."""

    def __init__(self, rules: Iterable[RedFlagRule]):
        self.rules: tuple[RedFlagRule, ...] = tuple(rules)
        ids = [r.rule_id for r in self.rules]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"red-flag rules: duplicate rule ids: {', '.join(duplicates)}")
        self._phrases: dict[tuple[str, ...], str] = {}
        for rule in self.rules:
            for phrase in rule.phrases:
                key = tuple(_words(phrase))
                other = self._phrases.setdefault(key, rule.rule_id)
                if other != rule.rule_id:
                    raise ValueError(f"red-flag rules: '{phrase}' is in both {other} and {rule.rule_id}")
        self._longest = max((len(k) for k in self._phrases), default=0)
        self._by_id = {r.rule_id: r for r in self.rules}

    @classmethod
    def load(cls, path: str | None = None) -> RedFlagRules:
        rules = (parse_jsonl(path, RedFlagRule) if path
                 else parse_records(BUILT_IN_RULES, RedFlagRule)).raise_if_errors()
        return cls(rules)

    def rule(self, rule_id: str) -> RedFlagRule:
        return self._by_id[rule_id]

    def check_text(self, text: str) -> list[RedFlagHit]:
        """Rules whose phrases appear in ``text`` without a negation cue just before."""
        words = _words(text)
        found: dict[str, str] = {}
        for start in range(len(words)):
            for n in range(1, min(self._longest, len(words) - start) + 1):
                phrase = words[start:start + n]
                rule_id = self._phrases.get(tuple(phrase))
                if rule_id and rule_id not in found and not _negated(words, start, phrase):
                    found[rule_id] = " ".join(words[start:start + n])
        return [RedFlagHit(r.rule_id, found[r.rule_id]) for r in self.rules if r.rule_id in found]

    def check_answer(self, question: TriageQuestion, value: Any) -> list[RedFlagHit]:
        """Rules that list this answer. ``check_bank`` makes sure every answer in a
        question's ``red_flag_answers`` is listed by a rule, so the bank can add red flags."""
        key = question.answer_key(value)
        if key is None:
            return []
        return [RedFlagHit(r.rule_id, f"{question.question_id}={key}") for r in self.rules
                if key in r.answers.get(question.question_id, ())]

    def check_bank(self, questions: Iterable[TriageQuestion]) -> None:
        """Every red-flag answer in the question bank must lead to a rule (and so a card)."""
        missing = [f"{q.question_id}={answer}" for q in questions for answer in q.red_flag_answers
                   if not any(answer in r.answers.get(q.question_id, ()) for r in self.rules)]
        if missing:
            raise ValueError(f"red-flag rules: no rule covers the bank's red-flag answers {', '.join(missing)}")

    def check_cards(self, has_card) -> None:
        """Every rule's card must exist in the triage library."""
        missing = [f"{r.rule_id} -> {r.card_id}" for r in self.rules if not has_card(r.card_id)]
        if missing:
            raise ValueError(f"red-flag rules: unknown cards {', '.join(missing)}")


# ---- the gate: every string in a request, before anything else ----------------------


def collect_strings(raw: Any) -> list[str]:
    """Every string in a request body: keys, values, nested lists and objects, raw text."""
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, (bytes, bytearray)):
            found.append(bytes(item).decode("utf-8", errors="replace"))
        elif isinstance(item, Mapping):
            for key, value in item.items():
                walk(key)
                walk(value)
        elif isinstance(item, (list, tuple, set, frozenset)):
            for value in item:
                walk(value)

    walk(raw)
    return found


def screen_payload(raw: Any, rules: RedFlagRules,
                   questions: Mapping[str, TriageQuestion] | None = None) -> list[str]:
    """The red-flag rule ids in a whole request body, in first-found order.

    Scans every string (``collect_strings``), and when the body names a bank
    question, its answer too: ``screen-breathing = yes`` fires even if every
    other field in the request is invalid. Never raises on a malformed body.
    """
    rule_ids: list[str] = []
    for text in collect_strings(raw):
        rule_ids += [hit.rule_id for hit in rules.check_text(text)]
    if isinstance(raw, Mapping) and questions and isinstance(raw.get("question_id"), str):
        question = questions.get(raw["question_id"])
        if question is not None:
            try:
                rule_ids += [hit.rule_id for hit in rules.check_answer(question, raw.get("value"))]
            except (TypeError, ValueError):
                pass  # an invalid value cannot be a structured red-flag answer; its strings were scanned
    return list(dict.fromkeys(rule_ids))


def flagged_strings(raw: Any, rules: RedFlagRules) -> list[str]:
    """The strings in a request body that set off a rule: the words to keep onboard."""
    return [text for text in collect_strings(raw) if rules.check_text(text)]
