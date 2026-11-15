"""Triage reasoner ``bayes`` (slot ``reasoner``, team module M15, task B24).

The learned version of the ``rules`` reasoner. Ranking is **naive Bayes**:
each pattern's probability is its prior times P(clue | pattern) for every
clue, as if the clues were independent, normalised to sum to 1. The tables
are counted on simulated missions by ``orbit/learning/train_reasoner.py``
(with Laplace smoothing: one extra count everywhere, so nothing is
impossible). No machine-learning library at run time.

**Clues** (``observe``; the trainer uses the same function, labs aside):

    clue                        values                  from
    --------------------------  ----------------------  ---------------------------------
    sym:<symptom signal>        0-3, or "present"       evidence.findings (a symptom not
                                                        mentioned is unknown and skipped;
                                                        "present" = mentioned, no severity,
                                                        P = P(1) + P(2) + P(3))
    anom:<vital> / anom:sleep   yes / no                evidence.anomalies
    lab:<saliva DNA>, lab:crp   yes / no                the preview's contributors
    wb:stress, wb:mood          yes / no                the preview's contributors
    event:eva                   yes / no                an EVA in ctx.events, last 3 days
    other_complaint             yes / no                a finding outside the 8 signals
                                                        (hand-set table: the simulator has none)
    ans:<question id>           the answer key          evidence.answers, **non-symptom
                                                        questions only**

Unknown is not "no": without a preview, the vitals, labs and wellbeing clues
are left out. At run time ``observe`` gives a lab clue only for a positive
result ("yes"): the preview's contributors cannot tell a negative result from
no test, and onboard a missing test says nothing. (In the simulator extra
tests happen only during an illness, so "no result" would give the answer
away; NOTES B03, B09.) The trainer counts a lab when the preview's recent
window (pipeline ``recent_days``, 3) holds a reading, the one the scorer
shows: "yes" if flagged, "no" if not (``lab_values`` in
``train_reasoner.py``), so P(yes | pattern) is "positive, given it was
measured in the window", matching what this clue sees at run time. CRP is rarely measured outside
respiratory days in the simulator, so its table is near 0.5 for most patterns.

Answers to symptom questions are already merged into the findings by the
triage service (severity, or denied for "none"), so they are read from
``sym:`` and skipped in ``ans:``: nothing is counted twice.

**Reasons**: for each pattern, the 3 clues that are present (a reported
symptom, an anomaly, a lab result, the EVA, an answer) with the largest
log-likelihood ratio ``ln P(clue | pattern) - ln mean P(clue | other patterns)``,
as ``Contributor``s with that ratio as points and ``signal`` or ``event_id`` set.

**Next question**, keeping the rules reasoner's order and stop rules:

1. a screening question the complaint calls for;
2. the severity of a mentioned symptom that has none;
3. else, unless the top pattern has reached ``stop_probability``, the open
   question with the highest **expected information gain**: how many bits of
   uncertainty about the pattern its answer is expected to remove,
   ``H(now) - sum_a P(a) H(after a)``, with P(a | pattern) from the weights
   file (or the bank). ``None`` below ``min_gain_bits``.

Like ``rules``: never the same question twice, never what ORBIT already knows,
``None`` after ``max_questions``. One difference, on purpose: ``rules`` checks
``stop_probability`` before steps 1 and 2; ``bayes`` after them. The learned
tables are often sure early (in the simulator only VZV gives a rash), and a
safety screening question or a missing severity (which confirm stores, and
the scorer counts) must not be skipped because the model is confident.

**The answer likelihoods are hand-set** (``cards/questions.jsonl``); the
trainer samples simulated answers from them, so an evaluation that uses
answers measures consistency with the bank, not medical truth.

Weights file (JSON; default ``orbit/learning/reasoner_weights.json``)::

    {"version": "s1-20-d180-c4",                       # model_version "bayes-s1-20-d180-c4"
     "priors": {"vzv_like": 0.05, ...},
     "features": {"sym:symptom_fatigue": {"vzv_like": {"0": 0.2, "1": 0.5, ...}, ...}, ...},
     "answers": {"one-side": {"vzv_like": {"yes": 0.9, "no": 0.1}, ...}, ...},
     "trained_on": {...}, "notes": "..."}

Options:
    weights_path: the weights JSON. Default: the shipped file.
    questions_path: the question bank (``cards/questions.jsonl``). Default: the
        rules reasoner's small built-in bank.
    max_questions (5), stop_probability (0.8), min_gain_bits (0.05).

Evaluation (B24; simulated; ``reports/triage_eval.json``). Seeds 101-105, 180
days x 4 crew, symptom look-alikes, 30 % mild illnesses, 459 chats read by
``lexicon``; weights ``s1-20-d180-c4``:

                                       rules    bayes
    top-1, without answers (main)      0.994    0.976
    top-3, without answers (main)      1.000    0.991
    Brier, without answers (main)      0.191    0.040
    top-1 / Brier, with answers        0.972 / 0.150   0.976 / 0.042   (circular)
    questions per chat                 3.6      1.5

Much better calibrated and fewer questions, but it fails the switch rule on
top-1 and top-3, so ``orbit.toml`` keeps ``rules``.

Pure: no clock, no I/O after loading, same evidence gives the same answer.
Illustrative, never clinical advice.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from orbit.core.interfaces import AssessmentContext, TriageEvidence
from orbit.core.registry import register
from orbit.schema import (
    Contributor,
    PatternScore,
    SignalCategory,
    SignalType,
    TriagePattern,
    TriageQuestion,
    get_spec,
    parse_jsonl,
    parse_records,
)

from .reasoner import BUILT_IN_QUESTIONS, EVA_DAYS, FEATURE_SIGNALS, RulesReasoner, _recent_eva
from .scorer import describe_anomaly

P = TriagePattern
S = SignalType
DEFAULT_WEIGHTS = Path(__file__).resolve().parents[1] / "learning" / "reasoner_weights.json"
YES_NO = ("no", "yes")
LEVELS = ("0", "1", "2", "3")
SYMPTOMS = tuple(s for s in S if get_spec(s).category is SignalCategory.SYMPTOM)
ANOMALY_CLUES = {S.RESP_RATE: "anom:resp_rate", S.SKIN_TEMP: "anom:skin_temp",
                 S.RESTING_HR: "anom:resting_hr", S.HRV_RMSSD: "anom:hrv_rmssd", S.SPO2: "anom:spo2"}
SLEEP_CLUE = "anom:sleep"
CONTRIBUTOR_CLUES = {S.SALIVA_VZV_DNA: "lab:saliva_vzv_dna", S.SALIVA_HSV1_DNA: "lab:saliva_hsv1_dna",
                     S.SALIVA_EBV_DNA: "lab:saliva_ebv_dna", S.CRP: "lab:crp",
                     S.STRESS: "wb:stress", S.MOOD: "wb:mood"}
EVA_CLUE = "event:eva"
OTHER_CLUE = "other_complaint"
OTHER_COMPLAINT_TABLE = {p.value: ({"yes": 0.5, "no": 0.5} if p is P.OTHER else {"yes": 0.05, "no": 0.95})
                         for p in P}
"""Hand-set: the simulator never makes complaints outside the 8 signals."""


def clue_names() -> list[str]:
    """Every clue except answers, in a fixed order (the weights file's ``features``)."""
    return ([f"sym:{s.value}" for s in SYMPTOMS] + list(ANOMALY_CLUES.values()) + [SLEEP_CLUE]
            + list(CONTRIBUTOR_CLUES.values()) + [EVA_CLUE, OTHER_CLUE])


def clue_values(name: str) -> tuple[str, ...]:
    return LEVELS if name.startswith("sym:") else YES_NO


@dataclass(frozen=True)
class Clue:
    name: str  # "sym:symptom_fatigue", "ans:one-side" ...
    value: str  # "0"-"3", "present", "yes", "no", or an answer key
    reason: Contributor | None  # shown when the clue is present; None for absent clues


def observe(evidence: TriageEvidence, ctx: AssessmentContext,
            questions: dict[str, TriageQuestion] | None = None) -> list[Clue]:
    """The clues in the evidence (shared with the trainer). Unknown symptoms are left out."""
    clues: list[Clue] = []
    other = False
    for f in evidence.findings:
        if f.signal is None:
            other = other or not f.negated
            continue
        spec = get_spec(f.signal)
        if f.negated or f.severity == 0:
            clues.append(Clue(f"sym:{f.signal.value}", "0", None))
        elif f.severity is None:
            clues.append(Clue(f"sym:{f.signal.value}", "present",
                              Contributor(label=spec.label, points=0, signal=f.signal)))
        else:
            clues.append(Clue(f"sym:{f.signal.value}", str(f.severity), Contributor(
                label=f"{spec.label}: {spec.scale_label(f.severity)}", points=0, signal=f.signal)))
    clues.append(Clue(OTHER_CLUE, "yes" if other else "no", None))

    if evidence.preview is not None:  # without a preview, vitals and labs are unknown
        found: dict[str, Contributor] = {}
        for a in evidence.anomalies:
            name = SLEEP_CLUE if get_spec(a.signal).category is SignalCategory.SLEEP \
                else ANOMALY_CLUES.get(a.signal)
            if name is not None and name not in found:
                found[name] = Contributor(label=describe_anomaly(a), points=0, signal=a.signal)
        for name in [*ANOMALY_CLUES.values(), SLEEP_CLUE]:
            clues.append(Clue(name, "yes" if name in found else "no", found.get(name)))

        shown: dict[str, Contributor] = {}
        for r in evidence.preview.contributors:
            name = CONTRIBUTOR_CLUES.get(r.signal)
            if name is not None and r.points > 0 and name not in shown:
                shown[name] = Contributor(label=r.label, points=0, signal=r.signal)
        for name in CONTRIBUTOR_CLUES.values():
            if name in shown:
                clues.append(Clue(name, "yes", shown[name]))
            elif not name.startswith("lab:"):  # a missing lab result is unknown, not negative
                clues.append(Clue(name, "no", None))

    eva = _recent_eva(ctx)
    clues.append(Clue(EVA_CLUE, "yes" if eva else "no", Contributor(
        label=f"Spacewalk in the last {EVA_DAYS} days", points=0, event_id=eva.event_id)
        if eva else None))

    for answer in evidence.answers:
        q = (questions or {}).get(answer.question_id)
        if q is None or q.is_symptom_question:
            continue  # symptom answers are already in the findings: never counted twice
        key = q.answer_key(answer.value)
        if key is None:
            continue
        label = f"{q.answer_word(answer.value).capitalize()}: {q.text}"[:160]
        clues.append(Clue(f"ans:{q.question_id}", key, Contributor(
            label=label, points=0, signal=FEATURE_SIGNALS.get(q.feature or "", q.signal))))
    return clues


def _entropy(probs: Sequence[float]) -> float:
    return -sum(p * math.log2(p) for p in probs if p > 0)


def _table(raw, where: str, keys: Sequence[str] | None) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict) or set(raw) != {p.value for p in P}:
        raise ValueError(f"{where}: needs a row for each of the 8 patterns")
    if keys is None:  # answers: checked against the question bank when the module is built
        rows = [set(row) for row in raw.values() if isinstance(row, dict)]
        if any(r != rows[0] for r in rows):
            raise ValueError(f"{where}: every pattern's row needs the same answer keys")
    for pattern, row in raw.items():
        if not isinstance(row, dict) or (keys is not None and set(row) != set(keys)) \
                or not all(isinstance(v, (int, float)) and 0 < v <= 1 for v in row.values()) \
                or abs(sum(row.values()) - 1) > 1e-3:
            raise ValueError(f"{where}: row {pattern} must give each answer a probability "
                             "above 0, summing to 1")
    return {p: {k: float(v) for k, v in row.items()} for p, row in raw.items()}


