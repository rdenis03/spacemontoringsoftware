"""Train the ``bayes`` reasoner's tables on simulated missions (M15, task B24)::

    python -m orbit.learning.train_reasoner --seeds 1-20 --days 180 --crew 4 \
        --out orbit/learning/reasoner_weights.json

No scikit-learn needed: naive Bayes is counting.

Data. Per seed: the simulator with ``symptom_lookalikes=True`` and
``mild_illness_rate=0.3`` -> ``Pipeline`` on ``Store(":memory:")`` -> ingest.
Then, per **chat day** (``chat_days``; the days an astronaut would plausibly
describe symptoms), at 10:30 of that day:

    label                       chat days                              pattern
    --------------------------  -------------------------------------  -----------
    viral_reactivation (virus)  symptom day to half-way through        vzv_like, hsv1_like,
                                recovery (while there are symptoms)    ebv_like
    respiratory_infection       the same                               respiratory
    eva_exertion                the morning after the spacewalk        exertion
    sleep_shift                 every day of the shift                 sleep_loss
    stress_load                 every day of the look-alike            stress
    (no label)                  every 30th day from day 22, at least   other
                                3 days from any label of the astronaut

An illness wins when a look-alike falls on the same day. The evidence is
what the triage service would see: findings = that morning's 8 check-in
symptoms (0 = denied), preview = ``pipeline.assess(as_of, save=False)``
(contributors and anomalies), ``ctx.events``. ``observe`` from the module
turns it into clues, so training and run time read symptoms, anomalies,
wellbeing and the EVA the same way.

Labs are the exception (``lab_values``). ``observe`` only ever says "yes"
for a lab (a positive result); a missing result is unknown at run time. In
training, a lab counts on a chat day when the preview's recent window
(pipeline ``recent_days``, 3) holds a reading (``ctx.latest(signal)``), the
same reading the scorer shows: "yes" if the preview flags it (``observe``
gives the clue), "no" if not; no reading in the window is skipped, as at run
time. The window, not the chat day alone: a positive from 2 days ago is a
"yes" clue in the live triage too, so counting same-day readings only would
make training and run time disagree. Counting "no" on every day without a
positive result would teach "was a test done at all" (the simulator runs
extra tests only during an illness); counting only ``observe``'s clues would
never see a "no" and give every pattern the same (n + 1) / (n + 2). The saliva panel measures all three viruses at once, so
its negatives are real evidence. CRP is measured almost only on respiratory
days in the simulator, so its table stays near 0.5 for most patterns: an
honest "not enough data", not a finding.

Answers. For every chat day and every non-symptom question in the bank with
likelihoods, one answer is drawn from the bank's **hand-set** P(answer |
true pattern) with ``random.Random(answer_seed)``. So the answer tables only
re-learn the bank: an evaluation that uses answers measures consistency, not
medical truth (B24 reports "without answers" as the main comparison).

Smoothing. Laplace: P(v | pattern) = (count + 1) / (n + number of values);
priors the same over the 8 patterns. ``other_complaint`` is hand-set in the
module (the simulator has no complaints outside the 8 signals).

Seeds 101-105 are held out for the evaluation and refused. Deterministic:
the same arguments give the same file (LF line ends).

Arguments: ``--seeds`` (1-20), ``--days`` (180), ``--crew`` (4), ``--out``,
``--config`` (orbit.toml: its baseline, detector and scorer make the preview),
``--questions`` (cards/questions.jsonl), ``--answer-seed`` (1),
``--mild-illness-rate`` (0.3).
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from orbit.core import Pipeline, Store, create, load_settings
from orbit.core.interfaces import AssessmentContext, TriageEvidence
from orbit.modules.simulator import MissionSimulator
from orbit.schema import (
    ScenarioType,
    SignalType,
    SymptomFinding,
    TriagePattern,
    TriageQuestion,
    get_spec,
    parse_jsonl,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "reasoner_weights.json"
DEFAULT_CONFIG = ROOT / "orbit.toml"
DEFAULT_QUESTIONS = ROOT / "cards" / "questions.jsonl"
HELD_OUT_SEEDS = frozenset(range(101, 106))  # the same seeds as orbit/learning/train.py
FIRST_DAY = 22
OTHER_EVERY_DAYS = 30
OTHER_GAP_DAYS = 3
CHAT_TIME = timedelta(hours=10, minutes=30)
MILD_ILLNESS_RATE = 0.3
P = TriagePattern
T = ScenarioType
VIRUS_PATTERN = {"vzv": P.VZV_LIKE, "hsv1": P.HSV1_LIKE, "ebv": P.EBV_LIKE}


def parse_seeds(text: str) -> list[int]:
    """"1-20", "1,2,5" or "1-3,7", like ``orbit.learning.train.parse_seeds`` (which needs scikit-learn)."""
    seeds: set[int] = set()
    for part in filter(None, (p.strip() for p in text.split(","))):
        first, dash, last = part.partition("-")
        try:
            lo, hi = int(first), int(last) if dash else int(first)
        except ValueError:
            raise ValueError(f"bad seeds {text!r}: use 1-20, 1,2,5 or 1-3,7") from None
        if hi < lo:
            raise ValueError(f"bad seed range {part!r}: the end is before the start")
        seeds.update(range(lo, hi + 1))
    if not seeds:
        raise ValueError("no seeds given")
    return sorted(seeds)


def seeds_label(seeds: Sequence[int]) -> str:
    runs: list[list[int]] = []
    for s in sorted(set(seeds)):
        if runs and s == runs[-1][1] + 1:
            runs[-1][1] = s
        else:
            runs.append([s, s])
    return ".".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


@dataclass(frozen=True)
class ChatDay:
    astronaut_id: str
    mission_day: int
    pattern: TriagePattern
    label_id: str | None  # None for "other"


def chat_days(sim: MissionSimulator) -> list[ChatDay]:
    """The labelled days an astronaut would describe symptoms (table in the module docstring)."""
    taken: dict[tuple[str, int], ChatDay] = {}
    for e in sim.episodes:
        pattern = VIRUS_PATTERN[e.virus] if e.virus else P.RESPIRATORY
        label_id = e.label(sim.day_start).label_id
        for day in range(e.symptom_day, e.symptom_day + e.recovery_days // 2 + 1):
            if 1 <= day <= sim.days:
                taken.setdefault((e.astronaut_id, day), ChatDay(e.astronaut_id, day, pattern, label_id))
    for x in sim.lookalikes:
        if x.astronaut_id is None or not x.levels:
            continue
        pattern = {T.EVA_EXERTION: P.EXERTION, T.SLEEP_SHIFT: P.SLEEP_LOSS,
                   T.STRESS_LOAD: P.STRESS}.get(x.scenario)
        if pattern is None:
            continue
        days = [x.day + 1] if x.scenario is T.EVA_EXERTION else range(x.first_day, x.last_day + 1)
        label_id = f"{x.astronaut_id}-{x.scenario.value}-d{x.day:03d}"
        for day in days:
            if 1 <= day <= sim.days:
                taken.setdefault((x.astronaut_id, day), ChatDay(x.astronaut_id, day, pattern, label_id))
    busy: dict[str, set[int]] = {}
    for e in sim.episodes:
        busy.setdefault(e.astronaut_id, set()).update(range(e.first_day, e.last_day + 1))
    for x in sim.lookalikes:
        for m in sim.crew:
            if x.astronaut_id in (None, m.astronaut_id):
                busy.setdefault(m.astronaut_id, set()).update(range(x.first_day, x.last_day + 2))
    for m in sim.crew:
        for day in range(FIRST_DAY, sim.days + 1, OTHER_EVERY_DAYS):
            near = busy.get(m.astronaut_id, set())
            if not any(d in near for d in range(day - OTHER_GAP_DAYS, day + OTHER_GAP_DAYS + 1)):
                taken.setdefault((m.astronaut_id, day), ChatDay(m.astronaut_id, day, P.OTHER, None))
    return sorted(taken.values(), key=lambda c: (c.mission_day, c.astronaut_id))


def checkin_findings(ctx: AssessmentContext) -> tuple[SymptomFinding, ...]:
    """That morning's 8 check-in symptoms as findings (0 = denied)."""
    out = []
    for signal in SignalType:
        if get_spec(signal).category.value != "symptom":
            continue
        reading = ctx.latest(signal, within=timedelta(hours=12))
        level = int(reading.value) if reading is not None else 0
        out.append(SymptomFinding(signal=signal, label=get_spec(signal).label,
                                  severity=level, negated=level == 0))
    return tuple(out)


