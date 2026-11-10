# ORBIT architecture and module specs

This file is the build spec for ORBIT. It is written so a Claude Code agent
(or a person) can build any one module without reading the rest of the code
first.

**How to use it**

1. Read **Part 1** (system and rules) and **Part 2** (code map) in full.
2. Find your module in **Part 3**. It says which files you own, the
   interface you plug into, what you must guarantee, and when you are done.
3. Read the files listed under *Read first* in your section before coding.
4. Do not edit files you do not own unless your section says so.
5. Finish with the checklist in *Definition of done* (Part 1) and in your section.

---

# Part 1: The system

## What ORBIT does

On long missions, astronauts must spot health changes themselves. ORBIT is an
immune early-warning system: it gathers health indicators (wearable vitals,
sleep, daily symptom check-ins, onboard lab tests, stressors such as solar
events), compares each astronaut with **their own** normal, and turns changes
into a traffic-light status with plain-language reasons and concrete actions.
It runs fully onboard, without Earth.

## Data flow

```
  DATA SOURCES                 BACKBONE                         ANALYTICS SLOTS
  ────────────                 ────────                         ───────────────
  files      (M3)  ─┐
  simulator  (M2)  ─┼─ ingest ─▶ Store (SQLite) ──context──▶ baseline  (M6)
  donki      (M5)  ─┘              ▲                            │ list[Baseline]
                                   │                            ▼
  check-in (M11) ── API ───────────┤                         detector  (M7)
                                   │                            │ list[Anomaly]
                                   │                            ▼
                                   │                         scorer    (M8)
                                   │                            │ RiskAssessment
                                   │                            ▼
                                   └──── save_day ◀───────── actions   (M10)
                                                                  list[ActionCard]
  Store ──▶ API ──▶ dashboard (M12), crew view (M14)
  Store ──▶ sync slot (M13, consent filter) ──▶ Earth
  Pipeline.run() on simulator data ──▶ evaluation (M9)
```

The **pipeline** (`orbit/core/pipeline.py`) is the only place modules are
connected. It calls them in order and saves results to the **store**
(`orbit/core/store.py`). Modules never call each other or the database.

## Design principles and what they mean for code

| Principle | Consequence for your code |
|---|---|
| Offline first | No network at run time. Only data sources built for a ground uplink (M5) may fetch, and they must also work from a local cache. Frontends load no fonts, scripts or icons from CDNs. |
| Personal baselines | Compare each astronaut with their own history, never with population "normal" ranges. |
| Explainable | Every point of a risk score has a plain-language reason the astronaut can check. |
| Astronaut in control | Symptoms and wellbeing stay onboard unless the astronaut shares them. Respect `CrewMember.share_with_earth`. |
| Degrade, don't die | A module error must never stop the system. The pipeline isolates stages; you must not catch-and-hide errors inside your module either: raise clearly. |
| Always runnable | `python -m orbit demo` must work after every change. Starter modules stay registered as fallbacks. |

## Rules for every agent (MUST)

1. **Use the schema models** from `orbit.schema` for all data crossing a
   module boundary. Never pass raw dicts between modules.
2. **Time is timezone-aware UTC.** Use `datetime.now(timezone.utc)`, never a
   naive datetime. **Analytics modules never read the clock**: use `ctx.as_of`.
3. **Units, labels, ranges and scales come from the signal registry**
   (`get_spec(signal)`). Never hard-code them.
4. **Analytics modules are pure** (slots baseline, detector, scorer, actions,
   sync): no database, no network, no file writes, no global mutable state, no
   unseeded randomness. Same input gives the same output. Configuration arrives
   only through constructor options.
5. **Every constructor option has a default.** The contract tests build each
   module with no options.
6. **Register, don't replace.** Add your module with `@register(...)`, import it
   in `orbit/modules/__init__.py`, and keep the starter registered.
7. **Do not edit `orbit/schema/` or `orbit/core/`** unless your section says so.
   If a change is unavoidable: keep it minimal and backward-compatible, run the
   full test suite, and say so in your summary.
8. **Do not hand-edit `examples/*.jsonl`.** Change `examples/make_examples.py`
   and regenerate. The tests use these files as fixtures.
9. **Dependencies:** prefer the standard library, numpy and pandas. Add any new
   dependency to `pyproject.toml`.
10. **Medical content is illustrative.** Never present weights, thresholds or
    action cards as clinical guidance. No medication doses.
11. **Text shown to astronauts** is short, plain language, sentence case, no
    jargon (for example "Skin temperature 0.4 °C above your normal for 2 days").
12. **Tests:** add `tests/test_<module>.py`. Tests never touch the network.

## Definition of done (every module)

- [ ] `python -m pytest` passes, including `tests/test_contracts.py`.
- [ ] `python -m orbit demo` runs with your module active in the config.
- [ ] `python -m orbit modules` lists your module.
- [ ] The module docstring says what it does, why, and every option.
- [ ] `orbit.toml` contains an example config block (commented out if not active).
- [ ] Anything other teammates see (API, files, config) is documented here or in README.md.

---

# Part 2: Code map

## Layout and ownership

```
orbit/
  schema/            M1 data contract (done)
    enums.py         signal types, sources, quality, alert levels ...
    signals.py       signal registry: unit, plausible range, concern direction
    models.py        Observation, ContextEvent, CrewMember, Baseline, Anomaly,
                     Contributor, RiskAssessment, ActionCard
    io.py            JSONL / CSV / pandas readers and writers
    export.py        JSON Schema + signals.json export
  core/              backbone (done)
    interfaces.py    the slots (protocols) and the data passed between stages
    store.py         M4 shared SQLite store (done)
    pipeline.py      runs the stages, isolates failures, hooks
    registry.py      @register / create / available
    config.py        orbit.toml loader
  modules/           one starter per slot; teams add their modules here
    sources.py       source: files, memory              (M3 extends)
    baseline.py      baseline: rolling_median           (M6)
    detector.py      detector: robust_z                 (M7)
    scorer.py        scorer: rule_based                 (M8)
    actions.py       actions: card_library              (M10)
    consent.py       sync: consent_gate                 (M13)
  api/app.py         FastAPI app (frontend + live feeds)
  __main__.py        CLI: demo, serve, ingest, run, status, modules, reset
orbit.toml           which implementation fills each slot
examples/            fixture data + make_examples.py
schemas/             exported JSON Schemas + signals.json
tests/               schema, store, pipeline, contract and API tests
```

## Data contract (`orbit.schema`)

All models are immutable pydantic v2 models that reject unknown fields.

| Model | Fields (defaults in brackets) | Helpers |
|---|---|---|
| `Observation` | `observation_id` [uuid], `astronaut_id`, `timestamp`, `signal`, `value`, `unit` [filled from registry], `source`, `quality` [good], `simulated` [False], `device_id`, `note` | `.spec`, `.category`, `.is_usable` |
| `ContextEvent` | `event_id` [uuid], `event_type`, `start`, `end` [None], `severity` [moderate], `astronaut_id` [None = whole crew], `source` [ground], `external_id`, `description`, `simulated` | `.affects(id)`, `.overlaps(start, end)` |
| `CrewMember` | `astronaut_id`, `callsign`, `role`, `mission_start`, `share_with_earth` [vital, sleep, lab, context] | `.mission_day(t)`, `.shares(category)` |
| `Baseline` | `astronaut_id`, `signal`, `as_of`, `center`, `spread` (≥0, ~1 SD), `n_samples`, `window_days`, `method` | `.low`, `.high` |
| `Anomaly` | `astronaut_id`, `signal`, `detected_at`, `kind` (spike/drift), `value`, `baseline_center`, `baseline_spread`, `deviation` (signed robust z), `consecutive_days` [1] | `.delta` |
| `Contributor` | `label` (≤160 chars), `points` (≥0), `signal` [None], `event_id` [None] | |
| `RiskAssessment` | `assessment_id` [uuid], `astronaut_id`, `assessed_at`, `score` (0–100), `level` [derived from score], `contributors` [sorted by points, descending], `model_version` | `.top_reasons(n)` |
| `ActionCard` | `card_id` (slug), `level`, `title`, `steps` (≥1), `rationale`, `escalate_to` [self], `triggers` [()] | |

Validation rules: timestamps need a timezone and are stored in UTC; `unit`
must equal the signal's unit; each signal accepts only certain sources
(symptoms only from `checkin`); values outside the plausible range are allowed
only with `quality` bad or suspect; ordinal scales are whole numbers; a
`RiskAssessment`'s level must match its score.

Alert levels (`LEVEL_THRESHOLDS`, `level_for_score`): green < 25 ≤ yellow < 50
≤ orange < 75 ≤ red. `AlertLevel.rank` orders them 0–3.

**Signals** (25; `get_spec(signal)` gives label, unit, range, concern direction,
cadence, scale labels, allowed sources):

| Category | Signals (unit, worrying direction) | Source, cadence |
|---|---|---|
| vital | `skin_temp` (degC, up), `resting_hr` (bpm, up), `hrv_rmssd` (ms, down), `resp_rate` (breaths/min, up), `spo2` (pct, down) | wearable/manual, nightly |
| sleep | `sleep_duration` (h, down), `sleep_efficiency` (pct, down) | wearable/manual, nightly |
| symptom | `symptom_fatigue`, `_fever_chills`, `_sore_throat`, `_swollen_glands`, `_mouth_sores`, `_rash_tingling`, `_headache`, `_muscle_aches` (0–3, up) | checkin, daily |
| wellbeing | `mood` (1–5, down), `stress` (1–5, up) | checkin, daily |
| lab | `saliva_ebv_dna`, `saliva_vzv_dna`, `saliva_hsv1_dna` (copies/mL, up), `saliva_cortisol` (nmol/L, up), `wbc_count` (10^9/L, both), `crp` (mg/L, up) | lab/manual, on demand |
| context | `radiation_dose_daily` (mGy, up), `workload` (h, up) | environment/ground/manual, daily |

File helpers: `parse_jsonl`, `parse_csv`, `parse_records` (return a
`ParseResult` with `.valid`, `.errors`, `.raise_if_errors()`), `write_jsonl`,
`write_csv`, `to_dataframe`, `from_dataframe`.

## Slots (`orbit/core/interfaces.py`)

| Slot | Protocol | Method | Starter |
|---|---|---|---|
| `source` | `DataSource` | `read() -> SourceBatch` | `files`, `memory` |
| `baseline` | `BaselineEngine` | `compute(ctx) -> list[Baseline]` | `rolling_median` |
| `detector` | `AnomalyDetector` | `detect(ctx, baselines: Mapping[SignalType, Baseline]) -> list[Anomaly]` | `robust_z` |
| `scorer` | `RiskScorer` | `score(ctx, anomalies: Sequence[Anomaly]) -> RiskAssessment` | `rule_based` |
| `actions` | `ActionEngine` | `recommend(assessment, ctx) -> list[ActionCard]` | `card_library` |
| `sync` | `SyncGate` | `package(member, observations, assessments) -> EarthPacket` | `consent_gate` |

**`AssessmentContext`** (what every analytics stage receives, read-only):

```
|──── history: baseline_window_days (14) ────|── recent: recent_days (3) ──| as_of
                                             ^ recent_start
```

| Field / method | Meaning |
|---|---|
| `member`, `astronaut_id`, `mission_day` | who and when |
| `as_of` | the moment being assessed (UTC); the only "now" a module may use |
| `history` | usable readings before `recent_start`, oldest first: for baselines |
| `recent` | usable readings from `recent_start` to `as_of`: for detection and scoring |
| `events` | events affecting this astronaut, from `as_of - event_lookback_days` (7) to `as_of` |
| `history_for(signal)`, `recent_for(signal)` | readings of one signal |
| `latest(signal, within=None)` | newest recent reading, optionally only if newer than `within` |
| `recent_in(category)` | recent readings of one category |

"Usable" means `quality` is not bad. Suspect readings are included; modules
may down-weight them.

Other types: `SourceBatch(source_name, crew, observations, events, errors)`,
`DayResult(astronaut_id, as_of, mission_day, baselines, anomalies, assessment,
actions, errors)`, `EarthPacket(astronaut_id, created_at, observations,
assessments, withheld)`.

## Registry and config

```python
from orbit.core.registry import register

@register("detector", "cusum")      # slot, name
class CusumDetector:
    def __init__(self, k: float = 0.5, h: float = 4.0): ...
    def detect(self, ctx, baselines): ...
```

`create(slot, name, **options)` builds a module and checks it implements the
slot; `available(slot)` lists names. Built-in modules are loaded by importing
`orbit.modules`, so **every new module file must be imported in
`orbit/modules/__init__.py`**.

`orbit.toml`:

```toml
[mission]   name, assessment_hour_utc (10)
[storage]   database ("data/orbit.db")
[pipeline]  baseline_window_days (14), recent_days (3), event_lookback_days (7)
[modules.<slot>]  use = "<name>", then the module's options
[[sources]]       use = "<name>", then the source's options (one block per source)
```

Option keys ending in `_path` are resolved relative to `orbit.toml`. Unknown
top-level sections are ignored; unknown `[modules.x]` slots are an error.
Use `experiments/<name>.toml` copies to try modules without changing the
main config (`python -m orbit --config experiments/x.toml demo`).

## Pipeline (`orbit/core/pipeline.py`)

| Method | Does |
|---|---|
| `Pipeline.from_settings(settings, store=None)` | builds the store and every configured module |
| `ingest(source_or_batch) -> IngestReport` | saves crew, then observations (unknown astronauts rejected), then events |
| `context(astronaut_id, as_of) -> AssessmentContext` | builds the snapshot |
| `assess(astronaut_id, as_of, save=True) -> DayResult` | baseline → detector → scorer → actions; each stage isolated, failures recorded in `errors` |
| `run(start=None, end=None, astronaut_ids=None) -> RunReport` | one assessment per astronaut per day at `assessment_hour_utc`; defaults to every day with data |
| `status(astronaut_id) -> DayResult \| None` | latest saved result |
| `earth_packet(astronaut_id, start, end) -> EarthPacket` | runs the sync slot |
| `on("ingested" \| "assessed", callback)` | hooks; a failing listener is logged and ignored |

Re-running the same astronaut and moment replaces the earlier result.

## Store (`orbit/core/store.py`)

`upsert_crew`, `crew`, `member`, `add_observations`,
`observations(id, signals=, start=, end=, usable_only=True)`, `data_range`,
`add_events`, `events(id=None, start=, end=)` (includes crew-wide events),
`save_day`, `assessments`, `latest_assessment`, `recommendations(assessment_id)`,
`anomalies_at(id, as_of)`, `baselines(id, signal=, start=, end=)`, `counts`.
Writes with the same ID replace the old row.

## API (`orbit/api/app.py`)

`GET /api/health`, `/api/signals`, `/api/crew`, `/api/overview`,
`/api/crew/{id}/status`, `/api/crew/{id}/observations?signal=&start=&end=&include_bad=`,
`/api/crew/{id}/baselines?signal=`, `/api/crew/{id}/assessments`,
`/api/crew/{id}/earth-packet?start=&end=`, `/api/events`;
`POST /api/crew/{id}/checkin`, `/api/observations`, `/api/pipeline/run`.
OpenAPI at `/openapi.json`, interactive docs at `/docs`.

## Contract tests (`tests/test_contracts.py`)

Every registered module is tested automatically against its slot:

| Slot | Must hold |
|---|---|
| source | builds with no options; `read()` returns a `SourceBatch` with a non-empty `source_name` |
| baseline | non-empty for AST-01 on day 90; `as_of == ctx.as_of`; one per signal; **same result with `recent` removed**; empty history gives `[]` |
| detector | finds anomalies for AST-01 on day 90; only signals that have a baseline; `{}` baselines gives `[]` |
| scorer | correct `astronaut_id` and `assessed_at`; deterministic; scores sick AST-01 above healthy AST-02 on day 90 |
| actions | at least one card for scores 0, 30, 60, 90; no card above the assessment's level |
| sync | only shared categories leave; sent + withheld = all readings; score and level kept; private reasons redacted |

## Demo scenario (fixtures)

`examples/`: mission days 70–90 (2027-03-14 to 2027-04-03), astronauts
AST-01 "Vega" and AST-02 "Altair". AST-01 develops shingles (VZV) reactivation:
vitals shift on day 89, more on day 90; fatigue on day 89, fatigue + rash on
day 90; saliva VZV 850 copies/mL on day 90. Events: spacewalk (AST-01, day 88),
solar particle event (crew, day 89–90). One faulty AST-02 reading is stored
with `quality="bad"`.

With the starter modules: AST-01 green on day 88, **yellow (27.7) on day 89**,
**orange (70.2) on day 90**; AST-02 green throughout.
`tests/test_pipeline.py::test_demo_scenario_end_to_end` pins this story for
the active config. If your module changes it, update the test only on purpose:
the pitch demo relies on it.

---

# Part 3: Module specs

## M1: Data schema (done)

**Owner files:** `orbit/schema/`. **Status:** complete.

Change it only when a module spec below says so (M2 adds `labels.py`).
To add a signal: add it to `SignalType` (`enums.py`) and a `SignalSpec`
(`signals.py`), then run `python -m pytest` and `python -m orbit.schema export schemas`.
A breaking change (renaming or removing a field) needs a major
`SCHEMA_VERSION` bump in `models.py`, which makes old databases refuse to open.

---

## M2: Mission simulator

**Owner files:** `orbit/modules/simulator.py` (or a package
`orbit/modules/simulator/`), `orbit/schema/labels.py` (new, shared with M9),
`experiments/sim180.toml`, `tests/test_simulator.py`.
**Slot:** `source`, registered as `simulator`. **Unblocks:** M9.

**Goal.** Generate a realistic, labelled long-duration mission: every
astronaut's daily data plus illness episodes and look-alike confounders,
with ground-truth labels so M9 can measure detection.

**Read first:** `orbit/schema/signals.py`, `orbit/schema/models.py`,
`orbit/modules/sources.py`, `examples/make_examples.py` (similar generator, small).

**Options (all defaulted; keep defaults fast for the contract test):**

| Option | Default | Meaning |
|---|---|---|
| `days` | 60 | mission length in days |
| `crew_size` | 4 | astronauts `AST-01` … `AST-NN` |
| `seed` | 1 | all randomness comes from this |
| `mission_start` | `"2027-01-04T00:00:00Z"` | day 1 |
| `scenarios` | `"random"` | `"random"`, or a list of inline tables, e.g. `{type = "viral_reactivation", astronaut = "AST-02", virus = "vzv", symptom_day = 90}` |
| `illness_rate` | 1.0 | for `"random"`: illness episodes per astronaut per 90 days |
| `confounders` | true | add look-alike episodes that should not alert |
| `faults` | true | add sensor faults and missing nights |
| `labels_path` | none | if set, write labels as JSONL here |

**Output.** `read()` returns a `SourceBatch(source_name="simulator", crew,
observations, events)`. Every record has `simulated=True`. Also provide
`labels() -> list[ScenarioLabel]` for in-process use by M9.

**Daily records per astronaut** (same times as the fixtures):

| Time (UTC) | Records |
|---|---|
| 06:00 | 5 vitals + 2 sleep signals, `source="wearable"`, `device_id="wrist-<id>"` |
| 07:00 | all 8 symptoms (0 when absent), `mood`, `stress`, `source="checkin"` |
| 09:00 | weekly saliva EBV/VZV/HSV-1 DNA (low or below 100 copies/mL when healthy), plus extra tests during illness, `source="lab"` |
| 23:59 | `radiation_dose_daily`, `workload`, `source="environment"` |

IDs are deterministic: `f"{astronaut}-{signal}-{yyyymmdd}"` (add the hour
for extra lab tests), so re-ingesting replaces instead of duplicating.

**Physiology model (illustrative):** each astronaut gets a personal normal
drawn once from: skin temp 33.5–35.0 °C, resting HR 48–65 bpm, HRV 30–90 ms,
respiratory rate 13–16, SpO₂ 95.5–98 %, sleep 6.0–7.5 h, efficiency 84–93 %.
Night-to-night noise (SD): temp 0.08, HR 1.0, HRV 4–5 % of normal, resp 0.2,
SpO₂ 0.3, sleep 0.3 h, efficiency 1.8. Use AR(1) noise (φ ≈ 0.3) so nights
are mildly correlated. Clamp to plausible ranges.

**Scenarios (`ScenarioType`)** with illustrative effects. "Day 0" is symptom onset:

| Type | should_alert | Effect |
|---|---|---|
| `viral_reactivation` (virus ebv/vzv/hsv1) | yes | From day −`lead_days` (default 2, configurable 1–3): temp +0.2→+0.6 °C, HR +2→+7, HRV −10→−30 %, resp +0.4→+1.2, sleep −0.3→−1.0 h. Saliva DNA of that virus rises from day −3. From day 0: fatigue 1–2 plus the virus's sign (VZV `rash_tingling`, HSV-1 `mouth_sores`, EBV `swollen_glands` + `sore_throat`). Recovers over 5–10 days. |
| `respiratory_infection` | yes | temp +0.8, resp +2, HR +8, `fever_chills` and `sore_throat` 1–3, CRP rises |
| `eva_exertion` | no | `EVA` event; workload 12 h; next night HRV −15 %, HR +3; no symptoms |
| `sleep_shift` | no | `SLEEP_SHIFT` event; sleep −1.5 h for 2–3 nights |
| `solar_particle_event` | no | crew-wide event; radiation dose ×2–5 for 1–2 days; no physiology change |
| `sensor_fault` | no | a few readings with absurd values stored with `quality="bad"` and a note |
| `missing_data` | no | no wearable records for 1–2 nights |

The gap between physiological onset and symptom onset is the early-warning
window ORBIT must find. Keep it configurable.

**`orbit/schema/labels.py`** (export from `orbit/schema/__init__.py`; agree any
change with M9):

```python
class ScenarioType(StrEnum): ...   # the 7 types above

class ScenarioLabel(_Model):        # same base config as other schema models
    label_id: str
    astronaut_id: AstronautId
    scenario: ScenarioType
    virus: Literal["ebv", "vzv", "hsv1"] | None = None
    onset: UtcDatetime                 # physiological onset
    symptom_onset: UtcDatetime | None = None
    resolved: UtcDatetime | None = None
    should_alert: bool
    notes: str | None = None
```

**Requirements.** Same options give byte-identical output. 180 days × 4
crew in under 5 seconds. Every record passes schema validation. Use either
the `files` source or the simulator in one config, not both (IDs would clash).

**Config:** create `experiments/sim180.toml` (copy of `orbit.toml` with
`[[sources]] use = "simulator"`, `days = 180`, `labels_path = "data/sim/labels.jsonl"`).

**Tests:** determinism; record counts per day; a viral episode raises mean
skin temperature in its prodrome; `symptom_onset ≥ onset`; confounders have
`should_alert=False`; faulty readings have `quality="bad"`.

**Done when:** `python -m orbit --config experiments/sim180.toml demo` runs, and
an injected viral episode turns at least yellow with the starter modules.

---

## M3: Ingestion of real device exports

**Owner files:** `orbit/modules/ingestion.py`, `tests/test_ingestion.py`,
`tests/fixtures/ingestion/*.csv`. May extend `orbit/modules/sources.py`.
**Slot:** `source`, registered as `wearable_csv`.

**Goal.** Load real wearable exports safely: map vendor columns to signals,
convert units, attach a timezone, flag bad data instead of dropping it, and
report every problem with its row number.

**Read first:** `orbit/schema/io.py`, `orbit/schema/signals.py`, `orbit/modules/sources.py`.

**Options:**

| Option | Default | Meaning |
|---|---|---|
| `path` | none | CSV file (wide format: one row per night) |
| `astronaut_id` | none | used when the file has no astronaut column |
| `timestamp_column` | `"date"` | column with the date or time |
| `timezone` | none | IANA name applied to naive timestamps; **required** if timestamps are naive |
| `columns` | `{}` | vendor column → signal, e.g. `{"Resting HR" = "resting_hr"}` |
| `units` | `{}` | signal → vendor unit, e.g. `{skin_temp = "degF"}` |
| `device_id` | none | stored on every reading |

**Conversions:** degF→degC `(x − 32) × 5/9`; fraction→pct `× 100` for `spo2`
and `sleep_efficiency`; min→h and s→h for sleep duration. An unknown
unit is a `RowError`, never a guess. Relative "deviation" columns (as some
rings export) cannot become absolute values: reject them with a clear error.

**Quality rules:** outside the plausible range → keep it with `quality="bad"` and
a note giving the raw value; a vendor flag such as low wear time → `suspect`; the
same astronaut, signal and timestamp twice → keep the last one; empty cells → skip
silently.

**Output:** `SourceBatch(source_name=f"wearable_csv:{filename}", ...)` with row-numbered errors.

**Optional:** expose `normalize_records(records) -> ParseResult` so the API can
use it later. Do not change the API yourself.

**Done when:** the fixtures for °F, fractions, naive timestamps, out-of-range
values and duplicates all import as specified; the contract test passes.

---

## M4: Shared store (done)

**Owner files:** `orbit/core/store.py`. **Status:** complete.

To add a table (M13 will): add `CREATE TABLE IF NOT EXISTS` to `_TABLES`;
store the full record as JSON in `doc` plus indexed filter columns; store
times as integer microseconds with `_ts()`; write inside `with self._tx()`;
re-validate on read with `_docs(Model, sql, params)`; add it to `counts()`;
test in `tests/test_store.py`. Never let modules import the store.

---

## M5: Space weather feed (NASA DONKI)

**Not planned for this version.** Its task (B12) was dropped. The design below
stays for later; until then, solar events come from the simulator (M2) and the
example data.

**Owner files:** `orbit/modules/space_weather.py`, `tests/test_space_weather.py`,
`tests/fixtures/donki/*.json` (recorded responses).
**Slot:** `source`, registered as `donki`.

**Goal.** Turn real space-weather events into `ContextEvent`s so solar storms
count as immune stressors. On a real mission the ground fetches and uplinks, and
the spacecraft reads a local cache. Model exactly that.

**API:** `https://api.nasa.gov/DONKI/{FLR|SEP|CME|GST}?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&api_key=KEY`
(dates inclusive). Key from the `NASA_API_KEY` environment variable, falling
back to `DEMO_KEY` (heavily rate-limited). Expected fields, **to be confirmed on
a live response before mapping**: FLR `flrID`, `beginTime`, `peakTime`,
`endTime`, `classType`; SEP `sepID`, `eventTime`; CME `activityID`,
`startTime`; GST `gstID`, `startTime`, `allKpIndex[].kpIndex`.

**Options:**

| Option | Default | Meaning |
|---|---|---|
| `mode` | `"cache"` | `"cache"` reads `cache_path` only (onboard, offline); `"fetch"` downloads and writes the cache (ground) |
| `cache_path` | `"data/donki_cache.json"` | raw responses keyed by endpoint |
| `real_start`, `real_end` | none | real date range to fetch or replay |
| `mission_start` | none | if set, shift real dates so `real_start` lands on this date: a simulated 2027 mission replays real solar history |
| `include_cme` | false | CMEs alone are noisy; their effects show up as SEP/GST |

**Mapping:** FLR → `solar_flare`, SEP → `solar_particle_event`, CME → `cme`,
GST → `geomagnetic_storm`; `astronaut_id=None` (whole crew), `source="ground"`,
`external_id` = the DONKI ID, `event_id = f"donki-{external_id}"` (re-ingest
replaces). Severity: flare class X10+ extreme, X high, M moderate, C and B low;
storm max Kp 9 extreme, 8 high, 7 moderate, 5–6 low; SEP moderate. End time:
FLR `endTime`; SEP start + 12 h; GST start + 3 h × number of Kp readings
(document these assumptions in the docstring).

**Requirements:** no network in `cache` mode or in tests; a missing cache gives
an empty batch with a `RowError`, not a crash; a network error in `fetch` mode
raises with a clear message.

**Done when:** the recorded fixtures map correctly, including time shift and
severity, and a replayed storm appears in the scorer's reasons during the demo.

---

## M6: Personal baseline

**Owner files:** `orbit/modules/<name>.py` (e.g. `baseline_ewma.py`),
`tests/test_<name>.py`. **Slot:** `baseline`. **Starter:** `rolling_median`
(median + 1.4826 × MAD, spread floors in `MIN_SPREAD`, needs `min_samples=5`).

**Goal.** Learn each astronaut's normal per signal, robust to bad nights and
able to follow slow in-flight adaptation without absorbing an illness.

**Read first:** `orbit/modules/baseline.py`, `AssessmentContext` in `orbit/core/interfaces.py`.

**Input → output:** `compute(ctx) -> list[Baseline]` using **only `ctx.history`**.

**Requirements:**
- `as_of = ctx.as_of`, `astronaut_id = ctx.astronaut_id`, `window_days =
  ctx.baseline_window_days`, accurate `n_samples`, `method` set to your name.
- At most one baseline per signal; skip signals with too little data.
- `spread > 0` and roughly one standard deviation, because the detector divides
  by it and the dashboard draws `center ± spread` as "your normal". Reuse the
  `MIN_SPREAD` floors.
- Continuous vital and sleep signals at minimum; ordinal signals optional.

**Ideas:** exponentially weighted median or mean (half-life about 7 days);
separate pre-flight (`mission_day ≤ 0`) and in-flight baselines; down-weight
`suspect` readings.

**Done when:** the contracts pass, and the M9 comparison with `rolling_median`
is recorded in your module docstring (lead time, false alarms).

---

## M7: Anomaly detector

**Owner files:** `orbit/modules/<name>.py`, `tests/test_<name>.py`.
**Slot:** `detector`. **Starter:** `robust_z` (spike if the latest reading is
≥ 2.5 spreads off; drift if the last 2 readings are ≥ 1.5 off; worrying
direction only).

**Goal.** Find meaningful departures from the personal baseline as early as
possible, without alarming on single noisy nights.

**Read first:** `orbit/modules/detector.py` (reuse `concern_score`), `orbit/schema/signals.py`.

**Input → output:** `detect(ctx, baselines) -> list[Anomaly]`, using `ctx.recent_for(signal)`.

**Requirements:**
- Only signals present in `baselines`; skip `spread <= 0`; no recent readings
  means no anomaly.
- **At most one anomaly per signal** (the scorer assumes this).
- Only the worrying direction (`get_spec(signal).concern`).
- `deviation = (value − center) / spread` (signed); `detected_at` = timestamp
  of the newest reading used; `value` = that reading (spike) or the mean of the
  run (drift); `consecutive_days ≥ 1`.
- Combining signals is the scorer's job; anomalies stay per signal.

**Ideas:** CUSUM (catches slow drifts earlier); EWMA control charts; a
persistence rule tuned on simulator data.

**Done when:** the contracts pass and M9 shows equal or better lead time than
`robust_z` without more false alarms.

---

## M8: Risk scorer

**Owner files:** `orbit/modules/<name>.py`, `tests/test_<name>.py`.
**Slot:** `scorer`. **Starter:** `rule_based` (points per anomaly, symptom,
lab result, wellbeing flag and event; capped at 100).

**Goal.** Turn all evidence into one 0–100 score that is easy to explain and
ranks real illness above everyday stress.

**Read first:** `orbit/modules/scorer.py` (reuse `describe_anomaly`,
`CHECKIN_FRESHNESS`, `EVENT_NAMES`), `orbit/schema/models.py` (`RiskAssessment`).

**Input → output:** `score(ctx, anomalies) -> RiskAssessment`. Symptoms, labs
and wellbeing come from `ctx.latest(...)`, events from `ctx.events`.

**Requirements:**
- `astronaut_id = ctx.astronaut_id`, `assessed_at = ctx.as_of`, `score` in
  0–100, leave `level` out (it is derived), set `model_version`.
- **Every point has a `Contributor`** with a plain-language label for the
  astronaut, and its `signal` or `event_id` set. Action cards trigger on these
  signals, and the consent gate redacts by them.
- The points add up to the score before the cap.
- Use check-ins only if fresh (≤ 36 h); ignore events that start after `as_of`.
- Deterministic. Do not read the clock.

**Ideas:** a bonus when three or more vital signals move together; time decay
for events; viral DNA trend instead of a single value; weights fitted on M9
results, kept as readable points.

**Done when:** the contracts pass; the demo story (Part 2) holds or the team
agreed on a new one; M9 numbers are recorded in your docstring.

---

## M9: Evaluation

**Owner files:** `orbit/evaluation/` (`__init__.py`, `metrics.py`,
`runner.py`, `__main__.py`), `tests/test_evaluation.py`.
**Not a slot.** **Needs:** M2 (`simulator` source and `ScenarioLabel`).

**Goal.** Give the pitch real numbers: how many days before symptoms ORBIT
warns, how often it raises false alarms, and which module version is better.

**Read first:** `orbit/core/pipeline.py`, `orbit/core/config.py`, M2's `labels.py`.

**CLI:**
```bash
python -m orbit.evaluation --config orbit.toml --config experiments/<other>.toml \
    --days 180 --crew 4 --seeds 1 2 3 4 5 --out data/reports/evaluation.json
```
For each config and seed: build the simulator with these options (they
override the config's sources), run `Pipeline.from_settings(settings,
store=Store(":memory:")).run()`, and compare the assessments with the labels.
Every config sees identical data.

**Metrics (exact definitions):**
- *Alert*: an assessment with level ≥ `min_level` (default yellow).
  *Episode*: consecutive days with alerts.
- *Window* of a label: from `onset − 2 days` to `resolved`, or `onset + 14 days` if `resolved` is not set.
- *Sensitivity*: share of `should_alert` labels with at least one alert in their window.
- *Lead time*: `symptom_onset − first alert in the window`, in days (positive
  means before symptoms). Report the median and the range.
- *False alarms*: episodes that overlap no `should_alert` window, per 30
  astronaut-days. Report the episodes that overlap confounder windows separately.

**Output:** JSON with per-config and per-scenario numbers (mean ± SD over
seeds), plus a printed table: config, active module names, sensitivity, median
lead time, false alarms per 30 days, confounder alert rate.

**Done when:** it runs on the starter config, and the README's *Results* section
quotes the numbers (marked as simulated).

---

## M10: Action engine

**Owner files:** `orbit/modules/actions.py` (extend) or a new module;
`cards/action_cards.jsonl` (new hand-edited library); `tests/test_actions.py`.
**Slot:** `actions`. **Starter:** `card_library` (cards at the assessment's
level whose `triggers` match a contributor signal; falls back to the closest
lower level).

**Goal.** Always give the astronaut a clear, doable next step that fits the
reasons for their status, and say who else must know.

**Read first:** `orbit/modules/actions.py`, `examples/action_cards.jsonl`,
`ActionCard` in `orbit/schema/models.py`.

**Input → output:** `recommend(assessment, ctx) -> list[ActionCard]`.

**Requirements:**
- At least one card for every level; never a card above the assessment's level.
- Cards that match a reason come first; at most `max_cards` (default 3).
- Orange and red cards set `escalate_to`.
- Card text: imperative steps under 200 characters, doable onboard, no medication
  doses, and a rationale in plain language.
- If you move the library to `cards/action_cards.jsonl`, add a test that it
  validates, point `cards_path` in `orbit.toml` to it, and keep the demo test passing.

**Ideas:** virus-specific cards (VZV: check skin and photograph the rash);
follow-up steps ("repeat the saliva test in 48 hours"). Escalation after several
orange days needs past assessments in the context, which is a core change:
propose it, do not build it alone.

---

## Frontend (shared rules for M11, M12, M14)

**Location:** `frontend/`, one app with routes `/` (dashboard, M12),
`/checkin` (M11), `/crew` (M14). **Stack:** React + TypeScript + Vite; charts
with a bundled library (for example Recharts). If the team picked Streamlit
instead, use `ui/` and still call the HTTP API, never the store.

**Rules:**
- Backend: `python -m orbit serve` (loads the example data automatically).
  API base URL `import.meta.env.VITE_API_URL ?? "http://localhost:8000"`.
- **Types are generated, not hand-written:**
  `npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.ts`.
- **Labels, units, scale words and level thresholds come from `GET /api/signals`.**
  Never hard-code them.
- Levels use color **plus** text and an icon (never color alone); readable in a
  dim cabin; large touch targets; nothing loaded from a CDN at run time.
- Show **mission time** from the data (`as_of`, `mission_day`), not the wall
  clock. The demo data is set in 2027.

`DayResult` (returned by `/status` and `/checkin`):
```json
{"astronaut_id": "AST-01", "as_of": "2027-04-03T10:00:00Z", "mission_day": 90,
 "assessment": {"score": 70.2, "level": "orange", "contributors":
   [{"label": "Skin temperature 0.45 °C above your normal for 2 days", "points": 9.0,
     "signal": "skin_temp", "event_id": null}], "model_version": "rule_based-0.1"},
 "actions": [{"card_id": "reduce-load", "title": "Reduce workload and rest",
   "steps": ["..."], "escalate_to": "crew_medical_officer", "level": "orange"}],
 "anomalies": [...], "baselines": [...], "errors": []}
```

---

## M11: Daily check-in UI

**Owner files:** `frontend/src/routes/checkin/`. **API:** `POST /api/crew/{id}/checkin`.

**Goal.** A check-in that takes under 60 seconds and shows its effect at once.

**Screen:** the 8 symptoms (labels and descriptions from `/api/signals`, scale
words none / mild / moderate / severe), all preset to "none" so only changes
need a tap; mood and stress 1–5 with their scale words; an optional note.
Submit sends `{"timestamp": <ISO time with timezone>, "symptoms":
{"symptom_fatigue": 2}, "mood": 3, "stress": 3, "note": "..."}`. The response is a
`DayResult`: show the new level, the top 3 reasons and the action cards.

**Requirements:** in demo mode, choose the mission date for the timestamp (the data
is in 2027); keep the form filled in and offer a retry if the request fails;
show a 422 error's message next to the form.

---

## M12: Astronaut dashboard

**Owner files:** `frontend/src/routes/dashboard/`, shared components in `frontend/src/components/`.

**Goal.** One glance answers "Am I OK? Why? What do I do?", with trends for those who want detail.

**Views:**
- **Today:** status tile (level word, color, icon, score, mission day,
  time of the assessment); the "Why" list (every contributor with a points bar);
  action cards with their steps as a checklist (ticks kept only on the page);
  who to tell (`escalate_to`).
- **Trends:** a signal picker grouped by category; a line of readings from
  `/observations?signal=`; a shaded "your normal" band from `/baselines?signal=`
  (center ± spread at each `as_of`); event markers from `/api/events`; today's
  anomalies highlighted.
- **History:** the score over time from `/assessments`, with level bands taken from
  `alert_levels` in `/api/signals`.

**Requirements:** refetch after a check-in, and poll `/status` every 60 s;
astronaut switcher for the demo; if `errors` is not empty, show a quiet note that
part of the analysis is unavailable.

---

## M13: Sync and consent

**Owner files:** `orbit/modules/consent.py` (or a new `sync` module); allowed core
changes: a new `outbox` table and its methods in `orbit/core/store.py`, a
`[comms]` section in `orbit/core/config.py`, new endpoints in
`orbit/api/app.py`; `tests/test_sync.py`.
**Slot:** `sync`. **Starter:** `consent_gate`.

**Goal.** The astronaut decides what leaves the spacecraft. What does leave goes
through a queue with a realistic communication delay, and every send is logged.

**Build:**
1. **Consent editing:** `PUT /api/crew/{id}/consent` with body
   `{"share_with_earth": ["vital", "sleep", ...]}`. Validate the categories,
   then `store.upsert_crew(CrewMember.model_validate({...member.model_dump(), ...}))`.
2. **Outbox:** table `outbox(id, astronaut_id, created_ts, deliver_ts, doc)`;
   `[comms] one_way_delay_minutes = 20`;
   `POST /api/crew/{id}/earth-packet/send?start=&end=` packages and queues;
   `GET /api/outbox` lists packets with status `queued` or `delivered`
   (delivered once the current time ≥ `deliver_ts`).
3. Keep `package()` pure. The queue lives in the store and the API, not in the slot.

**Privacy requirements:** never send readings of a category the astronaut does
not share; redact reasons based on private categories; keep `withheld` counts
exact; always send score and level, so a hidden emergency is impossible (document
this choice for the pitch).

---

## M14: Crew and medical officer view

**Owner files:** `frontend/src/routes/crew/`; allowed core change:
`?view=shared` on `GET /api/crew/{id}/status` in `orbit/api/app.py`, plus its test.

**Goal.** The commander and the crew medical officer see who needs attention,
without seeing private details the astronaut has not shared.

**Build:** a grid from `/api/overview` (callsign, level, score, time of the
assessment), worst first, with orange and red highlighted. Clicking opens the
**shared** status: add `view=shared` to the status endpoint, which passes the
assessment through `pipeline.sync.package(...)` so reasons from private
categories show the neutral label. Show who each card escalates to.

---

# Part 4: Build order and coordination

| Module | Can start | Needs | Unblocks |
|---|---|---|---|
| M2 simulator | now | — | M9 |
| M3 ingestion | now | — | real data |
| M5 space weather | now | — | real events |
| M6 / M7 / M8 analytics | now (on example data) | M9 to compare versions | better scores |
| M9 evaluation | after M2's `labels.py` | M2 | the pitch numbers |
| M10 actions | now | — | — |
| M11 / M12 / M14 frontend | now (API is live) | — | the demo |
| M13 sync | now | — | — |

**Shared files:**
- `orbit/schema/` and `orbit/core/`: one change at a time, full test suite,
  mention it in your summary or commit message.
- `orbit/modules/__init__.py`: one import line per module (trivial merge conflicts).
- `orbit.toml`: keep the starters active until a new module passes its contracts
  and its M9 comparison. Try modules in `experiments/*.toml`.

**Commands:**
```bash
pip install -e ".[dev]"
python -m pytest                       # all tests
python -m pytest tests/test_contracts.py
python -m orbit demo                   # whole scenario in memory
python -m orbit --config experiments/x.toml demo
python -m orbit modules                # what is registered and active
python -m orbit serve                  # API on :8000, docs at /docs
python -m orbit.schema validate file.jsonl
```
