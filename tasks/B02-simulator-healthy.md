# B02 · Simulator v1: healthy crew

**Lane:** Simulator (M2) · **Needs:** B01 · **Branch:** `be/b02-simulator-healthy` · **Size:** M

## Goal

A `simulator` data source that generates a long mission for a healthy crew:
every daily record, for every astronaut, deterministic from a seed. No
illness yet: B03 adds it, B04 adds look-alikes and faults. Getting the healthy
physiology right first makes illness easy to add and easy to test.

## Read first

- SPEC.md Part 3, M2: options, daily records table, physiology model.
- `orbit/modules/sources.py` (`MemorySource`: how a source returns a `SourceBatch`).
- `examples/make_examples.py` (a small generator in the same style, same times of day).
- `orbit/schema/signals.py` (`get_spec`: units, plausible ranges, allowed sources).
- `orbit/core/interfaces.py` (`SourceBatch`).

## Files

- `orbit/modules/simulator.py` (new; or a package `orbit/modules/simulator/` if it grows)
- `orbit/modules/__init__.py` (one import line)
- `experiments/sim180.toml` (new)
- `tests/test_simulator.py` (new)

## Build

1. `@register("source", "simulator")` class `MissionSimulator` with these
   options, all defaulted: `days=60`, `crew_size=4`, `seed=1`,
   `mission_start="2027-01-04T00:00:00Z"`. Accept and store the options B03
   and B04 will use (`scenarios="random"`, `illness_rate=1.0`,
   `confounders=True`, `faults=True`, `labels_path=None`), but ignore them
   for now.
2. Crew `AST-01` to `AST-NN` with callsigns, `mission_start` from the option.
3. Personal normals drawn once per astronaut from the ranges in SPEC M2;
   night-to-night noise with the SDs in SPEC M2; AR(1) noise with φ ≈ 0.3;
   clamp to each signal's plausible range from `get_spec`.
4. Daily records at the times in SPEC M2: 06:00 vitals and sleep
   (`source="wearable"`, `device_id="wrist-<id>"`), 07:00 the 8 symptoms
   (0 when healthy) plus `mood` and `stress` (`source="checkin"`), 09:00 weekly
   saliva EBV/VZV/HSV-1 DNA below 100 copies/mL (`source="lab"`), 23:59
   `radiation_dose_daily` and `workload` (`source="environment"`).
5. Deterministic IDs: `f"{astronaut}-{signal}-{yyyymmdd}"`. Every record has
   `simulated=True`.
6. All randomness comes from one `random.Random(seed)` (or a seeded numpy
   `Generator`). No global random state, no clock.
7. `labels()` returns `[]` for now (B03 fills it).
8. `experiments/sim180.toml`: a copy of `orbit.toml` with the `files` source
   replaced by `[[sources]] use = "simulator"`, `days = 180`,
   `labels_path = "data/sim/labels.jsonl"`, and `database = ":memory:"`.
   Never use the `files` source and the simulator in one config.

## Tests (`tests/test_simulator.py`)

- Same options give byte-identical output (compare the JSONL of all records).
- Records per astronaut per day: 7 wearable, 10 check-in, 2 environment,
  plus 3 lab records once a week.
- Every record passes schema validation and has `simulated=True`.
- 180 days × 4 crew runs in under 5 seconds.
- Each astronaut's mean skin temperature stays within 0.2 °C of their normal.

## Done when

- [ ] The contract test for sources passes for `simulator` with no options.
- [ ] `python -m orbit --config experiments/sim180.toml demo` runs and every astronaut stays green or yellow.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Expose the per-astronaut personal normals and the day loop in a way B03 can
add effects to (for example a list of per-day offset functions per signal).
Write that hook's shape in the module docstring.
