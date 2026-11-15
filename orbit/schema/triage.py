"""Symptom triage (M15): what a triage chat reads, asks and produces.

The astronaut describes how they feel in their own words. The triage
service (``orbit/triage/service.py``) turns each message into
``SymptomFinding``s (extractor slot), ranks ``TriagePattern``s and picks the
next ``TriageQuestion`` (reasoner slot), and keeps the whole chat as one
``TriageSession``. Nothing becomes an ``Observation`` until the astronaut
confirms.

    SymptomReport     one message in the astronaut's own words
    SymptomFinding    one symptom ORBIT understood (or a complaint outside the 8 signals)
    TriageQuestion    one follow-up question from the hand-written bank
    TriageAnswer      the astronaut's answer (None when skipped)
    PatternScore      how well a pattern fits, with up to 3 reasons
    TriageResult      everything one turn produced
    TriageSession     the chat: messages, answers, latest result, status

Pattern labels are plain words ("Signs that fit shingles (VZV)") and never a
diagnosis. Everything medical here is illustrative.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, FiniteFloat, StringConstraints, model_validator

from .enums import SignalCategory, SignalType
from .models import ActionCard, AstronautId, Contributor, Slug, UtcDatetime, _Model, _new_id
from .signals import SEVERITY_SCALE, get_spec


class TriagePattern(StrEnum):
    """What a set of symptoms may fit. Training labels in brackets (simulator, B24)."""

    VZV_LIKE = "vzv_like"  # viral_reactivation, virus vzv
    HSV1_LIKE = "hsv1_like"  # viral_reactivation, virus hsv1
    EBV_LIKE = "ebv_like"  # viral_reactivation, virus ebv
    RESPIRATORY = "respiratory"  # respiratory_infection
    EXERTION = "exertion"  # eva_exertion
    SLEEP_LOSS = "sleep_loss"  # sleep_shift
    STRESS = "stress"  # stress_load (B24)
    OTHER = "other"  # no label, or a complaint outside the 8 signals


class TriageStatus(StrEnum):
    ASKING = "asking"  # a question is open
    READY = "ready"  # no more questions; the astronaut can review and confirm
    ESCALATED = "escalated"  # a red flag fired: no questions, red-flag card first
    CONFIRMED = "confirmed"  # saved as a check-in and re-assessed
    CANCELLED = "cancelled"  # closed without saving anything
    EXPIRED = "expired"  # closed after the session timeout


OPEN_STATUSES: frozenset[TriageStatus] = frozenset(
    {TriageStatus.ASKING, TriageStatus.READY, TriageStatus.ESCALATED}
)
"""A session in one of these accepts answers, text, confirm and cancel."""

Side = Literal["left", "right", "both", "one_side"]
AnswerType = Literal["yes_no", "scale_0_3", "choice", "reading"]
AnswerValue = bool | int | float | str | None
YES_NO = ("yes", "no")
_YES = {"yes", "y", "true"}
_NO = {"no", "n", "false"}


class SymptomReport(_Model):
    """One message from the astronaut, as typed or dictated."""

    report_id: str = Field(default_factory=_new_id, max_length=64)
    astronaut_id: AstronautId
    reported_at: UtcDatetime
    text: str = Field(min_length=1, max_length=1000)
    channel: Literal["text", "voice"] = "text"


class SymptomFinding(_Model):
    """One symptom ORBIT understood from the text or an answer.

    ``signal`` is one of the 8 symptom signals, or ``None`` for a complaint
    outside them (nausea, dizziness ...), which is kept for the medical
    officer and never dropped. ``evidence`` holds the words from the text it
    is based on (empty when it came from an answer).
    """

    signal: SignalType | None = None
    label: str = Field(min_length=1, max_length=80)
    severity: int | None = Field(default=None, ge=0, le=3, description="0-3; None if not said.")
    negated: bool = Field(default=False, description="True for 'no sore throat'.")
    confidence: FiniteFloat = Field(default=1.0, ge=0, le=1)
    evidence: tuple[Annotated[str, StringConstraints(min_length=1, max_length=200)], ...] = ()
    onset_hours: FiniteFloat | None = Field(default=None, ge=0, description="How long ago it started.")
    body_site: str | None = Field(default=None, max_length=40)
    side: Side | None = None

    @model_validator(mode="after")
    def _symptom_signal(self) -> Self:
        if self.signal is not None and get_spec(self.signal).category is not SignalCategory.SYMPTOM:
            raise ValueError(f"{self.signal.value} is not a symptom signal")
        return self


class TriageQuestion(_Model):
    """One follow-up question from the hand-written bank (``cards/questions.jsonl``).

    * A **symptom question** has a ``signal``, no ``feature`` and answer type
      ``scale_0_3``: its answer is that symptom's severity. Its choices are
      the signal's scale words (none, mild, moderate, severe).
    * A **feature question** has a ``feature`` (``one_side``,
      ``recent_exertion`` ...). With a ``signal`` too, it is asked only when
      that symptom was reported; for a screening question, that symptom is
      the complaint that calls for it.

    ``likelihoods[pattern][answer]`` is P(answer | pattern), hand-set and
    illustrative. A pattern that is listed must cover every answer and sum to
    1; a pattern that is not listed gets 1 / (number of answers).
    """

    question_id: Slug
    text: str = Field(min_length=1, max_length=120)
    answer_type: AnswerType
    choices: tuple[str, ...] = ()
    signal: SignalType | None = None
    feature: Slug | None = None
    likelihoods: dict[TriagePattern, dict[str, FiniteFloat]] = Field(default_factory=dict)
    red_flag_answers: tuple[str, ...] = ()
    category: SignalCategory = SignalCategory.SYMPTOM
    screening: bool = False

    @model_validator(mode="before")
    @classmethod
    def _default_choices(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("choices"):
            return data
        if data.get("answer_type") == "yes_no":
            return {**data, "choices": YES_NO}
        if data.get("answer_type") == "scale_0_3":
            labels = SEVERITY_SCALE
            try:
                if data.get("signal"):
                    labels = get_spec(data["signal"]).scale_labels or SEVERITY_SCALE
            except (ValueError, KeyError):
                pass  # let field validation report the unknown signal
            return {**data, "choices": tuple(labels)}
        return data

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.signal is None and self.feature is None:
            raise ValueError("a question needs a signal, a feature or both")
        if self.signal is not None and get_spec(self.signal).category is not SignalCategory.SYMPTOM:
            raise ValueError(f"{self.signal.value} is not a symptom signal")
        if self.is_symptom_question:
            if self.answer_type != "scale_0_3":
                raise ValueError("a symptom question (signal, no feature) must be scale_0_3")
            if self.category is not SignalCategory.SYMPTOM:
                raise ValueError("a symptom question must have category symptom")
        if self.answer_type == "yes_no" and self.choices != YES_NO:
            raise ValueError("yes_no questions have the choices ('yes', 'no')")
        if self.answer_type == "scale_0_3" and len(self.choices) != 4:
            raise ValueError("scale_0_3 questions have 4 choices")
        if self.answer_type == "choice" and (not self.choices or len(set(self.choices)) != len(self.choices)):
            raise ValueError("choice questions need unique choices")
        if self.answer_type == "reading" and (self.choices or self.likelihoods or self.red_flag_answers):
            raise ValueError("reading questions have no choices, likelihoods or red-flag answers")
        if self.screening and (not self.red_flag_answers or self.signal is None or self.feature is None):
            raise ValueError("a screening question needs red_flag_answers, a signal and a feature")
        keys = set(self.answer_keys)
        for pattern, table in self.likelihoods.items():
            if set(table) != keys:
                raise ValueError(
                    f"likelihoods for {pattern.value} must cover exactly the answers {sorted(keys)}")
            if any(not 0 <= p <= 1 for p in table.values()) or abs(sum(table.values()) - 1) > 0.01:
                raise ValueError(f"likelihoods for {pattern.value} must be probabilities summing to 1")
        if not set(self.red_flag_answers) <= keys:
            raise ValueError(f"red_flag_answers must be among the answers {sorted(keys)}")
        return self

    @property
    def is_symptom_question(self) -> bool:
        """True if the answer is a symptom's severity (signal set, no feature)."""
        return self.signal is not None and self.feature is None

    @property
    def answer_keys(self) -> tuple[str, ...]:
        """The answers likelihoods and red flags are keyed by."""
        if self.answer_type == "yes_no":
            return YES_NO
        if self.answer_type == "scale_0_3":
            return ("0", "1", "2", "3")
        if self.answer_type == "choice":
            return self.choices
        return ()

    def normalize(self, value: Any) -> AnswerValue:
        """The stored form of an answer: bool, 0-3, a choice, a number, or None (skipped).

        Accepts the forms people and frontends send: ``True`` or ``"yes"``,
        ``2`` or ``"moderate"`` or ``"2"``, ``"None"`` (the scale word) ...
        Raises ``ValueError`` with the allowed answers otherwise.
        """
        if value is None:
            return None
        word = value.strip().lower() if isinstance(value, str) else None
        if self.answer_type == "yes_no":
            if isinstance(value, bool):
                return value
            if word in _YES or word in _NO:
                return word in _YES
        elif self.answer_type == "scale_0_3":
            if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and float(value).is_integer() and 0 <= value <= 3:
                return int(value)
            if word is not None:
                if word in ("0", "1", "2", "3"):
                    return int(word)
                lowered = [c.lower() for c in self.choices]
                if word in lowered:
                    return lowered.index(word)
        elif self.answer_type == "choice":
            if word is not None:
                for choice in self.choices:
                    if choice.lower() == word:
                        return choice
        else:  # reading
            try:
                number = float(value) if not isinstance(value, bool) else math.nan
            except (TypeError, ValueError):
                number = math.nan
            if math.isfinite(number):
                return number
        allowed = ", ".join(self.choices) if self.choices else "a number"
        if self.answer_type == "scale_0_3":
            allowed += " (or 0-3)"
        raise ValueError(f"'{value}' is not an answer to '{self.question_id}'; use {allowed}")

    def answer_key(self, value: Any) -> str | None:
        """Key into ``likelihoods`` and ``red_flag_answers``; None if skipped or a reading."""
        normal = self.normalize(value)
        if normal is None or self.answer_type == "reading":
            return None
        if self.answer_type == "yes_no":
            return "yes" if normal else "no"
        return str(normal)

    def likelihood(self, pattern: TriagePattern, key: str) -> float:
        """P(answer | pattern), or the uninformative 1 / (number of answers)."""
        table = self.likelihoods.get(pattern)
        if table is None:
            return 1.0 / len(self.answer_keys)
        return table[key]

    def answer_word(self, value: Any) -> str:
        """The answer as the astronaut saw it: 'yes', 'moderate', the choice ..."""
        normal = self.normalize(value)
        if normal is None:
            return "skipped"
        if self.answer_type == "yes_no":
            return "yes" if normal else "no"
        if self.answer_type == "scale_0_3":
            return self.choices[int(normal)]
        return f"{normal:g}" if isinstance(normal, float) else str(normal)


