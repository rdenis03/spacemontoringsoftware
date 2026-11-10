# B08 · Learned scorer module (placeholder weights)

**Lane:** AI (M8) · **Needs:** B07 · **Branch:** `be/b08-learned-scorer` · **Size:** S

## Goal

The runtime half of the AI scorer: a `scorer` module that reads a small JSON
file of learned weights and turns features into points with reasons. It ships
with hand-set placeholder weights so it works today; B09 replaces the file with
trained weights later. Runtime needs no machine-learning library: it is
multiplication, so it runs offline and is deterministic.

## Read first

- SPEC.md Part 3, M8: requirements (contributors, points add up, freshness,
  determinism).
- `orbit/modules/scorer.py` (`RuleBasedScorer`: the point sizes to mirror).
- `orbit/learning/features.py` (B07).
- `tests/test_contracts.py` (the scorer contract every scorer must pass).

## Files

- `orbit/modules/scorer_learned.py` (new)
- `orbit/learning/weights.json` (new, placeholder)
- `orbit/modules/__init__.py` (one import line)
- `experiments/learned.toml` (new: `orbit.toml` with `[modules.scorer] use = "learned"`)
- `pyproject.toml` (separate commit: package data so the JSON ships:
  `[tool.setuptools.package-data] orbit = ["learning/*.json"]`)
- `tests/test_scorer_learned.py` (new)

## Build

1. Weights file format:
   ```json
   {"version": "placeholder-1", "scale": 1.0,
    "weights": {"dev:skin_temp": 2.5, "sym:symptom_rash_tingling": 7.0},
    "trained_on": null}
   ```
2. `@register("scorer", "learned")` class `LearnedScorer(weights_path: str | None = None)`.
   Default path: `Path(__file__).parents[1] / "learning" / "weights.json"`.
   Refuse (raise `ValueError`) a negative weight or an unknown feature name.
3. `score(ctx, anomalies)`: `points = scale × weight × value` per feature;
   features that share a reason (same `signal`, or same `event_id`) become one
   `Contributor`, points summed, label of the first one. Drop zero points.
   `score = min(100, round(sum, 1))`, `model_version = f"learned-{version}"`.
   Leave `level` out (it is derived).
4. Placeholder weights that mirror `rule_based`: about 2.5 per vital
   deviation, 1.5 per sleep deviation, 0.5 per drift, symptom weights from
   `SYMPTOM_WEIGHTS`, 4 per DNA unit, 8 for high CRP, 3 for stress and mood,
   2.5 per event severity rank.
5. Do **not** switch `orbit.toml`; the starter stays active until B10.

## Tests (`tests/test_scorer_learned.py`)

- Points add up to the score before the cap; every contributor has `signal`
  or `event_id`.
- Same input, same output; `model_version` starts with `learned-`.
- A weights file with a negative weight is refused; a custom `weights_path` is used.

## Done when

- [ ] The scorer contract tests pass for `learned` (sick AST-01 above healthy AST-02).
- [ ] `python -m orbit --config experiments/learned.toml demo` runs.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

B09 overwrites `orbit/learning/weights.json` in the same format. Keep the
format documented in the module docstring.
