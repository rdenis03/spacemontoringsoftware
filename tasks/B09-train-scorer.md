# B09 · Train the scorer on simulated missions

**Lane:** AI · **Needs:** B04 (B03 is enough for a first run), B07, B08 · **Branch:** `be/b09-train-scorer` · **Size:** M

## Goal

Learn the scorer's weights from simulated missions where the right answers are
known, and write them to `orbit/learning/weights.json`. A simple, explainable
model (logistic regression) is enough: each feature gets one weight, so every
point still has a plain reason.

## Read first

- `orbit/learning/features.py` (B07), `orbit/modules/scorer_learned.py` (B08).
- `orbit/modules/simulator.py` (B02 to B04), `orbit/schema/labels.py` (B01).
- `orbit/core/pipeline.py`: `Pipeline.from_settings`, `context`, and the
  `baseline` and `detector` attributes used by `assess`.
- `orbit/evaluation/runner.py` (B06), if it exists: reuse how it builds a
  simulator pipeline.

## Files

- `orbit/learning/train.py` (new)
- `orbit/learning/weights.json` (overwritten with trained weights)
- `pyproject.toml` (separate commit: `train = ["scikit-learn>=1.4"]` under
  `[project.optional-dependencies]`)
- `tests/test_train.py` (new)

## Build

1. CLI: `python -m orbit.learning.train --seeds 1-20 --days 180 --crew 4 --out orbit/learning/weights.json`.
   Install with `pip install -e ".[dev,train]"`. Only this file imports
   scikit-learn; the runtime scorer never does.
2. Dataset, per seed: simulator → `Pipeline` with `Store(":memory:")` →
   ingest. For each astronaut and day from day 22 at the assessment hour:
   `ctx = pipeline.context(...)`, baselines and anomalies from the pipeline's
   own baseline and detector, `x = vector(extract(ctx, anomalies))`.
   `y = 1` when `as_of` falls in the `window()` of a `should_alert` label for
   that astronaut, else 0 (look-alike days are 0).
3. Fit `LogisticRegression(class_weight="balanced", max_iter=1000)`. Weights
   must be ≥ 0: drop features with a negative coefficient and refit, up to 10
   rounds. Features never non-zero in training get weight 0.
4. Convert to points: the intercept `b0` must be negative; `scale = 25 / -b0`,
   `weight_i = round(scale × coef_i, 3)`. So a score of 25 (yellow) means the
   model's probability of illness is 50 %.
5. Write the B08 format with `version = "trained-s1-20-d180-c4"` (from the
   arguments, never the clock) and `trained_on` = seeds, days, crew, number
   of samples and positives, scikit-learn version, dropped features, training AUC.
6. Deterministic: same arguments give the same file.

## Tests (`tests/test_train.py`)

Skip the whole file when scikit-learn is missing (`pytest.importorskip("sklearn")`).

- A tiny run (`--days 40 --crew 2 --seeds 1`) writes a file that
  `LearnedScorer` loads, with every weight ≥ 0.
- Two identical runs write identical files.

## Done when

- [ ] Trained weights are committed, and the scorer contract tests still pass
      for `learned` (sick AST-01 above healthy AST-02).
- [ ] `python -m orbit --config experiments/learned.toml demo` runs.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

B10 evaluates on seeds 101 to 105, which training never saw. Never train on
those seeds.
