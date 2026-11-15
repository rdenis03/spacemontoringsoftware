"""Evaluation runner (M9, task B06): whole simulated missions through ORBIT.

For every config and seed: load the config, replace its sources with the
simulator (``days``, ``crew_size``, ``seed``; everything else default, so
illnesses, look-alikes and faults are random), build a fresh pipeline on an
in-memory store, ingest, run, and score the assessments against the
simulator's labels with ``evaluate`` (B05). Nothing is reused between runs,
and every config sees identical data for a given seed.

Lead time is reported two ways:

* ``lead_time_days``: whole calendar days, the headline in the printed table:
  ``(symptom_onset.date() - first_alert.assessed_at.date()).days`` in UTC, so
  an alert on symptom day is 0 and the day before is 1.
* ``lead_time``: the exact SPEC value from ``evaluate`` (an alert at 10:00 the
  day before a 07:00 symptom onset is 0.875).

Report (``run_all`` returns it; ``--out`` writes it as JSON)::

    {
      "simulated": true,
      "settings": {"days": 180, "crew": 4, "seeds": [1, 2, 3, 4, 5], "min_level": "yellow"},
      "configs": [
        {
          "config": "orbit.toml",                 # file name, as shown in the table
          "path": "C:/.../orbit.toml",
          "modules": {"baseline": "rolling_median", ...},
          "runs": [                               # one per seed
            {"seed": 1, "observations": 13928, "seconds": 2.1,
             "lead_times_days": [1, 0, ...],      # calendar days, per detected label
             "lead_time_days": {"n", "median", "min", "max"},
             ...every key of evaluate() (see orbit/evaluation/metrics.py)...},
          ],
          "mean": {"sensitivity": {"mean": 0.95, "sd": 0.05, "n": 5},   # sd None if n < 2
                   "lead_time_days_median": {...}, "lead_time_exact_median": {...},
                   "false_alarms_per_30_days": {...}, "confounder_alert_rate": {...}},
          "by_scenario": {"viral_reactivation": {"labels": 31, "alerted": 29,
                                                 "rate": 0.94, "rate_mean": {...}}, ...},
        },
      ],
    }

Seeds with no value for a metric (for example no illness, so no sensitivity)
are left out of its mean, and ``n`` says how many seeds counted. The numbers
come from simulated missions; they are not clinical results.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from statistics import mean, stdev

from orbit.core import Pipeline, Store, create, load_settings
from orbit.core.config import ModuleChoice
from orbit.evaluation.metrics import alerts, evaluate, summary
from orbit.modules.simulator import MissionSimulator
from orbit.schema import AlertLevel, RiskAssessment, ScenarioLabel

HEADLINE = {
    "sensitivity": lambda run: run["sensitivity"],
    "lead_time_days_median": lambda run: run["lead_time_days"]["median"],
    "lead_time_exact_median": lambda run: run["lead_time"]["median"],
    "false_alarms_per_30_days": lambda run: run["false_alarms"]["per_30_days"],
    "confounder_alert_rate": lambda run: run["confounder_alert_rate"],
}


def lead_times_days(assessments: Iterable[RiskAssessment], labels: Iterable[ScenarioLabel],
                    min_level: AlertLevel | str = AlertLevel.YELLOW) -> list[int]:
    """Whole calendar days from the first alert in the window to symptom onset (UTC)."""
    found = alerts(assessments, min_level)
    out = []
    for label in labels:
        if not label.should_alert or label.symptom_onset is None:
            continue
        start, end = label.window()
        first = next((a for a in found if a.astronaut_id == label.astronaut_id
                      and start <= a.assessed_at <= end), None)
        if first is not None:
            out.append((label.symptom_onset.date() - first.assessed_at.date()).days)
    return out


def run_one(config: str | Path, seed: int, days: int = 180, crew: int = 4,
            min_level: AlertLevel | str = AlertLevel.YELLOW) -> dict:
    """One simulated mission through one config. Returns evaluate() plus run details."""
    started = time.perf_counter()
    options = {"days": days, "crew_size": crew, "seed": seed}
    settings = replace(load_settings(config), sources=(ModuleChoice("simulator", options),))
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    simulator = create("source", "simulator", **options)
    assert isinstance(simulator, MissionSimulator)
    batch = simulator.read()
    pipeline.ingest(batch)
    report = pipeline.run()
    assessments = [r.assessment for r in report.results if r.assessment is not None]
    labels = simulator.labels()

    result = evaluate(assessments, labels, min_level, astronaut_days=report.assessed)
    days_lead = lead_times_days(assessments, labels, min_level)
    return {
        "seed": seed,
        "observations": len(batch.observations),
        "events": len(batch.events),
        "failed_stages": report.failed_stages,
        "seconds": round(time.perf_counter() - started, 2),
        "lead_times_days": days_lead,
        "lead_time_days": summary(days_lead),
        **result,
    }


def _mean_sd(values: Sequence[float | None]) -> dict:
    present = [v for v in values if v is not None]
    return {
        "mean": mean(present) if present else None,
        "sd": stdev(present) if len(present) >= 2 else None,
        "n": len(present),
    }


def summarise(runs: Sequence[dict]) -> tuple[dict, dict]:
    """(mean ± SD of the headline numbers, per-scenario totals) over seeds."""
    headline = {name: _mean_sd([get(run) for run in runs]) for name, get in HEADLINE.items()}
    by_scenario: dict[str, dict] = {}
    for scenario in sorted({s for run in runs for s in run["by_scenario"]}):
        rows = [run["by_scenario"].get(scenario) for run in runs]
        labels = sum(r["labels"] for r in rows if r)
        alerted = sum(r["alerted"] for r in rows if r)
        by_scenario[scenario] = {
            "labels": labels, "alerted": alerted, "rate": alerted / labels if labels else None,
            "rate_mean": _mean_sd([r["rate"] if r else None for r in rows]),
        }
    return headline, by_scenario


def run_all(configs: Sequence[str | Path], seeds: Sequence[int], days: int = 180, crew: int = 4,
            min_level: AlertLevel | str = AlertLevel.YELLOW,
            progress: Callable[[str], None] | None = print) -> dict:
    """Every config x seed. Returns the report documented in the module docstring."""
    level = AlertLevel(min_level)
    out = []
    total, done = len(configs) * len(seeds), 0
    for config in configs:
        settings = load_settings(config)
        runs = []
        for seed in seeds:
            run = run_one(config, seed, days, crew, level)
            runs.append(run)
            done += 1
            if progress:
                progress(f"[{done}/{total}] {Path(config).name} seed {seed}: "
                         f"sensitivity {_fmt(run['sensitivity'])}, "
                         f"{run['false_alarms']['count']} false alarms ({run['seconds']} s)")
        headline, by_scenario = summarise(runs)
        out.append({
            "config": Path(config).name,
            "path": str(settings.config_path) if settings.config_path else str(config),
            "modules": {slot: choice.use for slot, choice in settings.modules.items()},
            "runs": runs,
            "mean": headline,
            "by_scenario": by_scenario,
        })
    return {
        "simulated": True,
        "settings": {"days": days, "crew": crew, "seeds": list(seeds), "min_level": level.value},
        "configs": out,
    }


# ---- printing -----------------------------------------------------------------


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _cell(stat: dict, digits: int = 2) -> str:
    if stat["mean"] is None:
        return "n/a"
    sd = "" if stat["sd"] is None else f" ± {stat['sd']:.{digits}f}"
    return f"{stat['mean']:.{digits}f}{sd}"


def table(report: dict) -> str:
    """The printed comparison: one row per config, mean ± SD over seeds."""
    header = ("Config", "Modules", "Sensitivity", "Lead time (days)",
              "False alarms / 30 d", "Confounder alert rate")
    rows = [header]
    for entry in report["configs"]:
        m = entry["mean"]
        modules = ", ".join(f"{slot}={name}" for slot, name in entry["modules"].items()
                            if slot in ("baseline", "detector", "scorer"))
        rows.append((entry["config"], modules, _cell(m["sensitivity"]),
                     _cell(m["lead_time_days_median"], 1),
                     _cell(m["false_alarms_per_30_days"]), _cell(m["confounder_alert_rate"])))
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    s = report["settings"]
    lines.append("")
    lines.append(f"Simulated missions: {s['days']} days x {s['crew']} crew, seeds "
                 f"{' '.join(map(str, s['seeds']))}, alert = {s['min_level']} or worse. "
                 "Lead time: median whole days before symptom day (0 = on symptom day).")
    return "\n".join(lines)
