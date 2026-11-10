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
