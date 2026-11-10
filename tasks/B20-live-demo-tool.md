# B20 · Live body demo tool

**Lane:** Demo · **Needs:** none (uses B11 if it exists) · **Branch:** `data/b20-live-demo-tool` · **Size:** S

## Goal

On stage, a teammate wears a watch (or just reads out their heart rate), and
the judges watch ORBIT react to real numbers. Two problems to solve: the
wearer needs a personal "normal" before ORBIT can spot a change, and the new
reading must be assessed right away, not at tomorrow's 10:00 UTC run.

## Read first

- `orbit/core/pipeline.py` (`ingest`, `assess`), `orbit/core/config.py` (`load_settings`).
- `orbit/modules/sources.py` (`MemorySource`), `orbit/core/interfaces.py` (`SourceBatch`).
- `orbit/api/app.py`: `POST /api/observations` and `POST /api/crew/{id}/checkin`
  (a check-in re-assesses at its own timestamp).
- `orbit/modules/baseline.py` (`min_samples=5`; history excludes the last 3 days).

## Files

- `tools/live_demo.py` (new)
- `tests/test_live_demo.py` (new)

## Build

1. `python tools/live_demo.py seed --id AST-03 --callsign Live --resting-hr 62 --skin-temp 34.1 --hrv 55 --resp-rate 14 --spo2 97 --sleep 7`
   builds a crew member plus 14 nights of normal readings around those values
   (small seeded noise, `source="manual"`, ending last night) and ingests them
   into the database from `orbit.toml`. Optional `--from-csv` uses B11's
   `wearable_csv` source for a real export instead of the numbers.
2. `python tools/live_demo.py push --id AST-03 --resting-hr 95 --skin-temp 34.8 [--api http://localhost:8000]`
   posts the readings stamped now to `POST /api/observations`, then posts a
   check-in stamped now (`mood` and `stress`, default 3) so the API re-assesses
   at that moment, and prints the new level and top 3 reasons.
3. Standard library only (`urllib`, `argparse`): no new dependency.
4. Put the logic in functions (`build_seed(...) -> SourceBatch`,
   `build_push(...) -> list[dict]`) so tests run without a server.

## Tests (`tests/test_live_demo.py`)

In-process, with `Store(":memory:")`, no network:

- After `build_seed` with normal values, assessing now is green.
- Adding a reading with resting HR +30 and skin temperature +0.7 turns it at
  least yellow, with heart rate among the reasons.
- Seeding twice replaces instead of duplicating (deterministic IDs).

## Done when

- [ ] With `python -m orbit serve` running, `seed` then `push` changes AST-03 on the dashboard.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Write the stage script (the commands, in order, with example values) in the
module docstring. Values are illustrative, not medical thresholds.
