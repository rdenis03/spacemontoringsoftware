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
| GET | `/api/crew/{id}/status` | dashboard (M12): level, reasons, actions, anomalies |
| GET | `/api/crew/{id}/observations?signal=&start=&end=` | charts |
| GET | `/api/crew/{id}/baselines?signal=` | "your normal" band |
| GET | `/api/crew/{id}/assessments` | score trend line |
| POST | `/api/crew/{id}/checkin` | check-in form (M11); re-assesses immediately |
| GET | `/api/crew/{id}/earth-packet?start=&end=` | what would go to Earth (M13) |
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
