# B06 · Evaluation runner and CLI

**Lane:** Evaluation (M9) · **Needs:** B04, B05 · **Branch:** `data/b06-eval-runner` · **Size:** M

## Goal

One command that runs whole simulated missions through ORBIT and prints how
early it warns and how often it raises false alarms, for one or more configs.
These are the numbers for the pitch, and how B10 decides whether the AI scorer
is better.

## Read first

- SPEC.md Part 3, M9: the CLI, how each run is built, the output.
- `orbit/core/pipeline.py` (`Pipeline.from_settings`, `ingest`, `run`).
- `orbit/core/config.py` (`load_settings`, `Settings`, `ModuleChoice`).
- `orbit/evaluation/metrics.py` (B05), `orbit/modules/simulator.py` (B02 to B04).

## Files

- `orbit/evaluation/runner.py` (new)
- `orbit/evaluation/__main__.py` (new)
- `tests/test_evaluation.py` (add tests)
- `README.md` (only a new *Results* section)

## Build

1. CLI, exactly as SPEC M9:
   ```bash
   python -m orbit.evaluation --config orbit.toml --config experiments/cusum.toml \
       --days 180 --crew 4 --seeds 1 2 3 4 5 --out reports/evaluation.json
   ```
   plus `--min-level` (default `yellow`).
2. For each config and seed: load settings, replace its sources with
   `ModuleChoice("simulator", {days, crew_size, seed})`, build
   `Pipeline.from_settings(settings, store=Store(":memory:"))`, ingest, run,
   then `evaluate(...)` with the simulator's `labels()`. Every config sees
   identical data for a given seed.
3. Output JSON: per config, per seed and mean ± SD over seeds, plus per
   scenario type. Print a table: config, active module names, sensitivity,
   median lead time, false alarms per 30 days, confounder alert rate.
4. Keep it fast: report progress per run; reuse nothing between runs.

## Tests

- A tiny run (`--days 40 --crew 2 --seeds 1`) on `orbit.toml` completes and
  writes JSON with the documented keys.
- Two configs on the same seed see identical observation counts.

## Done when

- [ ] It runs on the starter config for 180 days × 4 crew × 5 seeds.
- [ ] README *Results* quotes the starter numbers, marked as simulated.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Put the exact command you used in the README *Results* section so B10 can
rerun it for the learned scorer on held-out seeds 101 to 105.
