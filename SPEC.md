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

M15 adds two slots, `extractor` and `reasoner`, used only by the triage service, never by the daily pipeline (see M15).

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

## M15: Symptom triage

**Owner files (B23):** `orbit/schema/triage.py`, `orbit/triage/` (`__init__.py`,
`library.py`, `red_flags.py`, `service.py`, `config.py`), `orbit/modules/extractor.py`,
`orbit/modules/reasoner.py`, `cards/symptom_lexicon.jsonl`, `cards/questions.jsonl`,
`cards/patterns.jsonl`, `cards/triage_cards.jsonl`, `cards/red_flags.jsonl`, and the
tests listed in `tasks/B23-triage-v1.md`. Allowed core changes: `orbit/core/interfaces.py`
(`TriageEvidence`, two protocols, `SLOTS`), `orbit/core/store.py` (`triage_sessions`
only), `orbit/schema/models.py` (`SCHEMA_VERSION` only), exports in
`orbit/schema/__init__.py` and `orbit/core/__init__.py`, `orbit/api/app.py`,
`orbit/__main__.py`, and the `[triage]` block of `orbit.toml`.
**Slots:** `extractor` (starter `lexicon`), `reasoner` (starter `rules`).
**Not a slot:** the triage service. **Tasks:** B23 (version 1, rules), B24 (version 2, models).

**Goal.** The astronaut describes how they feel in their own words. ORBIT maps
the text to its 8 symptom signals (with severity, negation, onset, body site
and side), ranks 8 patterns with a probability and reasons, asks up to 5
follow-up questions, and replies with action cards. It runs onboard and
offline, is deterministic and explainable, and saves nothing until the
astronaut confirms. On confirm, the findings become ordinary `checkin`
observations and `pipeline.assess()` re-scores, so the scorer, action cards,
consent gate, shared view, Earth report and auto-send all work unchanged. The
daily pipeline (`orbit/core/pipeline.py`) does not change.

**Read first:** this section, `orbit/core/interfaces.py`, `Pipeline.assess` in
`orbit/core/pipeline.py`, `orbit/modules/actions.py`, `orbit/modules/scorer.py`,
`cards/action_cards.jsonl`, and tasks/NOTES.md B08, B15, B18 and B19.

```
 text ──▶ red-flag rules ──▶ extractor ──▶ findings ─┐
 answer ─▶ red-flag rules ─────────────────────────────┤
 preview = pipeline.assess(as_of, save=False) ─────────┴─▶ reasoner.rank ─▶ reasoner.next_question
                                                               │                 │
                                                    procedures (when ready)   question or None
 confirm ─▶ checkin observations ─▶ pipeline.assess(as_of) ─▶ merge cards ─▶ store.save_day
```

### Triage service (`orbit/triage/service.py`, not a slot)

- `TriageService` is the only place triage modules meet, as the pipeline is
  for the analytics. It owns all I/O (store, pipeline) and the wall clock for
  session timeouts (an injectable `clock`, like `create_app`). Slot modules stay pure.
- Each turn runs: red-flag rules → extractor (on new free text only) →
  reasoner (rank, then the next question). Procedures are built when the
  session is ready or escalated, and again on confirm. While asking, `procedures` is empty.
- Evidence includes a preview: `pipeline.assess(astronaut_id, as_of, save=False)`
  gives its assessment and anomalies. B18's auto-send already ignores unsaved previews.
- Findings carry what the answers said: the service merges each symptom
  answer into the findings (severity, and `negated` for "none") before the
  reasoner runs, so a reasoner reads symptoms from `evidence.findings` and
  uses `evidence.answers` for the other questions.
- Each step (extractor, preview, rank, next question) runs in an error
  boundary, and errors go to `TriageResult.errors` (like `DayResult.errors`):
  `"<step>: <ExceptionType>: <message>"`. A failing reasoner still leaves the
  re-assessment's cards.
