# B01 · Scenario labels schema

**Lane:** Simulator (part of M2) · **Needs:** none · **Branch:** `data/b01-scenario-labels` · **Size:** S

## Goal

Add the "right answers" model: what happened to whom and when, and whether
ORBIT should have alerted. The simulator (B02 to B04) writes these labels; the
evaluation (B05, B06) and the trainer (B09) read them. Agreeing on this model
first lets those tasks run in parallel.

## Read first

- SPEC.md Part 3, M2: the `orbit/schema/labels.py` block and the scenario table.
- SPEC.md Part 3, M9: the definition of a label's *window*.
- `orbit/schema/models.py`: `_Model`, `UtcDatetime`, `AstronautId`.
- `orbit/schema/__init__.py`, `orbit/schema/io.py`.

## Files

- `orbit/schema/labels.py` (new)
- `orbit/schema/__init__.py` (add exports only)
- `tests/test_labels.py` (new)

## Build

1. `ScenarioType(StrEnum)` with exactly these 7 values: `viral_reactivation`,
   `respiratory_infection`, `eva_exertion`, `sleep_shift`,
   `solar_particle_event`, `sensor_fault`, `missing_data`.
2. `ALERTING_SCENARIOS = frozenset({viral_reactivation, respiratory_infection})`.
3. `ScenarioLabel(_Model)` with the fields from SPEC M2:
   `label_id`, `astronaut_id`, `scenario`, `virus` (`"ebv" | "vzv" | "hsv1" | None`),
   `onset`, `symptom_onset`, `resolved`, `should_alert`, `notes`.
4. Validation (raise a clear error):
   - `symptom_onset >= onset` and `resolved >= onset` when they are set;
   - `virus` is required for `viral_reactivation` and must be `None` otherwise;
   - `should_alert == (scenario in ALERTING_SCENARIOS)`.
5. `ScenarioLabel.window(lookahead_days: int = 14) -> tuple[datetime, datetime]`:
   from `onset - 2 days` to `resolved`, or `onset + lookahead_days` when
   `resolved` is not set. This is the M9 window; B05 and B09 both use it.
6. `write_labels(path, labels)` and `read_labels(path) -> list[ScenarioLabel]`
   as JSONL, one label per line.
7. Export `ScenarioType`, `ScenarioLabel`, `ALERTING_SCENARIOS`, `read_labels`
   and `write_labels` from `orbit.schema`.

This is an additive change: do not bump `SCHEMA_VERSION`, and do not add the
model to the JSON Schema export.

## Tests (`tests/test_labels.py`)

- A valid viral label builds. Naive datetimes are rejected.
- `symptom_onset` before `onset` is rejected; a confounder with
  `should_alert=True` is rejected; a viral label without `virus` is rejected.
- `window()` with and without `resolved`.
- `write_labels` then `read_labels` gives equal objects.

## Done when

- [ ] `from orbit.schema import ScenarioLabel, ScenarioType` works.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

B02 to B04, B05 and B09 import `ScenarioLabel`, `ScenarioType`,
`ALERTING_SCENARIOS` and `ScenarioLabel.window()`. Do not rename them later.
