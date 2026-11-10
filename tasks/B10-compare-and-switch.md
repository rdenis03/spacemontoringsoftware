# B10 · Compare learned vs starter, then switch

**Lane:** AI · **Needs:** B06, B08, B09 · **Branch:** `be/b10-compare-switch` · **Size:** S

## Goal

Measure whether the trained scorer is actually better than the hand-written
starter, on missions it never saw. Then make it the default only if it is. The
result is the headline of the pitch: "warns X days earlier with Y fewer false
alarms (simulated)".

## Read first

- `README.md` *Results* (B06: the exact evaluation command).
- `orbit/modules/scorer_learned.py`, `orbit/learning/weights.json` (`trained_on`).
- `tests/test_pipeline.py::test_demo_scenario_end_to_end` (the demo story).

## Files

- `orbit.toml` (only `[modules.scorer]`, and only if the rule below says so)
- `orbit/modules/scorer_learned.py` (docstring numbers only)
- `README.md` (*Results* section)
- `reports/learned_vs_starter.json` (new)
- `tests/test_pipeline.py` (only after the team agrees; see below)

## Build

1. Run on held-out seeds:
   ```bash
   python -m orbit.evaluation --config orbit.toml --config experiments/learned.toml \
       --days 180 --crew 4 --seeds 101 102 103 104 105 --out reports/learned_vs_starter.json
   ```
2. Write both rows (sensitivity, median lead time, false alarms per 30 days,
   confounder alert rate) into the README and the scorer's docstring, marked
   as simulated.
3. Switch `orbit.toml` to `use = "learned"` only if the learned scorer has
   sensitivity ≥ the starter's, median lead time ≥ the starter's, and false
   alarms per 30 days ≤ the starter's. Otherwise keep `rule_based` and write
   down which number was worse.
4. If switched, run `python -m orbit demo`. The demo story is AST-01 yellow on
   day 89 and orange on day 90. If that changes, **stop**: report the new
   levels and ask the team before editing `tests/test_pipeline.py`.

## Done when

- [ ] Numbers for both scorers are in the README, marked simulated.
- [ ] The switch decision follows the rule above and is explained in the PR.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Tell the frontend which `model_version` string is now live, so the dashboard
badge shows it.
