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

## B07 · Feature extraction for the AI scorer

- Import from `orbit.learning`: `FEATURE_NAMES`, `Feature`, `extract`, `vector`.
- `extract(ctx, anomalies) -> list[Feature]`: non-zero features only, in `FEATURE_NAMES` order; pure and deterministic.
- `vector(features) -> dict[str, float]`: every `FEATURE_NAMES` key in order, zeros filled; unknown names raise `ValueError`.
- `Feature(name, value, label, signal=None, event_id=None)`, frozen. B08: `Contributor(label=f.label, points=w * f.value, signal=f.signal, event_id=f.event_id)`.
- `FEATURE_NAMES` (42): `dev:*` x7, `drift:*` x7, `vitals_moving`, `sym:*` x8, `dna:*` x3, `crp:high`, `stress:high`, `mood:low`, `event:*` x8. Append new names at the end only, then retrain (B09).
- Several anomalies for one signal: the most deviant is kept. `vitals_moving` counts the 5 vital signals only (not sleep), and only when 2 or more.
- `event:<type>` value is severity rank 1-4 (low..extreme), not rule_based's 1/3/6/10 points; per type the most severe event wins, ties to the most recent.
- Labels match `rule_based` exactly; `features.py` imports the private `_days_label` from `orbit/modules/scorer.py`, so do not rename it.
- Constants `MAX_DEVIATION=3`, `VIRAL_DETECTION_LIMIT=100`, `CRP_LIMIT=10` live in `features.py`, copied from rule_based defaults, not linked to them.
- AST-01 day 90 gives 16 features; AST-02 day 90 has no `dev:*` or `sym:*`.

## B03 · Simulator v2: illness episodes and labels

- `MissionSimulator(...).read()` and `.labels()` unchanged in shape; `labels()` gives one `ScenarioLabel` per episode, and `read()` writes them when `labels_path` is set.
- Default `scenarios="random"` now injects illnesses; pass `scenarios=[]` for a healthy crew (the two B02 healthy tests do).
- `sim.episodes`: `Episode` objects sorted by symptom day, each also in `sim.effects`. Fields `scenario, astronaut_id, symptom_day, lead_days, recovery_days, virus, ...`; `first_day`, `last_day`, `extra_labs(day, weekly)`, `label(day_start)`.
- Inline tables: `type`, `astronaut`, `symptom_day` required; `virus` for viral; optional `lead_days` (1-3; default 2 viral, 1 respiratory), `recovery_days` (5-10). Bad tables raise `ValueError`.
- Random: Poisson `illness_rate * days / 90` per astronaut, 70 % viral; nothing before day 22, whole episode inside the mission, 7 days apart per astronaut.
- Labels: `onset` = 00:00 of first vitals day (not the day -3 DNA rise); `symptom_onset` = day 0 at 07:00; `resolved` = 00:00 of day 0 + `recovery_days`.
- Extra-test rule: extra 09:00 lab tests run only from symptom day (day 0) to the end of recovery, never before; viral = that virus's DNA on non-weekly days, respiratory = CRP. IDs end in `-09`. Before day 0 the DNA rise shows only on weekly tests.
- B09: extra tests only happen during illness, so the presence of a test gives the answer away. Learn from test values only, never from whether a test exists.
- B04: add look-alikes to `sim.effects`; draw their randomness from a new generator (or after the episode seed) so existing values stay identical.
- Starter modules on VZV, symptom day 40: green 24.9 on day -1, orange on day 0. The warning comes on symptom day, not before; a stronger ramp or B08-B10 could make it earlier.