def simulated_mission(seed: int, days: int, crew: int, config: str | Path = DEFAULT_CONFIG,
                      mild_illness_rate: float = MILD_ILLNESS_RATE) -> tuple[MissionSimulator, Pipeline]:
    """The training/evaluation mission: symptom look-alikes on, some mild illnesses."""
    settings = replace(load_settings(config), sources=())
    sim = create("source", "simulator", days=days, crew_size=crew, seed=seed,
                 symptom_lookalikes=True, mild_illness_rate=mild_illness_rate)
    assert isinstance(sim, MissionSimulator)
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    pipeline.ingest(sim.read())
    return sim, pipeline


def chat_time(sim: MissionSimulator, day: int) -> datetime:
    return sim.day_start(day) + CHAT_TIME


def day_evidence(sim: MissionSimulator, pipeline: Pipeline,
                 chat: ChatDay) -> tuple[TriageEvidence, AssessmentContext]:
    as_of = chat_time(sim, chat.mission_day)
    preview = pipeline.assess(chat.astronaut_id, as_of, save=False)
    ctx = pipeline.context(chat.astronaut_id, as_of)
    evidence = TriageEvidence(findings=checkin_findings(ctx), answers=(), asked=(),
                              preview=preview.assessment, anomalies=tuple(preview.anomalies))
    return evidence, ctx


