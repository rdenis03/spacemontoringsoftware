"""Triage reasoner ``rules`` (slot ``reasoner``, team module M15).

Ranks the 8 triage patterns for what the astronaut said, and picks the next
follow-up question. Hand-set and readable, like the starter scorer's
``SYMPTOM_WEIGHTS``: every probability comes with up to 3 plain-language
reasons the astronaut can check. Illustrative, never clinical advice.

**Ranking.** Each pattern starts from a prior weight (``other`` 2, the rest
1, so "something else" leads when nothing is known) and is multiplied by a
likelihood ratio for every piece of evidence:

    Evidence                                   Patterns it points to
    -----------------------------------------  ---------------------------------
    Rash or tingling                           vzv_like
    Mouth sores                                hsv1_like
    Swollen glands, sore throat                ebv_like (throat also respiratory)
    Fever or chills, sore throat               respiratory
    High CRP, respiratory-rate anomaly         respiratory
    Muscle aches, fatigue, EVA in last 3 days  exertion
    Fatigue, headache, sleep anomaly           sleep_loss
    Headache, high stress, low mood            stress
    Viral DNA in saliva (>= 100 copies/mL)     that virus's pattern
    A complaint outside the 8 signals          other

A stronger symptom weighs more (``SEVERITY_POWER``); a denied symptom
("none", "no fever") divides by its ratio, so it weighs against the
patterns that expect it. Viral DNA, CRP, stress and mood are read from the
preview's contributors (the scorer names viral DNA only above its 100
copies/mL detection limit); anomalies from ``evidence.anomalies``; the EVA
from ``ctx.events``. Answers to feature questions (one side, recent hard
work ...) count through the bank's hand-set likelihoods P(answer | pattern).
Symptom answers are already merged into the findings by the triage service,
so they are not counted twice. The weights are normalised to probabilities;
each pattern's reasons are its 3 largest factors, as ``Contributor``s with
points = natural log of the factor and ``signal`` or ``event_id`` set.

**Next question**, in this order:

1. a screening question the complaint calls for (its ``signal`` was reported);
2. the severity of a mentioned symptom that has none yet;
3. the bank's next question (file order) that concerns one of the top 3
   patterns: its answers would differ for that pattern (total variation
   distance from the average answer >= ``CONCERN_TV``).

Never the same question twice (``evidence.asked``), and never what ORBIT
knows: no spacewalk question when ``ctx.events`` has an EVA in the last 3
days, no question about a symptom already rated, no one-side question when
the side is known, no eye screening when the body site is known and not on
the face, no short-sleep question with a sleep anomaly, no stress question
when the check-in already shows high stress. ``None`` when the top
probability reaches ``stop_probability``, after ``max_questions``, or when
no question is left.

Worked example (AST-01, day 89 10:30, "Weird burning, tingly patch on my
ribs since last night. Pretty wiped out too."): severity of the tingling
first ("moderate"), then "Is it on one side of your body only?" ("yes",
vzv_like leads at about 0.76), then "Any fever or chills?" ("none", vzv_like
about 0.83, above 0.8: ready). The spacewalk question is skipped.

Options:
    questions_path: JSONL bank of ``TriageQuestion`` records
        (``cards/questions.jsonl``). Default: a small built-in bank.
    max_questions: most questions per session (default 5).
    stop_probability: stop asking once the top pattern reaches it (default 0.8).

Pure: no clock, no I/O after loading, same evidence gives the same answer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from orbit.core.interfaces import AssessmentContext, TriageEvidence
from orbit.core.registry import register
from orbit.schema import (
    Contributor,
    ContextEvent,
    EventType,
    PatternScore,
    SignalCategory,
    SignalType,
    TriagePattern,
    TriageQuestion,
    get_spec,
    parse_jsonl,
    parse_records,
)

from .scorer import describe_anomaly

P = TriagePattern
S = SignalType

PRIORS: dict[TriagePattern, float] = {p: 1.0 for p in TriagePattern} | {P.OTHER: 2.0}

SYMPTOM_LR: dict[SignalType, dict[TriagePattern, float]] = {
    S.SYMPTOM_RASH_TINGLING: {P.VZV_LIKE: 8.0, P.HSV1_LIKE: 1.2},
    S.SYMPTOM_MOUTH_SORES: {P.HSV1_LIKE: 8.0, P.EBV_LIKE: 1.5},
    S.SYMPTOM_SWOLLEN_GLANDS: {P.EBV_LIKE: 5.0, P.RESPIRATORY: 1.5},
    S.SYMPTOM_SORE_THROAT: {P.EBV_LIKE: 3.0, P.RESPIRATORY: 3.0},
    S.SYMPTOM_FEVER_CHILLS: {P.RESPIRATORY: 6.0, P.EBV_LIKE: 3.0},
    S.SYMPTOM_FATIGUE: {P.EXERTION: 2.0, P.SLEEP_LOSS: 2.5, P.EBV_LIKE: 2.0, P.VZV_LIKE: 1.5,
                        P.RESPIRATORY: 1.5, P.STRESS: 1.5},
    S.SYMPTOM_HEADACHE: {P.SLEEP_LOSS: 2.5, P.STRESS: 2.5, P.RESPIRATORY: 1.3},
    S.SYMPTOM_MUSCLE_ACHES: {P.EXERTION: 4.0, P.RESPIRATORY: 1.5},
}
"""Likelihood ratio of a reported symptom for each pattern (1.0 when not listed)."""

SEVERITY_POWER: dict[int | None, float] = {None: 0.85, 1: 0.75, 2: 1.0, 3: 1.25}
"""A symptom's ratio is raised to this power: stronger symptoms weigh more."""

