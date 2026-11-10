# ORBIT architecture

How the modules fit together, and why it is built this way.

## The big picture

```
  DATA SOURCES                 BACKBONE                         ANALYTICS SLOTS
  ────────────                 ────────                         ───────────────
  files (M3)      ─┐
  simulator (M2)  ─┼─ ingest ─▶ Store (SQLite) ──context──▶ baseline  (M6)
  space wx (M5)   ─┘              ▲                            │
                                  │                            ▼
  check-in (M11) ── API ──────────┤                         detector  (M7)
                                  │                            │
                                  │                            ▼
                                  │                         scorer    (M8)
                                  │                            │
                                  │                            ▼
                                  └──────── save_day ◀───── actions   (M10)

  Store ──▶ API ──▶ dashboard (M12), crew view (M14)
  Store ──▶ sync slot (M13, consent filter) ──▶ Earth
```

Everything meets in two places: the **pipeline** (`orbit/core/pipeline.py`),
which runs the modules in order, and the **store** (`orbit/core/store.py`),
where every result is saved. Modules never call each other.

## Design decisions

### 1. A walking skeleton: every slot works from day one

Each module slot has a simple starter implementation in `orbit/modules/`.
They are basic but real, so `python -m orbit demo` runs the whole mission
scenario end to end today.

Why: in a hackathon, integration is what usually fails, at hour 40, when
five separately built pieces meet for the first time. Here integration is done
first. Each teammate replaces one working part with a better one, and the
system works after every change. The frontend can be built against real API
responses immediately.

### 2. Slots, a registry and a config file

Each slot is defined by one small interface in `orbit/core/interfaces.py`
(for example a scorer needs one method: `score(ctx, anomalies)`). A module
joins a slot with a decorator, and `orbit.toml` chooses which one runs:

```python
@register("detector", "cusum")
class CusumDetector:
    def detect(self, ctx, baselines): ...
```

```toml
[modules.detector]
use = "cusum"
```

Why: five people can work in parallel without editing the same files.
Switching implementations is a one-line config change, so the team can
compare the starter detector with the new one on the same data, which is
exactly what the evaluation module (M9) needs.

### 3. Modules are pure functions of a context

The pipeline gives each analytics module an `AssessmentContext`: a read-only
snapshot of one astronaut at one moment (their readings, events, profile).
Modules do not touch the database.

The context splits time into two windows that never overlap:

```
|──── history: 14 days that define "your normal" ────|── recent: 3 days ──| now
```

Why: pure modules are easy to write and to test (no database setup), and
they cannot accidentally read the future. The split windows stop an illness
from becoming part of the astronaut's "normal": if the last three days were
included in the baseline, a slow fever would raise the baseline along with it
and hide itself.

### 4. One shared store, SQLite, idempotent writes

All data and all results live in one SQLite file. Each row holds the full
record as validated JSON plus a few indexed columns for filtering.

Why SQLite: no server, a single file, works offline, ships with Python. That
matches a spacecraft, where there is no cloud.
Why JSON plus index columns: adding a field to a model needs no database
migration, and everything read back is re-validated against the M1 schema.
Why idempotent: saving the same reading twice or re-running a day replaces the
old rows. The team can fix a module and re-run without cleaning up.

### 5. A failing module does not stop the system

Each stage runs in its own error boundary. If the detector crashes, the day is
still scored from symptoms, lab results and events, and the error is recorded
in `DayResult.errors` (shown by the CLI and the API).

Why: health monitoring should degrade, not die. It also keeps the demo safe
when someone pushes a half-finished module an hour before judging.

### 6. The API holds no health logic

`orbit/api/app.py` only reads from the store and calls the pipeline. The
dashboard, the CLI and the tests therefore always agree.

A check-in through the API saves the answers and re-assesses immediately, so
the astronaut sees the effect of what they reported.

### 7. Consent before anything leaves the spacecraft

The `sync` slot builds the packet for Earth. The starter sends only the
categories the astronaut shares (symptoms and mood stay onboard by default)
and replaces reasons based on private data with a neutral label, while still
sending the overall score.

Why: the challenge puts astronauts in charge of their own health. They report
more honestly when they control who sees what.

## One daily assessment, step by step

For each astronaut, once a day at 10:00 UTC (after the night's wearable data
and the morning check-in; set in `orbit.toml`):

1. **Context.** The pipeline loads 17 days of usable readings and the last
   7 days of events, and splits them into history and recent.
2. **Baseline (M6).** From history: median and spread per signal.
3. **Detector (M7).** Each recent reading against the baseline, in the
   worrying direction only. Spike = latest reading far off; drift = several
   days in a row moderately off.
4. **Scorer (M8).** Points for anomalies, symptoms, lab results and stress
   events, each with a plain-language reason. Total → green/yellow/orange/red.
5. **Actions (M10).** Cards matching the level and the reasons.
6. **Save.** Everything goes to the store; the `assessed` hook fires.

## Plugging in your module

1. Read your slot's interface in `orbit/core/interfaces.py`.
2. Create `orbit/modules/<your_module>.py`, add `@register("<slot>", "<name>")`,
   and import it in `orbit/modules/__init__.py`.
3. Run `python -m pytest tests/test_contracts.py`. Your module is tested
   automatically against the slot's contract.
4. Set `use = "<name>"` in `orbit.toml` and run `python -m orbit demo`.

Keep the starter registered: it is the fallback and the comparison point.

## Who owns what

| Slot / part | File | Team module |
|---|---|---|
| schema | `orbit/schema/` | M1 (done) |
| source | `orbit/modules/sources.py` | M3 ingestion; M2 simulator and M5 space weather add new sources |
| store | `orbit/core/store.py` | M4 (done) |
| baseline | `orbit/modules/baseline.py` | M6 |
| detector | `orbit/modules/detector.py` | M7 |
| scorer | `orbit/modules/scorer.py` | M8 |
| evaluation | uses `Pipeline.run()` on simulator data | M9 |
| actions | `orbit/modules/actions.py` + `examples/action_cards.jsonl` | M10 |
| check-in, dashboard, crew view | frontend, via `orbit/api/app.py` | M11, M12, M14 |
| sync | `orbit/modules/consent.py` | M13 |

## Known limits of the starter modules

* The baseline needs at least 5 readings per signal, so the first days of a
  mission have no anomaly detection (symptoms and lab results still count).
* The scorer's weights are hand-set for the demo, not clinically validated.
* The example data covers three weeks; the M2 simulator should produce a
  full mission with labelled scenarios for M9 to measure detection lead time.
