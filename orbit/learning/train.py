"""Train the learned scorer on simulated missions (M8, task B09).

The simulator knows when each astronaut was really ill, so the scorer's
weights can be learned instead of hand-set. The model is a logistic regression:
one weight per feature (B07), so every point keeps a plain reason. The result
is written in the weights format of the learned scorer (B08), which needs no
machine-learning library at runtime. Only this file imports scikit-learn::

    pip install -e ".[dev,train]"
    python -m orbit.learning.train --seeds 1-20 --days 180 --crew 4 \
        --out orbit/learning/weights.json

Dataset. Per seed: simulator -> ``Pipeline`` on ``Store(":memory:")`` -> ingest.
For each astronaut and mission day from day 22 (``FIRST_DAY``; no illness
starts earlier and the baseline needs history) at the assessment hour: the
pipeline's own baseline and detector give the anomalies, and
``x = vector(extract(ctx, anomalies))``. ``y = 1`` when that moment falls in
the ``window()`` of a ``should_alert`` label of that astronaut, else 0, so
look-alike days (spacewalks, sleep shifts, solar events, sensor faults) are 0.
Features come from reading values only, never from whether a test exists.

Fit. ``LogisticRegression(max_iter=1000)``, by default without class weights,
so the model's probability follows how often illness really occurs in the
simulated missions (``--class-weight balanced`` gives the first B09 fit). Weights
must be >= 0 (a reason can only add points), so features with a negative
coefficient are dropped and the model is refitted, up to ``MAX_ROUNDS`` (10)
times; anything still negative after that is set to 0. Features that were
never non-zero in training get weight 0.

Points. The intercept ``b0`` must be negative (a day with no findings is
healthy). With ``p`` = ``--yellow-probability`` and ``logit(p) = ln(p / (1 - p))``:
``scale = 25 / (logit(p) - b0)`` and ``weight = round(scale x coefficient, 3)``,
so a score of 25 (yellow) means the model's probability of illness is ``p``.
The file's own ``scale`` field stays 1.0: the weights are already in points.

Calibration (why p = 0.92 and no class weights). The first B09 fit used
balanced classes and p = 0.5. Balancing makes rare illness look common, so
vital signs alone reached 100 points: 0.2 false alarms per 30 days, and the
demo astronaut went straight to red. Tried on validation seeds 21-25 (never on
the held-out 101-105): without class weights, p = 0.92 gives no false alarms,
a median warning 0.77 days before symptoms (rule_based: 0.63), and yellow then
orange in the demo story. Lower p warns a little earlier but turns the demo
red (p = 0.5: orange then red, 0.03 false alarms per 30 days).

Deterministic: the same arguments give the same file. The version comes from
the arguments (``trained-s1-20-d180-c4``; ``-p50`` and ``-bal`` are added for a
non-default probability or balanced classes), never from the clock.

Seeds 101 to 105 are held out for the evaluation (B10) and are refused here.
The weights are learned from simulated data; they are illustrative, not clinical.

Arguments:

    --seeds    1-20                          simulator seeds: "1-20", "1,2,5" or "1-3,7"
    --days     180                           mission length per seed
    --crew     4                             astronauts per mission
    --out      orbit/learning/weights.json   where to write the weights
    --config   orbit.toml                    config whose baseline, detector and
                                             pipeline settings make the features
    --yellow-probability  0.92               model probability that earns 25 points
    --class-weight        none               "none" or "balanced"
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from orbit.core import Pipeline, Store, create, load_settings
from orbit.learning.features import FEATURE_NAMES, extract, vector
from orbit.modules.simulator import MissionSimulator

FIRST_DAY = 22
MAX_ROUNDS = 10
YELLOW_POINTS = 25.0  # the score at which the model's probability is YELLOW_PROBABILITY
YELLOW_PROBABILITY = 0.92
HELD_OUT_SEEDS = frozenset(range(101, 106))  # B10 evaluates on these
DEFAULT_OUT = Path(__file__).resolve().parent / "weights.json"
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "orbit.toml"


def parse_seeds(text: str) -> list[int]:
    """"1-20", "1,2,5" or "1-3,7" as a sorted list without repeats."""
    seeds: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        first, dash, last = part.partition("-")
        try:
            lo = int(first)
            hi = int(last) if dash else lo
        except ValueError:
            raise ValueError(f"bad seeds {text!r}: use 1-20, 1,2,5 or 1-3,7") from None
        if hi < lo:
            raise ValueError(f"bad seed range {part!r}: the end is before the start")
        seeds.update(range(lo, hi + 1))
    if not seeds:
        raise ValueError("no seeds given")
    return sorted(seeds)


def seeds_label(seeds: Sequence[int]) -> str:
    """Short text for the version: [1..20] -> "1-20", [1, 2, 3, 7] -> "1-3.7"."""
    runs: list[tuple[int, int]] = []
    for seed in sorted(set(seeds)):
        if runs and seed == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], seed)
        else:
            runs.append((seed, seed))
    return ".".join(str(lo) if lo == hi else f"{lo}-{hi}" for lo, hi in runs)


def dataset(seeds: Sequence[int], days: int, crew: int,
            config: str | Path = DEFAULT_CONFIG) -> tuple[np.ndarray, np.ndarray]:
    """(X, y): one row per astronaut-day from ``FIRST_DAY``, columns in ``FEATURE_NAMES`` order."""
    held_out = sorted(HELD_OUT_SEEDS.intersection(seeds))
    if held_out:
        raise ValueError(f"seeds {held_out} are held out for the evaluation (B10); "
                         "never train on them")
    settings = replace(load_settings(config), sources=())
    rows: list[list[float]] = []
    target: list[int] = []
    for seed in seeds:
        simulator = create("source", "simulator", days=days, crew_size=crew, seed=seed)
        assert isinstance(simulator, MissionSimulator)
        pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
        pipeline.ingest(simulator.read())
        windows: dict[str, list] = {}
        for label in simulator.labels():
            if label.should_alert:
                windows.setdefault(label.astronaut_id, []).append(label.window())
        for member in simulator.crew:
            ill = windows.get(member.astronaut_id, [])
            for mission_day in range(FIRST_DAY, days + 1):
                as_of = pipeline.assessment_time(simulator.day_start(mission_day).date())
                ctx = pipeline.context(member.astronaut_id, as_of)
                baselines = {b.signal: b for b in pipeline.baseline.compute(ctx)}
                anomalies = pipeline.detector.detect(ctx, baselines)
                rows.append(list(vector(extract(ctx, anomalies)).values()))
                target.append(int(any(start <= ctx.as_of <= end for start, end in ill)))
    X = np.array(rows, dtype=float).reshape(len(rows), len(FEATURE_NAMES))
    return X, np.array(target, dtype=int)


def fit(X: np.ndarray, y: np.ndarray, yellow_probability: float = YELLOW_PROBABILITY,
        class_weight: str | None = None) -> dict:
    """Non-negative logistic regression, as points. Returns weights and fit details."""
    if not 0 < yellow_probability < 1:
        raise ValueError("yellow probability must be between 0 and 1 (not included)")
    if class_weight not in (None, "balanced"):
        raise ValueError('class weight must be "none" or "balanced"')
    if len(set(y.tolist())) < 2:
        raise ValueError("training data needs both ill and healthy days; "
                         "use more seeds or more days")
    unseen = [name for i, name in enumerate(FEATURE_NAMES) if not X[:, i].any()]
    active = [i for i, name in enumerate(FEATURE_NAMES) if name not in unseen]
    dropped: list[str] = []
    model = None
    for round_no in range(MAX_ROUNDS + 1):  # the first fit, then up to MAX_ROUNDS refits
        if not active:
            raise ValueError("no feature is left with a positive weight")
        model = LogisticRegression(class_weight=class_weight, max_iter=1000)
        model.fit(X[:, active], y)
        negative = [i for i, coef in zip(active, model.coef_[0]) if coef < 0]
        if not negative or round_no == MAX_ROUNDS:
            break
        dropped += [FEATURE_NAMES[i] for i in negative]
        active = [i for i in active if i not in negative]

    intercept = float(model.intercept_[0])
    if intercept >= 0:
        raise ValueError(f"the intercept is {intercept:.3f}, but it must be negative "
                         "(a day with no findings must score as healthy)")
    yellow_logit = math.log(yellow_probability / (1 - yellow_probability))
    if yellow_logit <= intercept:
        raise ValueError(f"yellow probability {yellow_probability} is not above the "
                         "probability of a day with no findings; use a higher value")
    scale = YELLOW_POINTS / (yellow_logit - intercept)
    coefs = dict(zip(active, model.coef_[0]))
    clamped = [FEATURE_NAMES[i] for i, coef in coefs.items() if coef < 0]
    weights = {name: max(0.0, round(scale * float(coefs.get(i, 0.0)), 3)) + 0.0
               for i, name in enumerate(FEATURE_NAMES)}
    auc = float(roc_auc_score(y, model.decision_function(X[:, active])))
    return {
        "weights": weights,
        "intercept": round(intercept, 4),
        "points_per_logit": round(scale, 4),
        "dropped": dropped + clamped,
        "unseen": unseen,
        "auc": round(auc, 4),
    }


def train(seeds: Sequence[int], days: int = 180, crew: int = 4,
          out: str | Path = DEFAULT_OUT, config: str | Path = DEFAULT_CONFIG,
          yellow_probability: float = YELLOW_PROBABILITY,
          class_weight: str | None = None) -> dict:
    """Build the dataset, fit, write the weights file. Returns the written document."""
    seeds = sorted(set(seeds))
    X, y = dataset(seeds, days, crew, config)
    result = fit(X, y, yellow_probability, class_weight)
    suffix = "" if yellow_probability == YELLOW_PROBABILITY else f"-p{yellow_probability * 100:g}"
    suffix += "-bal" if class_weight == "balanced" else ""
    doc = {
        "version": f"trained-s{seeds_label(seeds)}-d{days}-c{crew}{suffix}",
        "scale": 1.0,
        "weights": result["weights"],
        "trained_on": {
            "simulated": True,
            "seeds": list(seeds),
            "days": days,
            "crew": crew,
            "samples": int(len(y)),
            "positives": int(y.sum()),
            "scikit_learn": sklearn.__version__,
            "class_weight": class_weight,
            "yellow_probability": yellow_probability,
            "dropped_features": result["dropped"],
            "unseen_features": result["unseen"],
            "training_auc": result["auc"],
            "intercept": result["intercept"],
            "points_per_logit": result["points_per_logit"],
        },
        "notes": (f"Logistic regression on simulated missions (B09). 25 points = "
                  f"{yellow_probability * 100:g} % model probability of illness. "
                  "Illustrative, not clinical."),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(doc, indent=2) + "\n")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m orbit.learning.train",
        description="Learn the scorer's weights from simulated missions.")
    parser.add_argument("--seeds", default="1-20", help='e.g. "1-20" or "1,2,5" (default 1-20)')
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--crew", type=int, default=4)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--yellow-probability", type=float, default=YELLOW_PROBABILITY,
                        help="model probability of illness that earns 25 points (default 0.92)")
    parser.add_argument("--class-weight", choices=("none", "balanced"), default="none")
    args = parser.parse_args(argv)
    try:
        doc = train(parse_seeds(args.seeds), args.days, args.crew, args.out, args.config,
                    args.yellow_probability,
                    "balanced" if args.class_weight == "balanced" else None)
    except ValueError as exc:
        parser.error(str(exc))
    info = doc["trained_on"]
    print(f"{doc['version']}: {info['samples']} astronaut-days, {info['positives']} ill, "
          f"training AUC {info['training_auc']}")
    for name, weight in sorted(doc["weights"].items(), key=lambda item: -item[1]):
        if weight > 0:
            print(f"  {weight:7.3f}  {name}")
    if info["dropped_features"]:
        print("dropped (negative):", ", ".join(info["dropped_features"]))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