- Methods: `start(astronaut_id, text, timestamp=None) -> TriageResult`,
  `answer(session_id, *, question_id=None, value=None, text=None, done=False) -> TriageResult`,
  `confirm(session_id, corrections=None) -> tuple[TriageResult, DayResult]`,
  `cancel(session_id) -> TriageSession`, `session(session_id)`,
  `sessions(astronaut_id, start=None, end=None)`, and
  `from_settings(triage_settings, pipeline, clock=None)`.
- The analytics `as_of` is the session's timestamp (`timestamp`, or the clock
  when it is not given; mission time in the demo), never the clock after that.
  `started_at` and `updated_at` are wall-clock times. Action cards for pattern
  lookups come from `pipeline.actions.cards` (both action engines keep their library there).
- Answers: `question_id` must be the open question (`next_question` of the
  last result); a question counts as asked once it is answered, and a skipped
  question is stored with value `None`. `done=True` ends the questions for the
  session (`TriageSession.done`). Free `text` can be added in any open turn.
- Sessions time out after `session_timeout_minutes` without a turn
  (`clock() - updated_at`): an open session becomes `expired` when it is next read.
- Errors: `SessionNotFound` (unknown id), `SessionClosed` (confirmed,
  cancelled or expired), `BadAnswer` (wrong question, value outside its
  answers, bad correction); the API maps them to 404, 409 and 422.

### Two new slots (`orbit/core/interfaces.py`; additive)

```python
@dataclass(frozen=True)
class TriageEvidence:
    findings: tuple[SymptomFinding, ...]
    answers: tuple[TriageAnswer, ...]
    asked: tuple[str, ...]            # question ids already asked (answered or skipped)
    preview: RiskAssessment | None    # assess(save=False) at the session's as_of
    anomalies: tuple[Anomaly, ...]

class SymptomExtractor(Protocol):     # slot "extractor"
    def extract(self, report: SymptomReport, ctx: AssessmentContext) -> list[SymptomFinding]: ...

class TriageReasoner(Protocol):       # slot "reasoner"
    def rank(self, evidence: TriageEvidence, ctx: AssessmentContext) -> list[PatternScore]: ...
    def next_question(self, evidence: TriageEvidence, ranking: Sequence[PatternScore],
                      ctx: AssessmentContext) -> TriageQuestion | None: ...
```

- Both are in `SLOTS`, so `python -m orbit modules` lists them and the
  registry accepts them. They are **not** in `ANALYTICS_SLOTS` in
  `orbit/core/config.py`: they are configured under `[triage]`, not
  `[modules.*]`, and `Pipeline.from_settings` keeps building only the five analytics slots.
- Slot modules follow rules 4 and 5: pure, and every option has a default.
  With no options a module uses a small built-in library (like
  `BUILT_IN_CARDS`), so the contract tests can build it. Reasoners expose
  `questions` (the bank) and `max_questions` attributes for the contract test.

**Contract tests (`tests/test_triage_contracts.py`)**, parametrized over `available(...)`:

| Slot | Must hold |
|---|---|
| extractor | builds with no options; in "Fever since yesterday, no sore throat" finds `symptom_fever_chills` not negated and `symptom_sore_throat` negated; empty text gives `[]`; deterministic; each evidence is a substring of the text, ignoring case |
| reasoner `rank` | all 8 patterns once each; probabilities sum to 1 ± 1e-6; sorted descending; deterministic; reasons are `Contributor`s; with a rash-or-tingling finding of severity 2, `vzv_like` ranks above `exertion` |
| reasoner `next_question` | never returns a question in `evidence.asked`; returns `None` once `max_questions` were asked; deterministic |

### Schema (`orbit/schema/triage.py`; exported from `orbit/schema/__init__.py`)

Same base as `labels.py` (`_Model`: frozen, unknown fields rejected;
`UtcDatetime`, `AstronautId`, `Slug`). `SCHEMA_VERSION` goes from 1.0.0 to
1.1.0; the store refuses only a major mismatch, so existing databases still open.

- `TriagePattern` (StrEnum): `vzv_like`, `hsv1_like`, `ebv_like`, `respiratory`,
  `exertion`, `sleep_loss`, `stress`, `other`.
- `TriageStatus` (StrEnum): `asking`, `ready`, `escalated` (open), `confirmed`,
  `cancelled`, `expired` (closed). `OPEN_STATUSES` lists the open ones.
