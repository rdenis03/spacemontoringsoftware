# ORBIT: Onboard Readiness & Body Insight Tracker

An immune early-warning system for long-duration space missions. It gathers
health indicators, compares each astronaut to their own baseline, and turns
changes into clear actions the crew can take without waiting for Earth.

## Quick start

```bash
pip install -e ".[dev]"
python -m orbit demo        # load example data, assess every day, show results
python -m orbit serve       # API on http://localhost:8000 (docs at /docs)
python -m pytest            # 88 tests
```

Requires Python 3.11+.

`demo` plays the example scenario: three weeks of data for two astronauts.
AST-01 develops early signs of shingles reactivation and goes green → yellow
(take a saliva test) → orange (virus found: reduce workload, tell the crew
medical officer). AST-02 stays green.

## How it is built

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the design and the reasons
behind it. In short:

- `orbit/schema/` (M1): the data contract every module uses.
- `orbit/core/`: the backbone. Module slots, the shared SQLite store, the
  plug-in registry, config loading and the pipeline that connects them.
- `orbit/modules/`: a simple working starter for every slot. Team members
  replace these with their real modules.
- `orbit/api/`: HTTP API for the frontend and live data feeds.
- `orbit.toml`: chooses which implementation fills each slot.

## Adding your module

1. Read your slot's interface in `orbit/core/interfaces.py`.
2. Create `orbit/modules/<name>.py` with `@register("<slot>", "<name>")` and
   import it in `orbit/modules/__init__.py`.
3. `python -m pytest tests/test_contracts.py` checks it fits the slot.
4. Set `use = "<name>"` in `orbit.toml`.

| Slot | Starter | Team module |
|---|---|---|
| source | `files`, `memory` | M3 (M2 simulator and M5 space weather add sources) |
| baseline | `rolling_median` | M6 |
| detector | `robust_z` | M7 |
| scorer | `rule_based` | M8 |
| actions | `card_library` | M10 |
| sync | `consent_gate` | M13 |

## Command line

```bash
python -m orbit demo                     # everything in memory, safe to repeat
python -m orbit ingest                   # load the [[sources]] in orbit.toml
python -m orbit run [--start 2027-04-01] [--end 2027-04-03] [--astronaut AST-01]
python -m orbit status AST-01
python -m orbit modules                  # which implementations exist / are active
python -m orbit serve [--port 8000]      # loads the sources first if the database is empty
python -m orbit reset                    # delete the database
python -m orbit.schema validate my.jsonl # check a data file against the schema
```

## API for the frontend

| Method | Path | Used by |
|---|---|---|
| GET | `/api/health` | anyone: status, active modules, record counts |
| GET | `/api/signals` | labels, units, scales, alert thresholds |
| GET | `/api/crew` | crew list |
| GET | `/api/overview` | crew view (M14): latest level per astronaut |
| GET | `/api/crew/{id}/status` | dashboard (M12): level, reasons, actions, anomalies; `?view=shared` hides private reasons and cards (crew view, M14) |
| GET | `/api/crew/{id}/day?as_of=` | the same for a past assessment (replay); also `?view=shared` |
| GET | `/api/crew/{id}/observations?signal=&start=&end=` | charts |
| GET | `/api/crew/{id}/baselines?signal=` | "your normal" band |
| GET | `/api/crew/{id}/assessments` | score trend line |
| POST | `/api/crew/{id}/checkin` | check-in form (M11); re-assesses immediately |
| GET | `/api/crew/{id}/earth-packet?start=&end=` | what would go to Earth (M13) |
| POST | `/api/crew/{id}/earth-packet/send?start=&end=&delay_minutes=` | package and queue for Earth; delay defaults to `[comms]` (M13) |
| PUT | `/api/crew/{id}/consent` | body `{"share_with_earth": ["vital", ...]}`: what leaves the spacecraft (M13) |
| GET | `/api/outbox?astronaut_id=` | everything sent, `queued` or `delivered`, with seconds to delivery (M13) |
| GET | `/api/events` | solar events, spacewalks |
| POST | `/api/observations` | devices and feeds pushing readings |
| POST | `/api/pipeline/run` | re-run assessments |

CORS is open, so a frontend dev server on any port can call the API.
Interactive documentation with request examples: `http://localhost:8000/docs`.

## The data contract (M1)

| Model | What it holds |
|---|---|
| `Observation` | One reading: astronaut, time, signal, value, unit, source, quality |
| `ContextEvent` | A stressor: solar event, spacewalk, schedule shift, ill crewmate |
| `CrewMember` | Profile, mission start, what the astronaut shares with Earth |
| `Baseline` | Personal normal for one signal (center and spread) |
| `Anomaly` | A deviation from the baseline (spike or drift) |
| `RiskAssessment` | Score 0–100, alert level, and the reasons behind it |
| `ActionCard` | What to do at a given level, and who to tell |

Rules the models enforce:

1. Timestamps must include a timezone and are stored in UTC.
2. Units must match the signal (`skin_temp` is `degC`); omit the unit to have
   it filled in.
3. Only the right channel can report a signal (symptoms come from the check-in).
4. Physically impossible values can only be stored with `quality="bad"`;
   analytics skip those.