def load_reasoner_weights(path: str | Path) -> tuple[str, dict[str, float], dict, dict]:
    """(version, priors, clue tables, answer tables); ValueError if malformed."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    version = doc.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("reasoner weights: 'version' must be a non-empty string")
    priors = doc.get("priors")
    if not isinstance(priors, dict) or set(priors) != {p.value for p in P} \
            or not all(isinstance(v, (int, float)) and v > 0 for v in priors.values()) \
            or abs(sum(priors.values()) - 1) > 1e-3:
        raise ValueError("reasoner weights: 'priors' must give the 8 patterns probabilities summing to 1")
    raw = doc.get("features") or {}
    if set(raw) != set(clue_names()):
        raise ValueError(f"reasoner weights: 'features' must be exactly {clue_names()}")
    features = {name: _table(raw[name], f"reasoner weights: {name}", clue_values(name)) for name in raw}
    answers = {qid: _table(t, f"reasoner weights: answers {qid}", None)
               for qid, t in (doc.get("answers") or {}).items()}
    return version, {k: float(v) for k, v in priors.items()}, features, answers


@register("reasoner", "bayes")
class BayesReasoner:
    _known = RulesReasoner._known  # what ORBIT already knows: the same rules as ``rules``

    def __init__(self, weights_path: str | None = None, questions_path: str | None = None,
                 max_questions: int = 5, stop_probability: float = 0.8, min_gain_bits: float = 0.05):
        if max_questions < 1:
            raise ValueError("max_questions must be at least 1")
        if not 0 < stop_probability <= 1:
            raise ValueError("stop_probability must be in (0, 1]")
        if min_gain_bits < 0:
            raise ValueError("min_gain_bits must not be negative")
        version, self.priors, self.features, self.answers = load_reasoner_weights(
            weights_path or DEFAULT_WEIGHTS)
        self.weights_version = version
        self.version = f"bayes-{version}"[:32]
        questions = (parse_jsonl(questions_path, TriageQuestion) if questions_path
                     else parse_records(BUILT_IN_QUESTIONS, TriageQuestion)).raise_if_errors()
        ids = [q.question_id for q in questions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"question bank: duplicate question ids: {', '.join(duplicates)}")
        self.questions: tuple[TriageQuestion, ...] = tuple(questions)
        self.max_questions = max_questions
        self.stop_probability = stop_probability
        self.min_gain_bits = min_gain_bits
        self._by_id = {q.question_id: q for q in self.questions}
        for qid, table in self.answers.items():  # a renamed key would fail mid-chat
            q = self._by_id.get(qid)
            if q is None or q.is_symptom_question:
                continue  # never read: symptom answers come from the sym: tables
            for pattern, row in table.items():
                if set(row) != set(q.answer_keys):
                    raise ValueError(f"reasoner weights: answers {qid} row {pattern} has keys "
                                     f"{sorted(row)}; the question bank has {sorted(q.answer_keys)}")
        self._symptom_question: dict[SignalType, TriageQuestion] = {}
        for q in self.questions:
            if q.is_symptom_question:
                self._symptom_question.setdefault(q.signal, q)

    # ---- likelihoods -----------------------------------------------------------------

    def likelihood(self, clue: Clue, pattern: TriagePattern) -> float:
        """P(clue value | pattern)."""
        if clue.name == OTHER_CLUE:
            return OTHER_COMPLAINT_TABLE[pattern.value][clue.value]
        if clue.name.startswith("ans:"):
            return self._answer_table(self._by_id[clue.name[4:]], pattern)[clue.value]
        row = self.features[clue.name][pattern.value]
        if clue.value == "present":
            return row["1"] + row["2"] + row["3"]
        return row[clue.value]

    def _answer_table(self, q: TriageQuestion, pattern: TriagePattern) -> dict[str, float]:
        if q.is_symptom_question:
            return self.features[f"sym:{q.signal.value}"][pattern.value]
        learned = self.answers.get(q.question_id)
        if learned is not None:
            return learned[pattern.value]
        return {k: q.likelihood(pattern, k) for k in q.answer_keys}

    # ---- ranking ---------------------------------------------------------------------

    def rank(self, evidence: TriageEvidence, ctx: AssessmentContext) -> list[PatternScore]:
        clues = observe(evidence, ctx, self._by_id)
        log_post = {p: math.log(self.priors[p.value]) for p in P}
        table = {c: {p: self.likelihood(c, p) for p in P} for c in clues}
        for c in clues:
            for p in P:
                log_post[p] += math.log(table[c][p])
        top = max(log_post.values())
        weights = {p: math.exp(v - top) for p, v in log_post.items()}
        total = sum(weights.values())
        scores = []
        for p in P:
            ratios = []
            for c in clues:
                if c.reason is None:
                    continue
                others = [table[c][q] for q in P if q is not p]
                llr = math.log(table[c][p] / (sum(others) / len(others)))
                if llr > 0:
                    ratios.append((llr, c.reason))
            ratios.sort(key=lambda item: item[0], reverse=True)
            reasons = tuple(r.model_copy(update={"points": round(llr, 2)}) for llr, r in ratios[:3])
            scores.append(PatternScore(pattern=p, probability=weights[p] / total, reasons=reasons))
        return sorted(scores, key=lambda s: s.probability, reverse=True)

    # ---- next question ---------------------------------------------------------------

    def information_gain(self, q: TriageQuestion, ranking: Sequence[PatternScore]) -> float:
        """Expected bits of uncertainty about the pattern that the answer to ``q`` removes."""
        prior = {s.pattern: s.probability for s in ranking}
        keys = q.answer_keys
        mass = sum(prior.values())
        if not keys or mass <= 0:
            return 0.0
        prior = {p: v / mass for p, v in prior.items()}
        rows = {p: self._answer_table(q, p) for p in prior}
        expected = 0.0
        for k in keys:
            joint = {p: prior[p] * rows[p][k] for p in prior}
            p_answer = sum(joint.values())
            if p_answer > 0:
                expected += p_answer * _entropy([v / p_answer for v in joint.values()])
        return _entropy(list(prior.values())) - expected

    def next_question(self, evidence: TriageEvidence, ranking: Sequence[PatternScore],
                      ctx: AssessmentContext) -> TriageQuestion | None:
        if len(evidence.asked) >= self.max_questions:
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
        if ranking and max(s.probability for s in ranking) >= self.stop_probability:
            return None  # sure enough: no more information-gain questions
        best, best_gain = None, self.min_gain_bits  # 3. the most informative question
        for q in open_questions:
            if q.screening or q.answer_type == "reading" or (
                    q.signal is not None and not q.is_symptom_question and q.signal not in reported):
                continue
            gain = self.information_gain(q, ranking)
            if (best is None and gain >= best_gain) or gain > best_gain + 1e-12:
                best, best_gain = q, gain  # ties keep the bank's file order
        return best
