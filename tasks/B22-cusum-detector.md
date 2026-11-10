# B22 · CUSUM detector (stretch)

**Lane:** Analytics (M7) · **Needs:** none (B06 for the comparison) · **Branch:** `be/b22-cusum-detector` · **Size:** S

## Goal

Catch slow drifts earlier than the starter `robust_z` detector, without
alarming on single noisy nights, using a cumulative-sum (CUSUM) chart per signal.

## Read first

- SPEC.md Part 3, M7: requirements and ideas.
- `orbit/modules/detector.py` (`RobustZDetector`, `concern_score`).
- `orbit/schema/signals.py` (`get_spec(signal).concern`).

## Files

- `orbit/modules/detector_cusum.py` (new)
- `orbit/modules/__init__.py` (one import line)
- `experiments/cusum.toml` (new: `orbit.toml` with `[modules.detector] use = "cusum"`)
- `tests/test_detector_cusum.py` (new)

## Build

1. `@register("detector", "cusum")` with `k=0.5` (slack, in spreads) and
   `h=4.0` (decision limit), both defaulted.
2. For each signal with a baseline: run a one-sided CUSUM in the worrying
   direction over `ctx.recent_for(signal)`, in units of the baseline spread.
   Report an anomaly when the sum passes `h`.
3. Every requirement in SPEC M7: at most one anomaly per signal, worrying
   direction only, skip `spread <= 0`, `deviation = (value − center) / spread`
   of the newest reading used, `consecutive_days` = length of the run, `kind="drift"`.

## Tests

- Three readings each +1.5 spreads trigger an anomaly; a single +2 spike does not.
- A drift in the harmless direction triggers nothing.
- Same input, same output.

## Done when

- [ ] The detector contract tests pass for `cusum`.
- [ ] If B06 exists: numbers for `experiments/cusum.toml` vs `orbit.toml` are in the module docstring.
- [ ] `python -m pytest` and `python -m orbit demo` pass. `orbit.toml` is not switched.