- `SymptomReport`: `report_id` [uuid], `astronaut_id`, `reported_at`, `text`
  (1 to 1,000 characters), `channel` (`"text"` or `"voice"`, default text).
- `SymptomFinding`: `signal` (a symptom `SignalType`, or `None` for a
  complaint outside the 8 signals), `label`, `severity` (0–3 or `None`),
  `negated`, `confidence` (0–1), `evidence` (words from the text; empty for
  findings that came from an answer), `onset_hours`, `body_site`, `side`
  (`"left"`, `"right"`, `"both"`, `"one_side"` or `None`). A signal, if set,
  must be in category symptom.
- `TriageQuestion`: `question_id` (Slug), `text` (at most 120 characters),
  `answer_type` (`"yes_no"`, `"scale_0_3"`, `"choice"` or `"reading"`),
  `choices`, `signal` and/or `feature`, `likelihoods` (pattern → answer →
  probability), `red_flag_answers`, `category` (`SignalCategory`, for
  consent), `screening` (bool).
  - A **symptom question** has a `signal`, no `feature` and answer type
    `scale_0_3`: its answer is that symptom's severity. Its `choices` default
    to the signal's scale words from `get_spec` (none, mild, moderate, severe).
  - A **feature question** has a `feature` (`one_side`, `recent_exertion`,
    `short_sleep`, `high_stress`, `breathing_trouble` ...). If it also has a
    `signal`, it is asked only when that symptom was reported (for a
    screening question: the complaint that calls for it).
  - Answer keys for `likelihoods` and `red_flag_answers`: `"yes"`/`"no"`,
    `"0"`–`"3"`, or a choice. A pattern missing from `likelihoods` gets the
    uninformative 1 / (number of answers). `reading` answers carry no likelihoods.
  - `normalize(value)` turns an answer into its stored form (bool, 0–3,
    choice, number) and raises `ValueError` for anything else; it accepts
    `true`/`"yes"`, `2`/`"moderate"`, `"none"` and so on. `answer_key(value)`
    gives the likelihood key.
- `TriageAnswer`: `question_id`, `value` (bool, int, float, str, or `None`
  when skipped), `answered_at`.
- `PatternScore`: `pattern`, `label` (plain words, filled by the service from
  `cards/patterns.jsonl`), `probability` (0–1), `reasons` (at most 3
  `Contributor`s, each with `signal` or `event_id` set where one applies).
- `TriageResult`: `session_id`, `astronaut_id`, `as_of`, `status`, `findings`,
  `ranking` (probabilities sum to 1 ± 1e-6 when not empty), `next_question`,
  `red_flags` (rule ids), `procedures` (`ActionCard`s), `errors`,
  `model_version` (at most 64 characters, e.g. `lexicon-0.1+rules-0.1`).
- `TriageSession`: `session_id`, `astronaut_id`, `started_at`, `updated_at`,
  `as_of`, `reports`, `answers`, `result`, `status`, `confirmed_as_of`, and
  `done` (the astronaut said "that's all").

### Store (`orbit/core/store.py`, the M4 way)

Table `triage_sessions(id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL,
started_ts INTEGER NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL)` with an
index on `(astronaut_id, started_ts)`. Methods: `save_session(session)` (same
id replaces), `session(session_id) -> TriageSession | None`, and
`sessions(astronaut_id, *, start=None, end=None)` on `started_at`, newest
first. The table is in `counts()`. `CREATE TABLE IF NOT EXISTS`, so old
databases gain the table.

### Config (`[triage]` in `orbit.toml`; `orbit/core/config.py` does not change)

`load_settings` ignores unknown top-level sections. `orbit/triage/config.py`
(`load_triage_settings(settings) -> TriageSettings`) reads `[triage]` from
`Settings.config_path` and resolves `_path` keys relative to that file, like
`_resolve_paths`. Without a config file, or without `[triage]`, the built-in
starters and small built-in libraries are used. Unknown keys are a `ConfigError`.