def sample_answer(q: TriageQuestion, pattern: TriagePattern, rng: random.Random) -> str:
    """One answer key drawn from the bank's hand-set P(answer | pattern)."""
    keys = q.answer_keys
    return rng.choices(keys, weights=[q.likelihood(pattern, k) for k in keys])[0]


def lab_values(clues: Sequence, ctx: AssessmentContext) -> dict[str, str]:
    """The lab clues to count on one chat day: "yes" (positive), "no" (measured negative).

    A lab counts when the preview's recent window (``ctx.recent``, pipeline
    ``recent_days``, 3) holds a reading, the same reading the scorer shows:
    "yes" if the preview flags it (``observe`` gave the clue), "no" if not.
    No reading in the window: left out (unknown), as at run time.
    """
    from orbit.modules.reasoner_bayes import CONTRIBUTOR_CLUES

    positive = {c.name for c in clues if c.name.startswith("lab:") and c.value == "yes"}
    out = {}
    for signal, name in CONTRIBUTOR_CLUES.items():
        if not name.startswith("lab:"):
            continue
        if name in positive:
            out[name] = "yes"
        elif ctx.latest(signal) is not None:
            out[name] = "no"
    return out


def iter_training(seeds: Sequence[int], days: int, crew: int, config: str | Path,
                  mild_illness_rate: float) -> Iterator[tuple[ChatDay, TriageEvidence, AssessmentContext]]:
    held_out = sorted(HELD_OUT_SEEDS.intersection(seeds))
    if held_out:
        raise ValueError(f"seeds {held_out} are held out for the evaluation (B24); never train on them")
    for seed in seeds:
        sim, pipeline = simulated_mission(seed, days, crew, config, mild_illness_rate)
        for chat in chat_days(sim):
            evidence, ctx = day_evidence(sim, pipeline, chat)
            yield chat, evidence, ctx


