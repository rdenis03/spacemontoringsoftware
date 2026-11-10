# B21 · EWMA baseline (stretch)

**Lane:** Analytics (M6) · **Needs:** none (B06 for the comparison) · **Branch:** `be/b21-ewma-baseline` · **Size:** S

## Goal

A personal baseline that follows slow in-flight adaptation (weights recent
nights more) without absorbing an illness, as an alternative to the starter
`rolling_median`.

## Read first

- SPEC.md Part 3, M6: requirements and ideas.
- `orbit/modules/baseline.py` (`RollingMedianBaseline`, `MIN_SPREAD`).
- `orbit/core/interfaces.py` (`AssessmentContext.history`).

## Files

- `orbit/modules/baseline_ewma.py` (new)
- `orbit/modules/__init__.py` (one import line)
- `experiments/ewma.toml` (new: `orbit.toml` with `[modules.baseline] use = "ewma"`)
- `tests/test_baseline_ewma.py` (new)

## Build

1. `@register("baseline", "ewma")` with `half_life_days=7.0`, `min_samples=5`,
   `suspect_weight=0.5`, all defaulted.
2. Exponentially weighted median (or a robust weighted mean) per signal from
   `ctx.history` only; spread ≈ 1 SD, floored with `MIN_SPREAD`; suspect
   readings down-weighted.
3. Every requirement in SPEC M6 (`as_of`, `window_days`, `n_samples`,
   `method="ewma"`, at most one per signal).

## Tests

- A step change 10 days ago moves the center more than `rolling_median` does.
- One absurd suspect night barely moves the center.
- Same input, same output.

## Done when

- [ ] The baseline contract tests pass for `ewma`.
- [ ] If B06 exists: numbers for `experiments/ewma.toml` vs `orbit.toml` are in the module docstring.
- [ ] `python -m pytest` and `python -m orbit demo` pass. `orbit.toml` is not switched.
