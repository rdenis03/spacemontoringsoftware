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
- `FEATURE_NAMES` (37): `dev:*` x7, `drift:*` x7, `vitals_moving`, `sym:*` x8, `dna:*` x3, `crp:high`, `stress:high`, `mood:low`, `event:*` x8. Append new names at the end only, then retrain (B09).
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

## B14 · Consent editing endpoint

- `PUT /api/crew/{astronaut_id}/consent`, body `ConsentUpdate {"share_with_earth": [SignalCategory, ...]}`, returns the updated `CrewMember`; other fields are kept.
- Unknown category gives 422 (pydantic message lists the allowed values); unknown astronaut gives 404; `[]` is allowed and shares no readings.
- Score and level still go to Earth whatever the consent (the consent gate's rule), so a hidden emergency is impossible.
- `share_with_earth` is a frozenset: the JSON order is not the request order and can change between server runs, and duplicates merge. Compare as sets.
- Re-ingesting the crew from a source (`upsert_crew`) resets consent to the defaults.
- `pipeline.earth_packet(...)` already follows the saved consent; B16's outbox can reuse it. The endpoint sits after `GET /api/crew` in `orbit/api/app.py`.

## B04 · Simulator v3: look-alikes and sensor faults

- `sim.lookalikes`: `LookAlike(scenario, astronaut_id, day, nights, ...)`, sorted by day; `astronaut_id=None` = crew-wide (solar). Also in `sim.effects`. `sim.episodes` stays illnesses only.
- `read()` now returns `events` (EVA, SLEEP_SHIFT, SOLAR_PARTICLE_EVENT); `sim.events()` gives the same list. IDs `f"{astronaut or 'CREW'}-{event_type}-{yyyymmdd}"`.
- `labels()` mixes illnesses and look-alikes, sorted by mission day; filter with `label.should_alert`. Look-alike labels have no `symptom_onset`.
- A solar event gives one label per astronaut: count false alarms per label, not per event (B06).
- EVA event runs 13:00-19:00, after the 10:00 assessment: its points and its next-night HRV -15 % / HR +3 both show the next day.
- Sensor faults: absurd values with `quality="bad"` and a note starting "Simulated sensor fault"; use `o.is_usable` when averaging raw readings. Missing data: no wearable records for 1-2 nights.
- Random rates per astronaut per 90 days: EVA 2, sleep shift 1, sensor fault 2, missing data 1; solar 1 per 60 days for the crew. From day 22, inside the mission, no overlap with the same astronaut's look-alikes; may overlap an illness.
- List mode contains exactly what is listed. Look-alike keys: `type`, `day`, `astronaut` (not for solar), `nights` (not for EVA).
- `confounders=False, faults=False` is byte-identical to B03 (checked against main for seeds 1-3); look-alikes draw from their own generator.
- Default 180 d x 4 crew, seed 1: 71 labels (6 viral, 2 respiratory, 15 EVA, 10 sleep shift, 12 solar, 16 sensor fault, 10 missing), 28 events, 31 bad readings. Counts are in the module docstring.

## B05 · Evaluation metrics

- Import from `orbit.evaluation`: `alerts`, `episodes`, `sensitivity`, `lead_times`, `summary`, `false_alarms`, `evaluate`, `Episode`, `FalseAlarmReport`, `CONFOUNDER_SCENARIOS`, `FAULT_SCENARIOS`. Pure: no I/O, no clock.
- `evaluate(assessments, labels, min_level=AlertLevel.YELLOW, astronaut_days=None) -> dict`; keys documented in `orbit/evaluation/metrics.py`. `min_level` also takes "orange" etc.; `astronaut_days=None` counts distinct (astronaut, UTC date) assessed.
- Keys: `sensitivity`, `detected`, `lead_times`, `lead_time` {n, median, min, max}, `false_alarms` {count, per_30_days, confounder_count, fault_count}, `confounder_alert_rate`, `by_scenario` {type: {labels, alerted, rate}}, plus counts. Nothing is rounded.
- `None` (not an error) when there are no labels of that kind; `per_30_days` is `None` when `astronaut_days` is 0.
- Windows are `label.window()`, both ends included; an alert episode overlapping any illness window of the same astronaut is not a false alarm, even inside a confounder window.
- Lead time is exact (SPEC): symptom onset 07:00, assessment 10:00, so the day before = 0.875 and symptom day = -0.125.
- Decision for B06: report lead time in whole calendar days as the headline number in the printed table (symptom day = 0, the day before = 1, i.e. `(symptom_onset.date() - first_alert.assessed_at.date()).days` in UTC), and keep the exact SPEC value in the JSON next to it.
- A solar event gives one label per astronaut, so it counts 4 times in `by_scenario` and `confounder_alert_rate`.
- `Episode` here is an alert run, not the simulator's illness `Episode`; import by module.
- Starter modules, default 180 d x 4 crew, seed 1: sensitivity 1.0 (8/8), lead time median 0.375 d (-0.125 to 1.875), 0 false alarms.

## B15 · Shared status for the crew view

- `GET /api/crew/{id}/status?view=shared` and `GET /api/crew/{id}/day?as_of=&view=shared`; `View = Literal["full", "shared"]` (default `full`, exactly as before; anything else gives 422).
- `shared_view(result, member)` (inside `create_app`) builds the shared `DayResult`; reuse it for any new endpoint that returns one.
- Reasons go through `pipeline.sync.package(member, [], [assessment])`: private ones get `PRIVATE_LABEL`, same points and order, so the points still add up. Score and level are always kept.
- Anomalies and baselines of unshared categories are dropped (the starter detector only makes vital and sleep anomalies).
- Action cards: shown in full only when all `triggers` are in shared categories (no triggers = always shown). Otherwise `card_id` `private-N` (in card order), title `PRIVATE_CARD_TITLE`, one step `PRIVATE_CARD_STEP`, `PRIVATE_CARD_RATIONALE`, triggers emptied; `level` and `escalate_to` kept. Constants in `orbit/api/app.py`.
- All-or-nothing: one private trigger hides the whole card, harmless steps included (today `reduce-load` and `saliva-test`). B19: keep each card's triggers within one category.
- Frontend: `private-N` IDs depend on order and are not stable between days; do not match on them.
- The crew view follows `share_with_earth` (B14); there is no separate crew consent. `/api/overview` already shows only callsign, level and score.

## B20 · Live body demo tool

- `python tools/live_demo.py seed --id AST-03 --callsign Live --resting-hr 62 --skin-temp 34.1 --hrv 55 --resp-rate 14 --spo2 97 --sleep 7 [--config]`: crew member + 14 nights at 06:00 UTC ending last night (`source="manual"`, seeded noise), ingested into the config's database, then assessed now (green).
- `python tools/live_demo.py push --id AST-03 --resting-hr 95 --skin-temp 34.8 --fever 2 [--api http://localhost:8000]`: readings stamped now to `POST /api/observations`, then a check-in stamped now (mood/stress 3) that makes the API assess; prints level and top 3 reasons. Stage script in the module docstring.
- Functions: `build_seed(astronaut_id, callsign, normals, now, nights=14, seed=1) -> SourceBatch`, `build_push(astronaut_id, readings, now) -> list[dict]`, `build_checkin(now, mood, stress, symptoms) -> dict`, `describe(day_result_json) -> str`, `night_stamps(now, nights)`.
- Starter scorer: HR +30 and temp +0.7 alone = 15 points (green); yellow needs 25, so the stage script adds `--fever 2` (27, yellow). Revisit if B08-B10 change the weights.
- Every push sends all five symptom flags (`--fever --fatigue --sore-throat --headache --aches`, 0 unless given), so a later push clears an earlier fever.
- Seed IDs `f"{id}-{signal}-{yyyymmdd}"`: re-seeding the same day replaces. Re-seeding re-saves the crew member, which resets consent to the defaults.
- `--from-csv` calls `create("source", "wearable_csv", path=, astronaut_id=)` (B11's planned options); without B11 it stops before opening the database.
- Tests run in-process (`TestClient`, `Store(":memory:")`); the tool loads via importlib from `tools/live_demo.py` (not a package).
- Checked against a running `serve` with a scratch database: green 0.0, yellow 27.0, back to green 0.0 in `/api/overview`.