def train(seeds: Sequence[int], days: int = 180, crew: int = 4, out: str | Path = DEFAULT_OUT,
          config: str | Path = DEFAULT_CONFIG, questions: str | Path = DEFAULT_QUESTIONS,
          answer_seed: int = 1, mild_illness_rate: float = MILD_ILLNESS_RATE) -> dict:
    from orbit.modules.reasoner_bayes import OTHER_CLUE, clue_names, clue_values, observe

    seeds = sorted(set(seeds))
    bank = parse_jsonl(questions, TriageQuestion).raise_if_errors()
    asked = [q for q in bank if not q.is_symptom_question and q.likelihoods and q.answer_keys]
    names = [n for n in clue_names() if n != OTHER_CLUE]
    counts = {n: {p: {v: 0 for v in clue_values(n)} for p in P} for n in names}
    answer_counts = {q.question_id: {p: {k: 0 for k in q.answer_keys} for p in P} for q in asked}
    pattern_counts = {p: 0 for p in P}
    rng = random.Random(answer_seed)
    for chat, evidence, ctx in iter_training(seeds, days, crew, config, mild_illness_rate):
        pattern_counts[chat.pattern] += 1
        clues = observe(evidence, ctx)
        for clue in clues:
            if clue.name in counts and not clue.name.startswith("lab:"):
                counts[clue.name][chat.pattern][clue.value] += 1
        for name, value in lab_values(clues, ctx).items():  # measured labs only (docstring)
            counts[name][chat.pattern][value] += 1
        for q in asked:
            answer_counts[q.question_id][chat.pattern][sample_answer(q, chat.pattern, rng)] += 1
    if not any(pattern_counts.values()):
        raise ValueError("no chat days; use more seeds or more days")
    # A pattern without chat days (small runs) gets uniform tables from the smoothing.

    def smooth(row: dict[str, int]) -> dict[str, float]:
        total = sum(row.values()) + len(row)
        return {k: round((v + 1) / total, 6) for k, v in row.items()}

    from orbit.modules.reasoner_bayes import OTHER_COMPLAINT_TABLE

    total = sum(pattern_counts.values()) + len(P)
    features = {n: {p.value: smooth(counts[n][p]) for p in P} for n in names}
    features[OTHER_CLUE] = OTHER_COMPLAINT_TABLE
    features = {n: features[n] for n in clue_names()}
    version = f"s{seeds_label(seeds)}-d{days}-c{crew}"
    if mild_illness_rate != MILD_ILLNESS_RATE:
        version += f"-m{mild_illness_rate:g}"
    doc = {
        "version": version,
        "priors": {p.value: round((pattern_counts[p] + 1) / total, 6) for p in P},
        "features": features,
        "answers": {qid: {p.value: smooth(rows[p]) for p in P} for qid, rows in answer_counts.items()},
        "trained_on": {
            "simulated": True,
            "seeds": list(seeds),
            "days": days,
            "crew": crew,
            "symptom_lookalikes": True,
            "mild_illness_rate": mild_illness_rate,
            "answer_seed": answer_seed,
            "chat_days": {p.value: pattern_counts[p] for p in P},
            "answers_from": "hand-set likelihoods in the question bank (sampled)",
        },
        "notes": ("Naive Bayes tables counted on simulated chat days with Laplace smoothing (B24). "
                  "Answer tables are sampled from the bank's hand-set likelihoods, so they measure "
                  "consistency, not medical truth. Illustrative, not clinical."),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(doc, indent=1) + "\n")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orbit.learning.train_reasoner",
                                     description="Count the bayes reasoner's tables on simulated missions.")
    parser.add_argument("--seeds", default="1-20")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--crew", type=int, default=4)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--answer-seed", type=int, default=1)
    parser.add_argument("--mild-illness-rate", type=float, default=MILD_ILLNESS_RATE)
    args = parser.parse_args(argv)
    try:
        doc = train(parse_seeds(args.seeds), args.days, args.crew, args.out, args.config,
                    args.questions, args.answer_seed, args.mild_illness_rate)
    except ValueError as exc:
        parser.error(str(exc))
    days = doc["trained_on"]["chat_days"]
    print(f"bayes-{doc['version']}: {sum(days.values())} chat days "
          + ", ".join(f"{k} {v}" for k, v in days.items()))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
