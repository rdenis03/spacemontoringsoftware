# Hand-off notes

What each finished task tells the tasks after it. `/ship` adds a section here
for every task it merges, and `/task` reads the sections for the tasks it needs.

## B01 · Scenario labels schema

- Import from `orbit.schema`: `ScenarioLabel`, `ScenarioType`,
  `ALERTING_SCENARIOS`, `read_labels`, `write_labels`. Do not rename them.
- Set `should_alert = scenario in ALERTING_SCENARIOS`; any other value is rejected.
- `write_labels(path, labels)` takes the path first (the opposite of
  `write_jsonl(items, path)`) and creates missing folders such as `data/sim/`.
- Times with another timezone are converted to UTC, so labels compare directly
  with assessment times.
- `label.window(lookahead_days=14)` runs from `onset - WINDOW_LEAD_DAYS` (fixed
  at 2, in `labels.py`) to `resolved`, or to `onset + lookahead_days`.

## B13 · Past-day endpoint for replay

- `GET /api/crew/{id}/day?as_of=` returns a `DayResult`, the same shape as `/status`.
- `as_of` must match a saved assessment exactly: take `assessed_at` from
  `/assessments` and pass it back unchanged. No rounding; anything else is 404.
- Naive times are UTC; offsets work (`12:00+02:00` finds the 10:00 UTC assessment).
- Built inside `orbit/api/app.py` from store methods; no change to `orbit/core/`.

## B02 · Simulator v1: healthy crew

- `MissionSimulator` in `orbit.modules.simulator`, registered as source `simulator`. Also has `labels() -> []` and `day_start(mission_day)` (day 1 = `mission_start`).
- Personal normals: `sim.normals[astronaut_id][SignalType]` for the 7 nightly signals, ready right after `__init__`; noise sizes in `sim.noise_sd`.
- Effects hook: `sim.effects` is a list of `effect(astronaut_id, mission_day) -> {SignalType: offset}`. Offsets are summed onto the healthy value, then rounded and clamped; symptoms, mood and stress become whole numbers.
- Relative changes use the normal, e.g. `-0.2 * sim.normals[id][SignalType.HRV_RMSSD]`.
- Saliva offsets show only on weekly lab days (mission days 1, 8, 15, ...). Extra lab tests, events and writing `labels_path` are not hooked yet: B03 adds them.
- Random draws happen in a fixed order; new draws inside the day loop change every later value for a seed. Use a separate `random.Random(...)` for new randomness.
- `scenarios`, `illness_rate`, `confounders`, `faults`, `labels_path` are stored on `self`, unused so far.
- Config paths resolve relative to the config file: `experiments/sim180.toml` uses `../data/...` and `../examples/...`.
- Healthy 180-day run with the starters: 720 assessments, all green.