```toml
[triage]                      # M15
session_timeout_minutes = 120
patterns_path = "cards/patterns.jsonl"
triage_cards_path = "cards/triage_cards.jsonl"
red_flags_path = "cards/red_flags.jsonl"

[triage.extractor]
use = "lexicon"
lexicon_path = "cards/symptom_lexicon.jsonl"

[triage.reasoner]
use = "rules"
questions_path = "cards/questions.jsonl"
max_questions = 5
stop_probability = 0.8
```

### Hand-written libraries (JSONL, checked on load, illustrative, never clinical)

- `cards/symptom_lexicon.jsonl`: phrases per symptom signal, severity words,
  negation cues, scope breakers, body sites, sides, and words for complaints
  outside the 8 signals. One record per line with a `kind`.
- `cards/questions.jsonl`: `TriageQuestion` records. File order is the
  rules reasoner's priority among bank questions.
- `cards/patterns.jsonl`: `pattern`, `label` in plain words (for example
  "Signs that fit shingles (VZV)"), and `card_ids`, which may name cards in
  `action_cards.jsonl` or `triage_cards.jsonl`. `vzv_like` lists
  `saliva-test` before `watch-patch`, so the worked example starts with the saliva test.
- `cards/triage_cards.jsonl`: pattern cards and red-flag cards as
  `ActionCard`s. Red-flag card ids start with `rf-`.
- `cards/red_flags.jsonl`: the rules (`rule_id`, `label`, `phrases`,
  `answers` (question id → red-flag answers), `card_id`).
- **Never add triage cards to `cards/action_cards.jsonl`.** The `protocol`
  engine would pick them on normal days, and `tests/test_actions.py` pins
  day 89's cards to exactly `["saliva-test", "rest-watch"]`. Nothing in the
  daily pipeline loads `triage_cards.jsonl`.
- Card check on load: unique ids (also against `pipeline.actions.cards`),
  orange and red cards set `escalate_to`, triggers within one signal
  category, steps under 200 characters, no digit followed by "mg", every
  pattern card id exists, every red-flag rule points to an `rf-` card, and
  every `red_flag_answers` entry in the question bank is covered by a rule.
- The built-in libraries (no paths) are self-contained: built-in patterns
  name only built-in triage cards.

### Patterns and their training labels

`vzv_like`, `hsv1_like` and `ebv_like` come from the simulator's
`viral_reactivation` (by virus); `respiratory` from `respiratory_infection`;
`exertion` from `eva_exertion`; `sleep_loss` from `sleep_shift`; `stress` from
`stress_load` (added in B24); `other` means no label, or a complaint outside
the 8 signals. Pattern labels on screen are plain words and never a diagnosis.

### Extractor `lexicon` (`orbit/modules/extractor.py`)

`@register("extractor", "lexicon")`, `LexiconExtractor(lexicon_path=None)`. It handles:
- phrases per signal ("tingly patch" → rash or tingling, "wiped out" →
  fatigue), longest phrase first, several mentions of one signal merged into one finding;
- severity words within 3 words before or after the phrase: "a bit" → 1,
  "pretty" or "quite" → 2, "really bad" or "severe" → 3;
- a negation window of 3 words before the phrase (no, not, without, never,
  don't ...), stopped by punctuation and scope breakers ("but", "and");
- durations, per sentence: "since last night" is about 12 h, "since this
  morning" 4 h, "since yesterday" 24 h, "for N days" N × 24 h;
- body sites and sides, given to the nearest finding in the same sentence;
- complaints outside the 8 signals (nausea, dizziness, blurry vision,
  congestion, back pain, cough, chest pain) as findings with signal `None`, never dropped.

Helpers for B24's text model: `tokenize(text)`, `is_negated(tokens, index)`
and `parse_duration(text) -> hours | None`.

### Reasoner `rules` (`orbit/modules/reasoner.py`)

`@register("reasoner", "rules")`,
`RulesReasoner(questions_path=None, max_questions=5, stop_probability=0.8)`.

- `rank`: hand-set likelihood ratios in the module, like `SYMPTOM_WEIGHTS` in `scorer.py`:
  - `vzv_like`: rash or tingling.
  - `hsv1_like`: mouth sores.
  - `ebv_like`: swollen glands and sore throat.
  - `respiratory`: fever or chills, sore throat, high CRP, a respiratory-rate anomaly.
  - `exertion`: muscle aches, fatigue, an EVA in the last 3 days.
  - `sleep_loss`: fatigue, headache, sleep anomalies.
  - `stress`: headache, high stress, low mood.
  - `other`: a complaint outside the 8 signals (and a higher prior, so it leads when nothing is known).
  Viral DNA above 100 copies/mL counts per virus, read from the preview's
  contributors (the scorer names it only above its detection limit). A
  stronger symptom weighs more; a denied symptom ("none") weighs against the
  patterns that expect it. Feature answers count through the bank's
  likelihoods. Probabilities are normalised, and the top 3 factors of each
  pattern are its reasons, as `Contributor`s (points = natural log of the factor).
- `next_question`:
  - Order: screening questions the complaint calls for, then a missing
    severity for a mentioned symptom, then the bank's next question (file
    order) that concerns the top 3 patterns.
  - Never ask the same question twice. Skip what ORBIT knows: no spacewalk
    question when `ctx.events` has an EVA in the last 3 days, no question
    about a symptom the text already rated, no one-side question when the
    side is known, no eye screening when the body site is known and not on
    the face, no short-sleep question with a sleep anomaly, no stress
    question when the check-in already shows high stress.
  - Return `None` when the top probability reaches `stop_probability`,
    after `max_questions`, or when no question is left. After
    `answer(..., done=True)` the service does not ask.
- The bank holds:
  - a symptom question per symptom signal, with scale words from `get_spec`;
  - "Is it on one side of your body only?";
  - fever or chills, recent hard work or a spacewalk (feature
    `recent_exertion`), short sleep and high stress questions;
  - screening questions with red-flag answers ("Any trouble breathing?").
  Each question carries illustrative per-pattern answer likelihoods.
- New cards in `cards/triage_cards.jsonl`: `watch-patch` (yellow, `vzv_like`),
  `mouth-care-early` (`hsv1_like`), `rest-fluids` (`ebv_like`),
  `keep-distance` (`respiratory`), `recover-after-work` (`exertion`),
  `describe-to-cmo` (`other`; escalates to the crew medical officer).
  `sleep_loss` and `stress` reuse `recover-sleep` and `ease-stress`.

### Red flags (`orbit/triage/red_flags.py`, not a slot)