DENIED_POWER = 1.0
"""A denied symptom divides by its ratio raised to this power."""

VIRAL_LR = {S.SALIVA_VZV_DNA: (P.VZV_LIKE, 6.0), S.SALIVA_HSV1_DNA: (P.HSV1_LIKE, 6.0),
            S.SALIVA_EBV_DNA: (P.EBV_LIKE, 6.0)}
CONTRIBUTOR_LR = {S.CRP: (P.RESPIRATORY, 3.0), S.STRESS: (P.STRESS, 3.0), S.MOOD: (P.STRESS, 2.0)}
RESP_ANOMALY_LR = (P.RESPIRATORY, 2.5)
SLEEP_ANOMALY_LR = (P.SLEEP_LOSS, 2.5)
EVA_LR = (P.EXERTION, 3.0)
OTHER_COMPLAINT_LR = (P.OTHER, 4.0)
EVA_DAYS = 3
TOP_PATTERNS = 3
CONCERN_TV = 0.15
FACE_SITES = frozenset({"face", "eye", "forehead", "scalp", "ear", "nose"})
FEATURE_SIGNALS = {"recent_exertion": S.WORKLOAD, "short_sleep": S.SLEEP_DURATION,
                   "high_stress": S.STRESS}
"""Signal a feature answer's reason is tied to (for consent); else the question's signal."""

_ONE_SIDE = {"vzv_like": {"yes": 0.9, "no": 0.1}, "hsv1_like": {"yes": 0.4, "no": 0.6},
             "ebv_like": {"yes": 0.3, "no": 0.7}, "respiratory": {"yes": 0.25, "no": 0.75},
             "exertion": {"yes": 0.1, "no": 0.9}, "sleep_loss": {"yes": 0.1, "no": 0.9},
             "stress": {"yes": 0.1, "no": 0.9}, "other": {"yes": 0.2, "no": 0.8}}
_QUIET_FEVER = {"0": 0.85, "1": 0.1, "2": 0.04, "3": 0.01}
_FEVER = {"vzv_like": {"0": 0.75, "1": 0.15, "2": 0.07, "3": 0.03},
          "hsv1_like": {"0": 0.7, "1": 0.2, "2": 0.07, "3": 0.03},
          "ebv_like": {"0": 0.35, "1": 0.3, "2": 0.25, "3": 0.1},
          "respiratory": {"0": 0.1, "1": 0.3, "2": 0.35, "3": 0.25},
          "exertion": _QUIET_FEVER, "sleep_loss": _QUIET_FEVER, "stress": _QUIET_FEVER,
          "other": {"0": 0.6, "1": 0.2, "2": 0.12, "3": 0.08}}
_EXERTION = {p.value: {"yes": y, "no": round(1 - y, 2)} for p, y in zip(
    TriagePattern, (0.3, 0.3, 0.3, 0.25, 0.9, 0.4, 0.4, 0.3))}