class TriageAnswer(_Model):
    """The astronaut's answer to one question; ``value`` is None when skipped."""

    question_id: Slug
    value: AnswerValue = None
    answered_at: UtcDatetime


class PatternScore(_Model):
    """How well one pattern fits the evidence, with up to 3 reasons."""

    pattern: TriagePattern
    label: str = Field(default="", max_length=80, description="Plain words, from cards/patterns.jsonl.")
    probability: FiniteFloat = Field(ge=0, le=1)
    reasons: tuple[Contributor, ...] = Field(default=(), max_length=3)


class TriageResult(_Model):
    """Everything one turn of a triage chat produced."""

    session_id: str = Field(min_length=1, max_length=64)
    astronaut_id: AstronautId
    as_of: UtcDatetime = Field(description="The moment assessed (mission time in the demo).")
    status: TriageStatus
    findings: tuple[SymptomFinding, ...] = ()
    ranking: tuple[PatternScore, ...] = ()
    next_question: TriageQuestion | None = None
    red_flags: tuple[str, ...] = Field(default=(), description="Ids of the red-flag rules that fired.")
    procedures: tuple[ActionCard, ...] = ()
    errors: tuple[str, ...] = Field(
        default=(), description="Steps that failed; the rest of the result is still valid.")
    model_version: str = Field(default="unversioned", max_length=64)

    @model_validator(mode="after")
    def _ranking_sums_to_one(self) -> Self:
        if self.ranking:
            total = sum(score.probability for score in self.ranking)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"ranking probabilities sum to {total:.6f}, not 1")
        return self


class TriageSession(_Model):
    """One triage chat. Stored whole in the ``triage_sessions`` table.

    ``started_at`` and ``updated_at`` are wall-clock times (for the session
    timeout); ``as_of`` is the moment assessed, which is mission time in the demo.
    """

    session_id: str = Field(min_length=1, max_length=64)
    astronaut_id: AstronautId
    started_at: UtcDatetime
    updated_at: UtcDatetime
    as_of: UtcDatetime
    reports: tuple[SymptomReport, ...] = ()
    answers: tuple[TriageAnswer, ...] = ()
    result: TriageResult | None = None
    status: TriageStatus = TriageStatus.ASKING
    confirmed_as_of: UtcDatetime | None = None
    done: bool = Field(default=False, description="The astronaut said 'that's all': no more questions.")

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES
