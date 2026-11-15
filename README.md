# ORBIT: Onboard Readiness & Body Insight Tracker

**An immune early-warning system for astronauts on long missions.** ORBIT
watches each astronaut's body against their *own* normal, notices when their
immune system starts to struggle, and tells the crew what to do: onboard,
without waiting for Earth.

Built for the NASA Space Apps Challenge. Python, FastAPI and SQLite in the
backend; React and TypeScript in the frontend. It uses **real NASA
space-weather data** from NASA DONKI.

**Live demo: [rdenis03.github.io/spacemontoringsoftware](https://rdenis03.github.io/spacemontoringsoftware/)**
· Code: [github.com/rdenis03/spacemontoringsoftware](https://github.com/rdenis03/spacemontoringsoftware)

> The demo's backend runs on a free server that sleeps when nobody uses it. If
> the site says it can't reach the API, open
> [the backend's health page](https://orbit-ubgu.onrender.com/api/health), wait
> about a minute until it answers, then press **Try again**.

> **Not medical advice.** All health data is simulated, and the scoring
> weights, red flags and procedures are illustrative. Alongside the simulated
> example events, the demo has two additional real NASA DONKI events, replayed
> onto mission days 72 and 76.

**Jump to:** [Live demo](https://rdenis03.github.io/spacemontoringsoftware/) ·
[Quick guide](QUICK_GUIDE.md) · [How it works](#how-it-works) ·
[NASA data](#nasa-data-and-resources) · [Machine learning](#machine-learning) ·
[Quick start](#quick-start) · [For developers](#for-developers)

---

## The problem

On long missions, stress, radiation, broken sleep and hard physical work weaken
the immune system. Viruses that most people carry silently (the ones behind
shingles, cold sores and glandular fever) can wake up. Near Mars, a message to
Earth takes up to 22 minutes each way, so the crew has to notice early and act
on their own.

## What ORBIT does

1. **Learns each astronaut's normal**: skin temperature, heart rate and its
   variability, breathing rate, sleep, and more.
2. **Spots changes early**, from wearables, the daily check-in and onboard lab
   tests, before the astronaut feels really ill.
3. **Turns them into one clear status** with the reasons behind it:

   | Level | Score | Meaning |
   |---|---|---|
   | 🟢 Green | 0–24 | Within your normal |
   | 🟡 Yellow | 25–49 | Keep an eye on it |
   | 🟠 Orange | 50–74 | Act on it today |
   | 🔴 Red | 75–100 | Get help now |

4. **Says what to do and who to tell**: short procedure cards, such as "Take a
   saliva sample" or "Reduce workload, tell the crew medical officer".
5. **Lets the astronaut just say how they feel.** A chat understands plain
   words, asks a few follow-up questions, shows a report the astronaut can
   correct, and saves it as their check-in.
6. **Keeps private data private.** Symptoms and mood stay onboard unless the
   astronaut chooses to share them with Earth.
7. **Counts real space weather as a stressor.** Solar particle events and
   geomagnetic storms from NASA's DONKI database become events in the mission,
   and they add to the score while they matter.

---

## How it works

### The daily assessment

```mermaid
flowchart LR
  W["Wearables: temperature, heart, sleep"] --> S["Shared store"]
  C["Check-in or chat: symptoms, mood, stress"] --> S
  L["Onboard labs: saliva virus DNA, CRP"] --> S
  E["Events: spacewalks, NASA DONKI space weather"] --> S
  S --> B["Baseline: your normal"]
  B --> D["Detector: spikes and drifts"]
  D --> R["Scorer: 0 to 100 and a level"]
  R --> A["Action cards: what to do"]
  R --> G["Consent gate: what Earth may see"]
```

Every reading goes into one shared store. Each day ORBIT compares the newest
readings with the astronaut's personal baseline, flags what is unusual, scores
it from 0 to 100 with the reasons ("Skin temperature 0.45 °C above your normal
for 2 days, +9 points"), and picks the procedure cards that fit.

### The symptom chat

```mermaid
flowchart LR
  M["Your message"] --> F{"Red-flag check"}
  F -- urgent --> X["Get medical help now"]
  F -- ok --> E["Extractor: symptoms, strength, what is denied"]
  E --> R["Reasoner: possible patterns"]
  R -- unsure --> Q["One follow-up question"]
  Q --> F
  R -- sure enough --> P["Report you can correct"]
  P -- save --> S["Saved as the check-in: score updated, procedures"]
```

- **Safety first.** Every message, answer and correction passes a red-flag
  check *before* any model sees it. Trouble breathing, chest pain, fainting,
  confusion, a rash near the eye, a sudden very bad headache, trouble
  swallowing or bleeding go straight to "Get medical help now".
- **Extractor:** finds the symptoms in plain words, how strong they are, and
  what the astronaut says they *don't* have ("No rash, but a burning patch").
- **Reasoner:** ranks 8 possible patterns (shingles, cold sores, glandular
  fever, chest or throat infection, hard physical work, short sleep, stress,
  something else) using the symptoms, today's sensors, lab results and recent
  events. It asks the question that would help most, and shows patterns only
  as "likely" or "possible", never as a diagnosis.
- **Report:** the astronaut checks what ORBIT understood, fixes anything
  wrong, and saves. The score is then re-assessed right away.

### Built from swappable parts

Each step is a module in a named slot, and `orbit.toml` chooses which one runs.
Every slot has a simple, explainable starter, and some have other options,
including trained models to compare against.

| Slot | What it does | Default (`orbit.toml`) | Other options |
|---|---|---|---|
| `source` | loads data | `files` (example data) + `donki` (real NASA space weather, from a local cache) | `wearable_csv` (device exports), `simulator` (whole missions) |
| `baseline` | your normal per signal | `rolling_median` | |
| `detector` | spikes and drifts | `robust_z` | |
| `scorer` | 0–100 score and reasons | `rule_based` | `learned` (trained) |
| `actions` | procedure cards | `protocol` | |
| `sync` | what may leave the spacecraft | `consent_gate` | |
| `extractor` | symptoms from text | `lexicon` | `text_linear` (trained) |
| `reasoner` | patterns and questions | `rules` | `bayes` (trained) |

Design details and the reasons behind them: **[ARCHITECTURE.md](ARCHITECTURE.md)**.
Full module specs: **[SPEC.md](SPEC.md)**.

---

## Quick start

You need **Python 3.11+** and **Node.js 20.19+ or 22.12+**.

```bash
git clone https://github.com/rdenis03/spacemontoringsoftware.git
cd spacemontoringsoftware

python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

python -m orbit demo              # the whole story in the terminal, in memory
```

Then run the app in **two terminals**:

```bash
# terminal 1: backend, http://localhost:8000 (API docs at /docs)
python -m orbit serve

# terminal 2: frontend, http://localhost:5173
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

To put the demo data back after trying things: stop `serve`, run
`python -m orbit reset`, then start `serve` again.

### Live deployment

- **Website:** [rdenis03.github.io/spacemontoringsoftware](https://rdenis03.github.io/spacemontoringsoftware/)
  on GitHub Pages. Every push to `main` runs `.github/workflows/pages.yml`,
  which builds `frontend/` with the repository variable `VITE_API_URL` (the
  backend address) and publishes it.
- **Backend:** [orbit-ubgu.onrender.com](https://orbit-ubgu.onrender.com/api/health)
  on Render's free tier, set up from `render.yaml` (Render → New → Blueprint →
  this repository). It redeploys from `main`. Its disk is not persistent, so
  every restart reloads the example data, including the NASA DONKI events.
  After about 15 idle minutes it sleeps, and the next request takes about a
  minute.

---

## Quick guide

**[QUICK_GUIDE.md](QUICK_GUIDE.md)** walks through the app step by step: telling
ORBIT how you feel, answering its questions, checking and saving the report, and
what Today, Crew and Earth show. It also has the demo story and messages to try.

---

## Machine learning

ORBIT trains its models on **simulated data**: 20 missions of 180 days with 4
crew, including illnesses, look-alikes such as hard work or short sleep, and
sensor faults (plus generated sentences for the text model). It then tests
them on 5 missions the training never saw.

| Model | What it learns | Result on unseen missions |
|---|---|---|
| Learned scorer | weights for the 0–100 score | warns earlier (24 of 45 illnesses before symptom day, vs 16) with no extra false alarms |
| Text model (`text_linear`) | symptoms, severity and "no" in plain words | understands everyday wording the word list misses ("my throat kinda hurts") |
| Bayes reasoner (`bayes`) | how likely each pattern is from symptoms, sensors, labs and events | much better calibrated (Brier score 0.04 vs 0.19), and asks 1.5 questions instead of 3.6 |

**The starters stay switched on.** A trained model replaces a starter only if
it is at least as good on every agreed measure. For the scorer and the
reasoner, that rule did not pass, and the text model still needs about 200 test
sentences from people who never saw the code. The trained models are one
config away:

```bash
python -m orbit --config experiments/learned.toml serve          # learned scorer
python -m orbit --config experiments/triage_learned.toml serve   # learned chat models
```

Full numbers, how to read them, and how to reproduce them: **[docs/RESULTS.md](docs/RESULTS.md)**.

---

## Privacy and safety

- **Consent first.** Each astronaut chooses which kinds of data may leave the
  spacecraft. Score and level are always shared; symptoms, mood and stress
  stay onboard unless shared. The Earth screen shows exactly what would be sent.
- **The crew view shows only what is shared.** Private reasons appear as
  "Private reason".
- **Red flags beat models.** The urgent-symptom check is not a swappable
  module: it runs before any model, on every message, answer and correction.
- **No hidden health logic.** The scorer explains every point, and the chat
  shows its reasons for every pattern.

---

## For developers

### Commands

```bash
python -m orbit demo                 # full scenario in memory, safe to repeat
python -m orbit serve [--port 8000]  # API; loads the example data if the database is empty
python -m orbit status AST-01        # latest status in the terminal
python -m orbit triage AST-01 "..." --as-of <time> [--answer ...]   # a chat in the terminal
python -m orbit run                  # re-run daily assessments
python -m orbit ingest               # load the sources in orbit.toml
python -m orbit modules              # which modules exist and which are active
python -m orbit reset                # delete the database
python -m pytest                     # 607 tests
```

Every command accepts `--config path/to/orbit.toml` and `--database path` (or `":memory:"`).

### API

Interactive docs with examples: **http://localhost:8000/docs**. The main routes:

| Route | For |
|---|---|
| `GET /api/signals` | labels, units, scales and level thresholds (the frontend never hard-codes these) |
| `GET /api/crew/{id}/status` | today's level, reasons, anomalies and procedures (`?view=shared` for the crew view) |
| `GET /api/crew/{id}/day?as_of=` | the same for a past day (replay) |
| `POST /api/crew/{id}/checkin` | save the quick check-in and re-assess |
| `POST /api/crew/{id}/triage` | start a chat, then `…/{session}/answer`, `…/confirm` and `…/cancel` |
| `GET /api/overview` | the crew view |
| `PUT /api/crew/{id}/consent`, `GET …/earth-packet`, `POST …/earth-packet/send`, `GET /api/outbox` | sharing with Earth |
| `GET /api/crew/{id}/observations`, `…/baselines`, `…/assessments` | charts |

### Project layout

```
orbit/
  schema/      the data contract: 25 signals, models and validation rules
  core/        slots, registry, config, SQLite store, pipeline
  modules/     the modules for every slot (starters and trained ones)
  triage/      the chat service, red flags and procedure library
  learning/    trainers and the trained weights (readable JSON)
  evaluation/  metrics and the comparison runner
  api/         FastAPI app
frontend/      React + TypeScript app (see frontend/README.md and DESIGN.md)
cards/         procedure cards, questions, red flags, symptom words (hand-written, checked on load)
examples/      the demo data: mission days 70–90 for two astronauts
experiments/   configs that switch on the trained models
reports/       committed evaluation results
tests/         607 tests: schema, store, pipeline, contracts, API, models and chat
```

### Adding a module

1. Read the slot's interface in `orbit/core/interfaces.py`.
2. Create `orbit/modules/<name>.py` with `@register("<slot>", "<name>")` and
   import it in `orbit/modules/__init__.py`.
3. Run `python -m pytest tests/test_contracts.py` to check it fits the slot.
4. Set `use = "<name>"` in `orbit.toml`.

Modules are pure: no database, network or clock inside them. Everything they
need arrives in one context object, which keeps them easy to test and replay.

---

## NASA data and resources

### Real space weather from NASA DONKI

Solar storms and radiation are part of the stress that weakens astronauts'
immune systems, so ORBIT counts them as events, like a spacewalk or a night of
broken sleep. Instead of only simulating them, ORBIT reads **real space-weather
events from NASA's DONKI database** (Space Weather Database Of Notifications,
Knowledge, Information) through the [NASA Open APIs](https://api.nasa.gov/).

**How it works**, modelled on a real mission:

1. **On the ground,** the `donki` source (`orbit/modules/space_weather.py`) in
   `fetch` mode downloads solar particle events (SEP) and geomagnetic storms
   (GST) for a date range and saves the raw NASA responses to a cache file.
   The API key comes from the `NASA_API_KEY` environment variable and is never
   saved.
2. **Onboard,** the same source in `cache` mode reads only that file, with no
   network, as a spacecraft would after an uplink.
3. Each NASA record becomes a crew-wide event with a severity (for example a
   storm's maximum Kp index), its real NASA ID and date in the description,
   and the scorer adds 1 to 10 points while it is recent.
4. The example mission is set in 2027, so ORBIT **replays** a real window onto
   it: `examples/donki_cache.json` holds NASA's real records for
   2025-10-16 to 2025-10-26, shifted so that 2025-10-16 becomes mission day 70.

**What you see in the demo:** open **Today → History** and replay to

- **day 73:** "Geomagnetic storm today", from the real storm of 18 October 2025
  (max Kp 6, low severity, +1 point);
- **day 76:** "Solar particle event today", from the real event of
  22 October 2025 (moderate, +3 points), plus the storm 3 days earlier.

"Show details" names the source: *NASA DONKI GST 2025-10-18T18:00Z, max Kp 6
(real event, replayed)*. The demo story itself (yellow on day 89, orange on
day 90) is unchanged.

**What we learned about the API:** one request covers at most 60 days (the
source splits longer ranges); one solar particle event is listed once per
instrument (the source merges records within 6 hours); and the flare endpoint
answered 404 during development, so flares and CMEs are off by default.

**To replay a different real window:** in a copy of `orbit.toml`, set the
`donki` source to `mode = "fetch"` with a new `real_start` and `real_end`
(60 days or less per request is handled for you), set `NASA_API_KEY`, and run
`python -m orbit --config <your copy> --database ":memory:" ingest`. That
writes the cache; switch back to `mode = "cache"` for normal use, and check the
day-by-day scores, since stronger events add more points.

### All NASA sources ORBIT uses

ORBIT uses real NASA data and builds on NASA research:

- **[NASA DONKI](https://ccmc.gsfc.nasa.gov/tools/DONKI/)** (API via
  [api.nasa.gov](https://api.nasa.gov/)): the `donki` source turns real solar
  particle events and geomagnetic storms into stress events. The demo replays
  a real storm (2025-10-18) and solar particle event (2025-10-22) onto mission
  days 72 and 76, read from a local cache so nothing touches the network onboard.
- **NASA Human Research Program**, ["Risk of Adverse Health Event Due to Altered
  Immune Response"](https://www.nasa.gov/directorates/esdmd/hhp/risk-of-adverse-health-event-due-to-altered-immune-response/): the problem ORBIT addresses.
- **NASA Evidence Report** (Crucian and Sams, NTRS 20140002769): immune changes
  in flight and the stressors ORBIT records.
- **Rooney et al. 2019** (NASA Johnson Space Center, *Frontiers in
  Microbiology*): why ORBIT watches VZV, HSV-1 and EBV, and why its first
  procedure is a saliva viral-DNA test.

Where each one is used, and what we learned about the DONKI API:
**[docs/NASA_RESOURCES.md](docs/NASA_RESOURCES.md)**.

---

## Use of AI tools

As the NASA Space Apps rules ask, we state where AI was used. The team
designed ORBIT and directed the work; large-language-model coding assistants
helped write and review code, tests and documentation, and every change was
reviewed and tested by the team (607 automated tests). The 20 provisional test
sentences in `tests/fixtures/triage/human_sentences.jsonl` were AI-written and
are labelled `"stub"`; they are to be replaced by sentences written by people.
No AI-generated images, video or audio are used, and no NASA logos or branding.

---

## Limits

- **Simulated health data only.** The simulator makes the problem cleaner than real
  bodies are, so real-world performance is unknown.
- **Illustrative medicine.** Thresholds, red flags and procedure cards were
  written for the demo, not by flight surgeons.
- **English only** for the chat, and its text model still needs real test
  sentences before it can be trusted.
