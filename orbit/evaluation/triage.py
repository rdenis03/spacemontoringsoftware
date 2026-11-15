"""Triage evaluation (M15, task B24): starters vs learned modules, and the switch rules.

    python -m orbit.evaluation.triage --config orbit.toml \\
        --config experiments/triage_learned.toml --seeds 101-105 --days 180 --crew 4 \\
        --out reports/triage_eval.json

Each ``--config`` names its ``[triage]`` extractor and reasoner; the first is the
baseline (the starters), the others are compared with it. Four parts:

1. **Extractor** on ``tests/fixtures/triage/human_sentences.jsonl``. **Provisional**:
   that file is a 20-line stub written by the same author as the training
   templates, not by people who never saw them. Per symptom, F1 of "present"
   (mentioned and not denied): F1 = 2 x precision x recall / (precision + recall).
   Macro F1 = their mean. Negation accuracy: share of the gold mentions found
   with the right ``negated``; a missed mention counts as wrong. Severity within
   one: share of gold present symptoms with a gold severity whose found severity
   (None counts as 1, as confirm stores it) is at most one level off.
2. **Red flags**: recall on the ``fires`` lines of
   ``tests/fixtures/triage/red_flag_sentences.jsonl`` and false fires on the
   others. The gate runs on the raw text before any model, so it does not
   depend on the extractor or reasoner; it is reported per config anyway.
3. **Reasoner** on simulated chats (seeds 101-105, never trained on): the
   simulator with ``symptom_lookalikes`` and ``mild_illness_rate`` 0.3, the
   chat days of ``orbit.learning.train_reasoner.chat_days`` (episode days with
   a known pattern). The message describes that morning's check-in symptoms
   (``utterances.describe``, seeded). Both reasoners read it with the same
   extractor (``lexicon``), so only the reasoner differs. Answers: a symptom
   question gets the true check-in level; a screening question "no" (red flags
   are part 2); any other question an answer drawn from the bank's **hand-set**
   P(answer | true pattern), seeded per seed, chat and question, so both
   reasoners get the same answer to the same question.

   * ``without_answers`` (**the main comparison**): the ranking after the
     first message: symptoms from the text, vitals, labs and events only.
   * ``with_answers``: the final ranking after the questions. The answers are
     drawn from the same hand-set likelihoods the bayes tables learned, so this
     measures consistency with the bank, not medical truth.

   Metrics: top-1 and top-3 (true pattern first / in the first three), Brier
   score (sum over the 8 patterns of (probability - 1 if true else 0)^2; 0 is
   perfect, 2 the worst), and questions per session. Also per true pattern.
4. **M9 with chats**: per seed the same mission through ``Pipeline.run()``
   (10:00 every day), then a confirmed chat at 10:30 on every chat day with the
   config's own extractor and reasoner. Sensitivity, lead time (median whole
   days) and false alarms per 30 astronaut-days, as M9 (``evaluate``), with and
   without the chats.

``switch`` checks the rules in ``tasks/B24-triage-ml.md`` for each compared
config and gives a recommendation. ``text_linear`` is never recommended while
the human sentences are the stub. All numbers come from simulated missions and
hand-set likelihoods: illustrative, not clinical.
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from statistics import mean, median

from orbit.core import load_settings
from orbit.core.config import ModuleChoice
from orbit.evaluation.metrics import evaluate
from orbit.evaluation.runner import lead_times_days
from orbit.learning.train_reasoner import (
    ChatDay,
    chat_days,
    chat_time,
    checkin_findings,
    parse_seeds,
    simulated_mission,
)
from orbit.learning.utterances import describe
from orbit.schema import SignalCategory, SignalType, TriagePattern, TriageQuestion, TriageStatus, get_spec
from orbit.triage.config import load_triage_settings
from orbit.triage.red_flags import RedFlagRules
from orbit.triage.service import TriageService

ROOT = Path(__file__).resolve().parents[2]
HUMAN_SENTENCES = ROOT / "tests" / "fixtures" / "triage" / "human_sentences.jsonl"
RED_FLAG_SENTENCES = ROOT / "tests" / "fixtures" / "triage" / "red_flag_sentences.jsonl"
LEXICON = ROOT / "cards" / "symptom_lexicon.jsonl"
SYMPTOMS = tuple(s for s in SignalType if get_spec(s).category is SignalCategory.SYMPTOM)
HUMAN_STUB_SOURCE = "stub-claude"
NOTE = ("Simulated missions and hand-set answer likelihoods: the reasoner numbers measure "
        "consistency with the question bank, not medical truth. Extractor numbers are "
        "provisional (20-line stub, same author as the templates). Illustrative, not clinical.")
P = TriagePattern


# ---- 1. extractor ---------------------------------------------------------------------


def _lines(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if "_comment" not in r]


def extractor_metrics(extractor, path: Path = HUMAN_SENTENCES) -> dict:
    rows = _lines(path)
    tp = {s: 0 for s in SYMPTOMS}
    fp, fn = dict(tp), dict(tp)
    negation_right = negation_total = severity_right = severity_total = 0
    for row in rows:
        gold = {SignalType(k): v for k, v in row["findings"].items()}
        found = {f.signal: f for f in extractor.read(row["text"]) if f.signal is not None}
        for s in SYMPTOMS:
            g = s in gold and not gold[s]["negated"]
            f = s in found and not found[s].negated
            tp[s] += g and f
            fp[s] += f and not g
            fn[s] += g and not f
        for s, g in gold.items():
            negation_total += 1
            negation_right += s in found and found[s].negated == g["negated"]
            if not g["negated"] and g["severity"] is not None:
                severity_total += 1
                got = found.get(s)
                level = None if got is None or got.negated else (got.severity or 1)
                severity_right += level is not None and abs(level - g["severity"]) <= 1

    def f1(s: SignalType) -> float | None:
        if tp[s] + fp[s] + fn[s] == 0:
            return None
        return 2 * tp[s] / (2 * tp[s] + fp[s] + fn[s])

    per = {s.value: f1(s) for s in SYMPTOMS}
    present = [v for v in per.values() if v is not None]
    return {
        "provisional": True,
        "sentences": len(rows),
        "sources": sorted({r.get("source", "?") for r in rows}),
        "f1": per,
        "macro_f1": mean(present) if present else None,
        "negation_accuracy": negation_right / negation_total if negation_total else None,
        "severity_within_one": severity_right / severity_total if severity_total else None,
    }


# ---- 2. red flags ---------------------------------------------------------------------


def red_flag_metrics(rules: RedFlagRules, path: Path = RED_FLAG_SENTENCES) -> dict:
    rows = _lines(path)
    positive = [r for r in rows if r["fires"]]
    negative = [r for r in rows if not r["fires"]]
    missed = [r["text"] for r in positive if not rules.check_text(r["text"])]
    false_fires = [r["text"] for r in negative if rules.check_text(r["text"])]
    return {"positive": len(positive), "negative": len(negative),
            "recall": (len(positive) - len(missed)) / len(positive) if positive else None,
            "missed": missed, "false_fires": len(false_fires),
            "note": "the gate runs on the raw text before any model"}


# ---- 3 and 4. simulated chats ---------------------------------------------------------


def _answer(q: TriageQuestion, chat: ChatDay, levels: dict[SignalType, int], seed: int, index: int):
    if q.is_symptom_question:
        return levels.get(q.signal, 0)
    if q.screening:
        return False
    keys = q.answer_keys
    if not keys:
        return None
    rng = random.Random(f"answer-{seed}-{index}-{q.question_id}")
    key = rng.choices(keys, weights=[q.likelihood(chat.pattern, k) for k in keys])[0]
    return {"yes": True, "no": False}.get(key, key)


def _brier(ranking, truth: TriagePattern) -> float:
    probs = {s.pattern: s.probability for s in ranking}
    return sum((probs.get(p, 0.0) - (p is truth)) ** 2 for p in P)


def _score(ranking, truth: TriagePattern) -> dict:
    order = [s.pattern for s in ranking]
    return {"top1": bool(order) and order[0] is truth, "top3": truth in order[:3],
            "brier": _brier(ranking, truth)}


def run_chat(service: TriageService, sim, chat: ChatDay, seed: int, index: int,
             confirm: bool) -> dict:
    """One simulated chat. Returns the first and final scores and the questions asked."""
    as_of = chat_time(sim, chat.mission_day)
    ctx = service.pipeline.context(chat.astronaut_id, as_of)
    levels = {f.signal: f.severity for f in checkin_findings(ctx)}
    text = describe(levels, random.Random(f"text-{seed}-{index}"), LEXICON)
    first = result = service.start(chat.astronaut_id, text, timestamp=as_of)
    asked = 0
    while result.status is TriageStatus.ASKING and result.next_question is not None and asked < 10:
        q = result.next_question
        result = service.answer(result.session_id, question_id=q.question_id,
                                value=_answer(q, chat, levels, seed, index))
        asked += 1
    if confirm and result.status in (TriageStatus.ASKING, TriageStatus.READY):
        result, _ = service.confirm(result.session_id)
    elif not confirm and result.status in (TriageStatus.ASKING, TriageStatus.READY):
        service.cancel(result.session_id)
    return {"pattern": chat.pattern.value, "without": _score(first.ranking, chat.pattern),
            "with": _score(result.ranking, chat.pattern), "questions": asked,
            "errors": list(result.errors)}


def _summary(chats: Sequence[dict], key: str) -> dict:
    if not chats:
        return {"n": 0, "top1": None, "top3": None, "brier": None}
    return {"n": len(chats),
            "top1": mean(c[key]["top1"] for c in chats),
            "top3": mean(c[key]["top3"] for c in chats),
            "brier": mean(c[key]["brier"] for c in chats)}


def _m9(pipeline, sim, labels, astronaut_days: int) -> dict:
    assessments = [a for m in sim.crew for a in pipeline.store.assessments(m.astronaut_id)]
    result = evaluate(assessments, labels, astronaut_days=astronaut_days)
    days = lead_times_days(assessments, labels)
    return {"sensitivity": result["sensitivity"],
            "lead_time_days_median": median(days) if days else None,
            "false_alarms_per_30_days": result["false_alarms"]["per_30_days"],
            "false_alarms": result["false_alarms"]["count"],
            "detected": result["detected"], "should_alert": result["labels"]["should_alert"]}


def _service(config: str | Path, pipeline, extractor: ModuleChoice | None = None) -> TriageService:
    ts = load_triage_settings(load_settings(config))
    if extractor is not None:
        ts = replace(ts, extractor=extractor)
    return TriageService.from_settings(ts, pipeline)


def simulated(config: str | Path, seed: int, days: int, crew: int) -> dict:
    """Parts 3 and 4 for one config and one seed."""
    # Part 3: every reasoner reads the chat with the same extractor.
    sim, pipeline = simulated_mission(seed, days, crew, config)
    report = pipeline.run()
    labels = sim.labels()
    before = _m9(pipeline, sim, labels, report.assessed)
    same_extractor = ModuleChoice("lexicon", {"lexicon_path": str(LEXICON)})
    service = _service(config, pipeline, same_extractor)
    chats = chat_days(sim)
    reasoner = [run_chat(service, sim, c, seed, i, confirm=False) for i, c in enumerate(chats)]
    # Part 4: the config's own modules, confirmed chats, then M9 again.
    own = _service(config, pipeline)
    confirmed = [run_chat(own, sim, c, seed, i, confirm=True) for i, c in enumerate(chats)]
    after = _m9(pipeline, sim, labels, report.assessed)
    return {"seed": seed, "chats": reasoner, "confirmed_errors": sum(bool(c["errors"]) for c in confirmed),
            "m9_without_chats": before, "m9_with_chats": after}


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return mean(present) if present else None


def evaluate_config(config: str | Path, seeds: Sequence[int], days: int, crew: int,
                    progress: Callable[[str], None] | None = None) -> dict:
    settings = load_settings(config)
    ts = load_triage_settings(settings)
    from orbit.core import create  # modules are built here only for parts 1 and 2

    extractor = create("extractor", ts.extractor.use, **ts.extractor.options)
    runs = []
    for seed in seeds:
        run = simulated(config, seed, days, crew)
        runs.append(run)
        if progress:
            progress(f"{Path(config).name} seed {seed}: {len(run['chats'])} chats")
    chats = [c for run in runs for c in run["chats"]]
    by_pattern = {}
    for p in P:
        group = [c for c in chats if c["pattern"] == p.value]
        by_pattern[p.value] = {"without_answers": _summary(group, "without"),
                               "with_answers": _summary(group, "with")}
    m9 = {}
    for key in ("m9_without_chats", "m9_with_chats"):
        m9[key] = {name: _mean([run[key][name] for run in runs])
                   for name in ("sensitivity", "lead_time_days_median", "false_alarms_per_30_days")}
        m9[key]["detected"] = sum(run[key]["detected"] for run in runs)
        m9[key]["should_alert"] = sum(run[key]["should_alert"] for run in runs)
        m9[key]["false_alarms"] = sum(run[key]["false_alarms"] for run in runs)
    return {
        "config": str(config).replace("\\", "/"),
        "modules": {"extractor": ts.extractor.use, "reasoner": ts.reasoner.use},
        "extractor": extractor_metrics(extractor),
        "red_flags": red_flag_metrics(RedFlagRules.load(ts.red_flags_path)),
        "reasoner": {
            "extractor_used": "lexicon",
            "without_answers": _summary(chats, "without"),
            "with_answers": _summary(chats, "with"),
            "questions_per_session": mean(c["questions"] for c in chats) if chats else None,
            "chat_errors": sum(bool(c["errors"]) for c in chats),
            "by_pattern": by_pattern,
        },
        "m9": m9,
        "confirmed_chat_errors": sum(run["confirmed_errors"] for run in runs),
    }


# ---- switch rules ---------------------------------------------------------------------


def _better(new, old, lower_is_better: bool = False) -> bool | None:
    if new is None or old is None:
        return None
    return new < old if lower_is_better else new > old


def switch_rules(base: dict, other: dict) -> dict:
    be, oe = base["extractor"], other["extractor"]
    br, orr = base["reasoner"], other["reasoner"]
    bm, om = base["m9"]["m9_with_chats"], other["m9"]["m9_with_chats"]
    stub = HUMAN_STUB_SOURCE in oe["sources"]
    extractor_rule = {
        "beats_on_f1": _better(oe["macro_f1"], be["macro_f1"]),
        "beats_on_negation": _better(oe["negation_accuracy"], be["negation_accuracy"]),
        "misses_no_red_flag": other["red_flags"]["recall"] == 1.0,
        "human_sentences_are_the_stub": stub,
    }
    reasoner_rule = {}
    for key in ("without_answers", "with_answers"):
        reasoner_rule[key] = {
            "beats_on_top1": _better(orr[key]["top1"], br[key]["top1"]),
            "beats_on_top3": _better(orr[key]["top3"], br[key]["top3"]),
            "beats_on_brier": _better(orr[key]["brier"], br[key]["brier"], lower_is_better=True),
        }
    reasoner_rule["no_more_questions"] = orr["questions_per_session"] <= br["questions_per_session"]
    m9_rule = {
        "sensitivity_no_worse": om["sensitivity"] >= bm["sensitivity"],
        "lead_time_no_worse": (om["lead_time_days_median"] or 0) >= (bm["lead_time_days_median"] or 0),
        "false_alarms_no_worse": om["false_alarms_per_30_days"] <= bm["false_alarms_per_30_days"],
    }
    extractor_ok = all(v for k, v in extractor_rule.items() if k != "human_sentences_are_the_stub")
    primary = reasoner_rule["without_answers"]
    reasoner_ok = all(primary.values()) and reasoner_rule["no_more_questions"]
    m9_ok = all(m9_rule.values())
    return {
        "extractor": {**extractor_rule, "passes": extractor_ok,
                      "recommend_switch": extractor_ok and m9_ok and not stub,
                      "why": ("not until about 200 human-written sentences replace the stub"
                              if stub else None)},
        "reasoner": {**reasoner_rule, "passes_on_main_comparison": reasoner_ok,
                     "recommend_switch": reasoner_ok and m9_ok,
                     "main_comparison": "without_answers (with_answers is circular: hand-set likelihoods)"},
        "m9": {**m9_rule, "passes": m9_ok},
        "demo_story": "checked by tests/test_pipeline.py; orbit.toml is unchanged",
    }


def run_all(configs: Sequence[str | Path], seeds: Sequence[int], days: int = 180, crew: int = 4,
            progress: Callable[[str], None] | None = print) -> dict:
    results = [evaluate_config(c, seeds, days, crew, progress) for c in configs]
    return {
        "simulated": True,
        "note": NOTE,
        "settings": {"days": days, "crew": crew, "seeds": list(seeds),
                     "simulator": {"symptom_lookalikes": True, "mild_illness_rate": 0.3}},
        "configs": results,
        "switch": {r["config"]: switch_rules(results[0], r) for r in results[1:]},
    }


def _fmt(value, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def table(report: dict) -> str:
    rows = [("Config", "Extractor", "macro F1*", "Negation*", "Reasoner", "Top-1 (no ans.)",
             "Top-3 (no ans.)", "Brier (no ans.)", "Top-1 (ans.)", "Questions", "Sens.", "FA/30 d")]
    for c in report["configs"]:
        r, m = c["reasoner"], c["m9"]["m9_with_chats"]
        rows.append((Path(c["config"]).name, c["modules"]["extractor"], _fmt(c["extractor"]["macro_f1"]),
                     _fmt(c["extractor"]["negation_accuracy"]), c["modules"]["reasoner"],
                     _fmt(r["without_answers"]["top1"]), _fmt(r["without_answers"]["top3"]),
                     _fmt(r["without_answers"]["brier"]), _fmt(r["with_answers"]["top1"]),
                     _fmt(r["questions_per_session"], 1), _fmt(m["sensitivity"]),
                     _fmt(m["false_alarms_per_30_days"])))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    s = report["settings"]
    lines += ["", f"Simulated: {s['days']} days x {s['crew']} crew, seeds {s['seeds']}. "
              "* provisional (20-line stub). " + NOTE]
    for config, rules in report["switch"].items():
        lines.append(f"{config}: switch extractor? {rules['extractor']['recommend_switch']}; "
                     f"switch reasoner? {rules['reasoner']['recommend_switch']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(prog="python -m orbit.evaluation.triage",
                                     description="Evaluate the triage modules (M15) on simulated chats.")
    parser.add_argument("--config", action="append", default=None,
                        help="config to evaluate; the first is the baseline (default: orbit.toml)")
    parser.add_argument("--seeds", default="101-105")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--crew", type=int, default=4)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    configs = args.config or ["orbit.toml"]
    report = run_all(configs, parse_seeds(args.seeds), args.days, args.crew)
    print()
    print(table(report))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        print(f"\nReport written to {out}")
    return report


if __name__ == "__main__":
    main()