5. Symptom (0–3) and mood/stress (1–5) scales are whole numbers.
6. The alert level always matches the score: green < 25 ≤ yellow < 50 ≤
   orange < 75 ≤ red.
7. Unknown fields are rejected and records are immutable.

25 signals in six categories: vital signs, sleep, symptoms, wellbeing, onboard
lab and context. `python -m orbit.schema signals` lists them with units and
ranges; `schemas/signals.json` has the same for the frontend.

Symptoms and wellbeing stay onboard unless the astronaut chooses to share
them (`CrewMember.share_with_earth`).

## Example data

`examples/` holds mission days 70–90 for two astronauts (800 readings), a
solar particle event, a spacewalk, sample risk assessments and an action-card
library. Rebuild with `python examples/make_examples.py`. The action cards and
scoring weights are illustrative, not medical protocols.

## Layout

```
orbit/
  schema/       M1 data contract: enums, signal registry, models, file I/O
  core/         backbone: interfaces, store, registry, config, pipeline
  modules/      starter implementation for every slot
  api/          FastAPI app
  __main__.py   command line
orbit.toml      configuration
examples/       sample data and the script that builds it
schemas/        JSON Schemas and signals.json for the frontend
tests/          schema, store, pipeline, contract and API tests
```

## Results

**Simulated, not clinical.** These numbers come from missions generated by
ORBIT's own simulator (M2) with illustrative illnesses, look-alikes and sensor
faults. They show how the starter modules behave on that data, not how well
ORBIT would work on real astronauts.

Starter modules (`orbit.toml`: `rolling_median`, `robust_z`, `rule_based`),
180 days x 4 crew x seeds 1-5, an alert is yellow or worse:

| Metric | Mean ± SD over 5 seeds |
|---|---|
| Sensitivity (illnesses with an alert in their window) | 1.00 ± 0.00 (39 of 39) |
| Lead time, median, whole days before symptom day | 0.6 ± 0.4 (range 0 to 2 days) |
| Lead time, median, exact (SPEC M9) | 0.48 ± 0.42 days |
| False alarms per 30 astronaut-days | 0.00 ± 0.00 |
| Confounder alert rate | 0.06 ± 0.06 |

How to read them:

- Every illness was caught, but mostly late: 19 of 39 on symptom day itself
  (lead 0), 15 one day early, 5 two days early. Earlier warning is the main
  thing to improve (B08 to B10).
- No alert happened outside an illness. The confounder alert rate is not zero
  only because some spacewalks, sleep shifts and faults fall inside an
  illness's window (it starts 2 days before onset), so they share its alert.
- Lead time in whole days counts calendar days (alert on symptom day = 0, the
  day before = 1). The exact SPEC value subtracts times, and assessments run
  at 10:00 after the 07:00 check-in, so an alert the day before is 0.875.

Reproduce (about 15 s per config; `data/` is git-ignored):

```bash
python -m orbit.evaluation --config orbit.toml --days 180 --crew 4 --seeds 1 2 3 4 5 \
    --out data/reports/evaluation.json
```

### Learned scorer vs starter (B10)

**Simulated, not clinical.** The learned scorer (`experiments/learned.toml`,
weights `trained-s1-20-d180-c4`) against the starter `rule_based`, on seeds 101
to 105, which the training never saw. 180 days x 4 crew, same baseline and
detector, an alert is yellow or worse:

| Metric (mean ± SD over 5 seeds) | `rule_based` (starter) | `learned` |
|---|---|---|
| Sensitivity | 1.00 ± 0.00 (45 of 45) | 1.00 ± 0.00 (45 of 45) |
| Lead time, median, whole days before symptom day | 0.1 ± 0.2 | 0.4 ± 0.4 |
| Lead time, median, exact (SPEC M9) | -0.03 ± 0.22 days | 0.28 ± 0.42 days |
| False alarms per 30 astronaut-days | 0.00 ± 0.00 | 0.00 ± 0.00 |
| Confounder alert rate | 0.14 ± 0.06 | 0.15 ± 0.07 |

- The learned scorer warns earlier with no more false alarms: it caught 24 of
  45 illnesses before symptom day (18 one day early, 6 two days), the starter
  16 of 45 (13 and 3).
- It meets the switch rule (sensitivity and lead time at least as good, false
  alarms no higher), and the demo story holds with it (yellow on day 89, orange
  71 on day 90).
- **`orbit.toml` still uses `rule_based`: the team held the switch back.** The
  learned weights barely count what the astronaut reports. A check-in with
  moderate fever, sore throat, low mood and high stress scores 4 points
  (starter: over 20), so the check-in and the live demo (`tools/live_demo.py`)
  would no longer turn yellow. In the simulator symptoms never come without
  vital or lab changes, so the model learned to rely on those. The three
  numbers above do not measure this.
- To switch later: give symptoms a floor in the trainer (or add symptom-only
  illnesses to the simulator), retrain, rerun this comparison.

Reproduce (about 30 s; the report is committed as `reports/learned_vs_starter.json`,
with config paths made relative):

```bash
python -m orbit.evaluation --config orbit.toml --config experiments/learned.toml     --days 180 --crew 4 --seeds 101 102 103 104 105 --out reports/learned_vs_starter.json
```
