# B04 · Simulator v3: look-alikes and sensor faults

**Lane:** Simulator (M2) · **Needs:** B03 · **Branch:** `be/b04-simulator-lookalikes` · **Size:** M

## Goal

Add the things that look like illness but are not: spacewalks, sleep shifts,
solar particle events, broken sensors and missing nights. They are how the
evaluation counts false alarms, and how the AI scorer (B09) learns that a high
heart rate after a spacewalk is fine.

## Read first

- SPEC.md Part 3, M2: the rows `eva_exertion`, `sleep_shift`,
  `solar_particle_event`, `sensor_fault`, `missing_data`; the `confounders`
  and `faults` options.
- `orbit/schema/models.py` (`ContextEvent`) and `orbit/schema/enums.py` (`EventType`).
- `orbit/modules/simulator.py` (B02, B03).

## Files

- `orbit/modules/simulator.py`
- `tests/test_simulator.py` (add tests)

## Build

1. `eva_exertion`: an `EVA` `ContextEvent` for that astronaut; workload 12 h
   that day; the next night HRV −15 % and resting HR +3; no symptoms.
2. `sleep_shift`: a `SLEEP_SHIFT` event; sleep −1.5 h for 2–3 nights.
3. `solar_particle_event`: a crew-wide event (`astronaut_id=None`);
   `radiation_dose_daily` × 2–5 for 1–2 days; no physiology change.
4. `sensor_fault`: a few readings with absurd values, stored with
   `quality="bad"` and a `note`.
5. `missing_data`: no wearable records for 1–2 nights.
6. Each gets a `ScenarioLabel` with `should_alert=False`.
7. With `scenarios="random"`: confounders appear when `confounders=True`
   (for example 2 spacewalks and 1 sleep shift per astronaut per 90 days, 1
   solar event per 60 days for the crew), and faults when `faults=True`.
   They may overlap an illness; illness episodes still never overlap each other.
8. Event IDs are deterministic, like observation IDs.

## Tests

- Every confounder label has `should_alert=False`.
- Every faulty reading has `quality="bad"` and a note.
- A missing-data night has no wearable records for that astronaut.
- `confounders=False, faults=False` reproduces B03's output exactly.
- Still under 5 seconds for 180 days × 4 crew; still byte-identical per seed.

## Done when

- [ ] `python -m orbit --config experiments/sim180.toml demo` runs.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

The simulator is complete for M2. Note in the module docstring how many
episodes of each type a default 180-day, 4-person run produces, so B06 and B09
can sanity-check their numbers.