BUILT_IN_QUESTIONS: tuple[dict[str, Any], ...] = (
    {"question_id": "screen-breathing", "text": "Any trouble breathing?", "answer_type": "yes_no",
     "signal": "symptom_fever_chills", "feature": "breathing_trouble", "screening": True,
     "red_flag_answers": ["yes"]},
    {"question_id": "one-side", "text": "Is it on one side of your body only?", "answer_type": "yes_no",
     "signal": "symptom_rash_tingling", "feature": "one_side", "likelihoods": _ONE_SIDE},
    {"question_id": "fever-chills", "text": "Any fever or chills?", "answer_type": "scale_0_3",
     "signal": "symptom_fever_chills", "likelihoods": _FEVER},
    {"question_id": "recent-exertion", "text": "Any hard physical work or a spacewalk in the last 3 days?",
     "answer_type": "yes_no", "feature": "recent_exertion", "category": "context",
     "likelihoods": _EXERTION},
    *({"question_id": s.value.removeprefix("symptom_").replace("_", "-"),
       "text": f"{get_spec(s).label}: how strong is it?", "answer_type": "scale_0_3", "signal": s.value}
      for s in SYMPTOM_LR if s is not S.SYMPTOM_FEVER_CHILLS),
)
"""Small fallback bank. The full, hand-edited one is cards/questions.jsonl."""


def _recent_eva(ctx: AssessmentContext) -> ContextEvent | None:
    """An EVA that started before ``as_of`` and ended at most EVA_DAYS before it."""
    since = ctx.as_of - timedelta(days=EVA_DAYS)
    for event in reversed(ctx.events):
        if event.event_type is EventType.EVA and event.start <= ctx.as_of \
                and (event.end or event.start) >= since:
            return event
    return None


def _total_variation(a: Sequence[float], b: Sequence[float]) -> float:
    return 0.5 * sum(abs(x - y) for x, y in zip(a, b, strict=True))