Fixed rules, checked on the raw text and on every answer before any model
runs. Example phrases: "can't breathe", "chest pain", "fainted", "confused",
"a rash near my eye". A negation cue (no, not, never, without, don't ...)
denies a phrase only when it comes directly before it, in the same clause:
"no chest pain", "without chest pain", "not short of breath", "I have no chest
pain" (at most two filler words may sit between: "I don't have any trouble
breathing"). Punctuation and dashes (— – - , ; . : ! ?) end a clause and stay
boundaries when tokenising. A phrase that is itself negative ("can't
breathe", "cannot breathe") is never denied by a cue before it, so "No, I
can't breathe" and "No—I can't breathe" fire. Uncertainty is not denial:
"not sure but chest pain", "not only chest pain" and "I don't think it's
serious but I can't breathe" fire. When in doubt, fire.

**The red-flag gate runs on every triage request before any validation; no
error can drop a detected flag.** `screen_payload(raw, rules, questions)` in
`orbit/triage/red_flags.py` collects every string in a request body (every
key, every value, nested lists and objects, or the text of a body that is not
JSON) and scans all of it; a structured answer to a bank question
(`screen-breathing = yes`) counts too. The `/triage` POST endpoints read the
raw body and hand it to the service (`start_raw`, `answer_raw`, `confirm_raw`,
`cancel_raw`), which runs the gate first, then looks up the session, then
validates; FastAPI does no body validation there. With a flag, the escalated
session is saved first and every validation problem goes to `errors`
(200 with the escalated `TriageResult`); `red_flag_at` is set either way:
- a start always creates an escalated session; text over 1,000 characters is
  cut to its first 1,000 with an error saying so;
- an answer, confirm or cancel to an unknown, closed or other astronaut's
  session starts a new escalated session instead of a 404 or 409;
- an invalid confirm escalates instead of confirming (`day` is null); a valid
  one records the flag, then confirms;
- a cancel whose body carries a flag escalates instead of cancelling;
- the flagged words are kept as reports in the session;
- a `view` parameter on a flagged POST is not refused.
Without a flag, the same problems give 422 (404, 409) as before. Every read-modify-write of a
session holds one lock per session id, and saving merges red flags and
reports with what is stored, so parallel requests cannot drop a red flag.
Failing triage steps log only the step, the exception type and the session
id, never the astronaut's words.

A match sets the status to `escalated`, stops the questions and puts the
rule's red-flag card first, whatever the score. A model may add a red flag
(an answer in a question's `red_flag_answers`) but never remove one: red flags
of a session only grow, and they stay after confirm or cancel. Recall on the
hand-written test set `tests/fixtures/triage/red_flag_sentences.jsonl` must be
100 %. That file is a first draft for a person to review.

Red-flag cards have no triggers and say what to do now without naming the
symptom, so the crew's shared view shows them in full.

### Library and procedures (`orbit/triage/library.py`, not a slot)

It loads and checks `patterns.jsonl` and `triage_cards.jsonl`, and provides
`merge_procedures(red_flag_cards, pattern_cards, day_cards, level, max_cards=4)`:
red-flag cards first, then the top pattern's cards, then the `protocol`
engine's cards from the (re-)assessment. Drop duplicate card ids and keep at
most 4. Never add a card above `level`, except red-flag cards. People write
card text; models choose cards, never words. Before confirm, `level` and the
day cards come from the preview.

### Confirm

1. Corrections (`{signal: severity}`, symptom signals only, 0–3) replace or
   add findings. Each confirmed finding with a signal becomes
   `Observation(signal, value=severity, source="checkin",
   observation_id=f"{astronaut_id}-{signal.value}-{as_of:%Y%m%dT%H%M%S}",
   note=f"triage {session_id}")`, the check-in's ID scheme. A negated symptom
   is stored as 0; a symptom mentioned without a severity is stored as 1
   (mild). Complaints outside the 8 signals write nothing and stay in the
   session. Never copy the raw text into a note: notes travel with shared symptoms.
2. Call `pipeline.assess(astronaut_id, as_of)` with `save=True`, so hooks and
   auto-send run as today.
3. Rank again with the re-assessment as the preview, merge the procedures and
   re-save the same run:
   `store.save_day(result.model_copy(update={"actions": tuple(merged)}))`. The
   dashboard and crew view then show the chat's cards, and private ones are
   hidden in the shared view as today.

### API (`orbit/api/app.py` stays thin)

| Method | Path | Body → returns |
| --- | --- | --- |
| POST | /api/crew/{id}/triage | {text, timestamp?} → TriageResult |
| POST | /api/crew/{id}/triage/{session_id}/answer | {question_id, value}, {text} or {done: true} → TriageResult |
| POST | /api/crew/{id}/triage/{session_id}/confirm | {corrections?: {signal: severity}} → {result, day} |
| POST | /api/crew/{id}/triage/{session_id}/cancel | → TriageSession |
| GET | /api/crew/{id}/triage/{session_id} | → TriageSession |
| GET | /api/crew/{id}/triage?start=&end= | → TriageSession[], own view only |

- `create_app(..., triage=None)` builds a service with the built-in starters
  (and the app's `clock`) when none is given; `cmd_serve` and
  `create_app_from_settings` pass one built from `[triage]`.
- Errors: 404 for an unknown astronaut or session (also a session of another
  astronaut), 409 for a closed session, 422 with the reason for a bad answer
  (unless the request carries a red flag, see Red flags). Corrections take
  only whole numbers 0–3: `true`, `"2"` and `2.0` get 422. Every `/triage`
  endpoint answers a `view` query parameter with 400 "Triage sessions have
  no shared view", except a POST whose body carries a red flag. The confirm
  response's `day` is null when a flagged, invalid confirm escalated instead.
- `OverviewRow` gains `red_flag_at`: the mission time (`as_of`) of the latest
  session with a red flag started in the last 24 h of wall-clock time, with no
  details. Sessions have no shared view.

### CLI (`orbit/__main__.py`)

- `python -m orbit triage AST-01 "<text>" --as-of 2027-04-02T10:30:00Z [--answer moderate --answer yes --answer none]`
  runs a session in memory on the example data, like `demo`. It prints the
  findings, each question with its answer, the patterns, the new level and
  score, and the cards. It confirms at the end; questions left when the
  answers run out end the session as "that's all".
- `python -m orbit modules` also shows the active `[triage]` modules, with a
  column wide enough for "extractor" and "reasoner".

### Privacy and consent

Raw text lives only in `triage_sessions`, never in an `EarthPacket` or a
note. Pattern reasons are `Contributor`s with `signal` set, so the consent
gate redacts them. Score, level and `red_flag_at` always reach the crew.
Confirmed symptoms are in category symptom, so they are private by default.

### Numbers measured on the code before B23 (test expectations)

- 270 tests pass. AST-01 is yellow 27.7 at day 89 10:00 and orange 70.2 at day 90 10:00.
- A confirmed chat at 2027-04-02T10:30:00Z (day 89) with rash or tingling 2,
  fatigue 2 and fever or chills 0 re-scores AST-01 to yellow 44.7. The
  `protocol` cards are `saliva-test`, then `rest-watch`. The 10:00 runs do not change.
- The same chat at 2027-04-03T10:30:00Z (day 90) gives red 77.2.
- The day-88 spacewalk (EVA event for AST-01, 2027-04-01) is in `ctx.events` on day 89.

### Worked example (AST-01, day 89, 10:30)

- Text: "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."
- Findings: rash or tingling (no severity, body site ribs, onset about 12 h)
  and fatigue 2. No red flag.
- Questions, in order: how strong the burning or tingling is ("Moderate" →
  2); "Is it on one side of your body only?" ("Yes"); "Any fever or chills?"
  ("None" → 0). The spacewalk question is skipped (the EVA is known).
  `vzv_like` leads after the one-side answer and passes 0.8 after the third
  question, so the session is ready.
- Confirm gives yellow 44.7. The procedures start with `saliva-test` and
  include `watch-patch` and `rest-watch`.

### Version 2 (B24): the models

B24 adds learned modules beside the starters; `orbit.toml` switches only if
the switch rules below pass and the team agrees.

- **Simulator look-alikes** (`symptom_lookalikes`, `mild_illness_rate`, off
  by default and drawing no random numbers when off): muscle aches and
  fatigue after an EVA, fatigue and headache during a sleep shift, and a new
  `stress_load` look-alike (stress, mood and headache, no vital change).
- **Extractor `text_linear`** (`orbit/modules/extractor_learned.py`): logistic
  regression per symptom on word and character n-grams plus a severity head,
  trained on seeded templates and hand-written paraphrases; negation and
  durations reuse the lexicon helpers.
- **Reasoner `bayes`** (`orbit/modules/reasoner_bayes.py`): naive Bayes
  trained on simulated episodes; next question by expected information gain
  in bits (`min_gain_bits = 0.05`), keeping the screening-first,
  severity-first and stop rules.
- **Evaluation** (`orbit/evaluation/triage.py`): extractor F1, negation and
  severity on human sentences; reasoner top-1, top-3, Brier score and
  questions per session; red-flag recall; M9 numbers with chats.
- **Switch rules:** `text_linear` beats `lexicon` on F1 and negation and
  misses no red-flag phrase; `bayes` beats `rules` on top-1, top-3 and Brier
  on seeds 101–105 with no more questions; M9 numbers no worse and the demo
  story holds. The answer likelihoods are hand-set, so the evaluation
  measures consistency, not medical truth.

**Done when (B23):** every checkpoint in `tasks/B23-triage-v1.md` passes,
the contracts pass for both slots, and `python -m orbit triage AST-01 ...` prints
the worked example (yellow 44.7).

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
| M15 symptom triage | after M10 (B19) | M8, M10, M13/M14 shared view (B15), auto-send (B18) | the chat check-in screen |

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