@register("reasoner", "rules")
class RulesReasoner:
    version = "rules-0.1"

    def __init__(self, questions_path: str | None = None, max_questions: int = 5,
                 stop_probability: float = 0.8):
        if max_questions < 1:
            raise ValueError("max_questions must be at least 1")
        if not 0 < stop_probability <= 1:
            raise ValueError("stop_probability must be in (0, 1]")
        questions = (parse_jsonl(questions_path, TriageQuestion) if questions_path
                     else parse_records(BUILT_IN_QUESTIONS, TriageQuestion)).raise_if_errors()
        ids = [q.question_id for q in questions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"question bank: duplicate question ids: {', '.join(duplicates)}")
        self.questions: tuple[TriageQuestion, ...] = tuple(questions)
        self.max_questions = max_questions
        self.stop_probability = stop_probability
        self._by_id = {q.question_id: q for q in self.questions}
        self._symptom_question: dict[SignalType, TriageQuestion] = {}
        for q in self.questions:
            if q.is_symptom_question:
                self._symptom_question.setdefault(q.signal, q)

    # ---- ranking ---------------------------------------------------------------------

    def rank(self, evidence: TriageEvidence, ctx: AssessmentContext) -> list[PatternScore]:
        factors: dict[TriagePattern, list[tuple[float, Contributor | None]]] = {p: [] for p in P}

        def add(pattern: TriagePattern, factor: float, reason: Contributor | None) -> None:
            factors[pattern].append((factor, reason))

        for finding in evidence.findings:
            if finding.signal is None:
                if not finding.negated:
                    pattern, ratio = OTHER_COMPLAINT_LR
                    add(pattern, ratio, Contributor(label=finding.label, points=0))
                continue
            spec = get_spec(finding.signal)
            denied = finding.negated or finding.severity == 0
            label = spec.label if finding.severity in (None, 0) else \
                f"{spec.label}: {spec.scale_label(finding.severity)}"
            for pattern, ratio in SYMPTOM_LR.get(finding.signal, {}).items():
                if denied:
                    add(pattern, ratio ** -DENIED_POWER, None)
                else:
                    add(pattern, ratio ** SEVERITY_POWER[finding.severity],
                        Contributor(label=label, points=0, signal=finding.signal))

        if evidence.preview is not None:
            for reason in evidence.preview.contributors:
                found = VIRAL_LR.get(reason.signal) or CONTRIBUTOR_LR.get(reason.signal)
                if found is not None and reason.points > 0:
                    add(found[0], found[1], Contributor(label=reason.label, points=0, signal=reason.signal))

        sleep_seen = False
        for anomaly in evidence.anomalies:
            category = get_spec(anomaly.signal).category
            if anomaly.signal is S.RESP_RATE:
                add(*RESP_ANOMALY_LR, Contributor(label=describe_anomaly(anomaly), points=0,
                                                  signal=anomaly.signal))
            elif category is SignalCategory.SLEEP and not sleep_seen:
                sleep_seen = True
                add(*SLEEP_ANOMALY_LR, Contributor(label=describe_anomaly(anomaly), points=0,
                                                   signal=anomaly.signal))

        eva = _recent_eva(ctx)
        if eva is not None:
            add(*EVA_LR, Contributor(label=f"Spacewalk in the last {EVA_DAYS} days", points=0,
                                     event_id=eva.event_id))

        for answer in evidence.answers:
            question = self._by_id.get(answer.question_id)
            if question is None or question.is_symptom_question:
                continue  # symptom answers are already in the findings
            key = question.answer_key(answer.value)
            if key is None:
                continue
            uniform = 1.0 / len(question.answer_keys)
            label = f"{question.answer_word(answer.value).capitalize()}: {question.text}"[:160]
            signal = FEATURE_SIGNALS.get(question.feature or "", question.signal)
            for pattern in P:
                factor = question.likelihood(pattern, key) / uniform
                add(pattern, max(factor, 1e-6), Contributor(label=label, points=0, signal=signal))

        weights = {p: PRIORS[p] * math.prod(f for f, _ in factors[p]) for p in P}
        total = sum(weights.values())
        scores = []
        for pattern in P:
            helpful = sorted(((f, r) for f, r in factors[pattern] if r is not None and f > 1),
                             key=lambda item: item[0], reverse=True)[:3]
            reasons = tuple(r.model_copy(update={"points": round(math.log(f), 2)}) for f, r in helpful)
            scores.append(PatternScore(pattern=pattern, probability=weights[pattern] / total,
                                       reasons=reasons))
        return sorted(scores, key=lambda s: s.probability, reverse=True)  # stable: ties keep enum order

    # ---- next question -----------------------------------------------------------------

    def next_question(self, evidence: TriageEvidence, ranking: Sequence[PatternScore],
                      ctx: AssessmentContext) -> TriageQuestion | None:
        if len(evidence.asked) >= self.max_questions:
            return None
        if ranking and max(s.probability for s in ranking) >= self.stop_probability:
            return None
        asked = set(evidence.asked)
        open_questions = [q for q in self.questions
                          if q.question_id not in asked and not self._known(q, evidence, ctx)]
        reported = {f.signal for f in evidence.findings if f.signal is not None and not f.negated}

        for q in open_questions:  # 1. screening the complaint calls for
            if q.screening and q.signal in reported:
                return q
        for finding in evidence.findings:  # 2. a missing severity
            if finding.signal is not None and not finding.negated and finding.severity is None:
                q = self._symptom_question.get(finding.signal)
                if q is not None and q in open_questions:
                    return q
        top = [s.pattern for s in sorted(ranking, key=lambda s: s.probability, reverse=True)][:TOP_PATTERNS]
        for q in open_questions:  # 3. the bank's next question about the top patterns
            if q.screening or (q.signal is not None and not q.is_symptom_question and q.signal not in reported):
                continue
            if self._concerns(q, top):
                return q
        return None

    def _known(self, q: TriageQuestion, evidence: TriageEvidence, ctx: AssessmentContext) -> bool:
        """True if ORBIT already knows the answer, so the question would waste the astronaut's time."""
        about = [f for f in evidence.findings if q.signal is not None and f.signal is q.signal]
        if q.is_symptom_question:
            return any(f.negated or f.severity is not None for f in about)
        if q.feature == "recent_exertion":
            return _recent_eva(ctx) is not None
        if q.feature == "one_side":
            return any(f.side is not None for f in about)
        if q.feature == "rash_near_eye":
            return any(f.body_site is not None and f.body_site not in FACE_SITES for f in about)
        if q.feature == "short_sleep":
            return any(get_spec(a.signal).category is SignalCategory.SLEEP for a in evidence.anomalies)
        if q.feature == "high_stress":
            preview = evidence.preview
            return preview is not None and any(r.signal is S.STRESS for r in preview.contributors)
        return False

    def _concerns(self, q: TriageQuestion, top: Sequence[TriagePattern]) -> bool:
        """True if the answer would differ for one of the top patterns."""
        keys = q.answer_keys
        if keys and q.likelihoods:
            table = {p: [q.likelihood(p, k) for k in keys] for p in P}
            average = [sum(table[p][i] for p in P) / len(P) for i in range(len(keys))]
            if any(_total_variation(table[p], average) >= CONCERN_TV for p in top):
                return True
        if q.is_symptom_question:
            ratios = SYMPTOM_LR.get(q.signal, {})
            return any(ratios.get(p, 1.0) != 1.0 for p in top)
        return False
