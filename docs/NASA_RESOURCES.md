# NASA data and resources used by ORBIT

ORBIT uses one NASA data source and three NASA research resources. This page
lists each one and exactly where ORBIT uses it.

| Resource | Kind | Used for |
|---|---|---|
| [NASA DONKI](#nasa-donki-space-weather-data) | live data (API) | the space-weather source and the real events in the demo |
| [HRP immune risk](#nasa-human-research-program-immune-risk) | research programme | the problem ORBIT addresses |
| [Evidence Report (Crucian and Sams)](#nasa-evidence-report-crucian-and-sams) | research report | immune changes in flight; the stressors used as context events |
| [Rooney et al. 2019](#herpes-virus-reactivation-in-astronauts-rooney-et-al-2019) | research paper | why ORBIT watches VZV, HSV-1 and EBV; why its first procedure is a saliva viral-DNA test |

---

## NASA DONKI (space-weather data)

**What:** DONKI (Space Weather Database Of Notifications, Knowledge,
Information), run by NASA's Community Coordinated Modeling Center.
Website: <https://ccmc.gsfc.nasa.gov/tools/DONKI/>. API through
<https://api.nasa.gov/> (`https://api.nasa.gov/DONKI/{SEP|GST|CME|FLR}?startDate=…&endDate=…&api_key=…`).

**Where ORBIT uses it:**

- `orbit/modules/space_weather.py`: the `donki` source (SPEC M5). It turns
  solar particle events (SEP), geomagnetic storms (GST) and, if switched on,
  CMEs and flares into crew-wide context events.
- `orbit.toml`: the `donki` source in `cache` mode, so the demo replays real
  events without touching the network.
- `examples/donki_cache.json`: the real DONKI responses for 2025-10-16 to
  2025-10-26, fetched once on 2026-11-15. With `mission_start = "2027-03-14"`
  they replay into the example mission:

  | Real event (DONKI ID) | Mission day | Severity | Score points |
  |---|---|---|---|
  | Geomagnetic storm, max Kp 6.0 (`2025-10-18T18:00:00-GST-001`) | 72 (counted from day 73, since it starts after the 10:00 assessment) | low | +1 on days 73–79 |
  | Solar particle event (`2025-10-22T00:09:00-SEP-001`) | 76 | moderate | +3 on days 76–83 |

- `tests/fixtures/donki/*.json`: the raw SEP, GST and CME responses for the
  same window, used by `tests/test_space_weather.py`.
- The dashboard (Today "Why" details and History) shows each event's
  description from the API, for example
  "NASA DONKI GST 2025-10-18T18:00Z, max Kp 6 (real event, replayed)".

**Facts found on live responses (2026-11-15):**

- **60 days per request at most.** A longer range answers HTTP 400 ("Date
  range cannot exceed 60 days"). The `donki` source splits longer windows into
  60-day requests.
- **One SEP is listed once per instrument.** A single solar particle event can
  appear as several SEP records minutes apart, one per instrument or energy
  channel (9 records on 2024-10-09, for example). The source merges records
  whose `eventTime` lies within 6 hours of a group's first record into one
  event, keeping the earliest `sepID` and giving the record count in the
  description.
- **Flares (FLR) are not checked against a live response.** The FLR endpoint
  answered HTTP 404 for every date tried, and the DONKI web service on
  `kauai.ccmc.gsfc.nasa.gov` could not be reached. The flare mapping follows the field names in the SPEC, and
  `include_flr` is off by default.
- Field names checked live: SEP `sepID`, `eventTime`; GST `gstID`,
  `startTime`, `allKpIndex[].kpIndex`; CME `activityID`, `startTime`.
- The window used here has 78 CME records in 11 days, which is why
  `include_cme` is off by default.

The API key comes from the `NASA_API_KEY` environment variable, falling back
to the rate-limited `DEMO_KEY`. It is never stored in the cache or in code.

---

## NASA Human Research Program: immune risk

**What:** the NASA Human Research Program (HRP) risk "Risk of Adverse Health
Event Due to Altered Immune Response"
(<https://www.nasa.gov/directorates/esdmd/hhp/risk-of-adverse-health-event-due-to-altered-immune-response/>).

**Where ORBIT uses it:** it is the problem ORBIT addresses. On long missions
the crew must notice immune changes themselves, without Earth.

- `README.md`, "The problem".
- `SPEC.md`, Part 1 "What ORBIT does".

---

## NASA Evidence Report (Crucian and Sams)

**What:** "Risk of Crew Adverse Health Event Due to Altered Immune Response",
B. Crucian and C. Sams, NASA Human Research Program Evidence Report,
NTRS 20140002769 (<https://ntrs.nasa.gov/citations/20140002769>).

**Where ORBIT uses it:** immune changes in flight, and the stressors ORBIT
records as context events.

- `orbit/schema/enums.py`, `EventType`: the stressors (solar particle events
  and other radiation, spacewalks, sleep-schedule shifts, an ill crewmate).
- `orbit/modules/scorer.py`: recent stress events add 1–10 points, by severity.
- `orbit/modules/simulator.py`: the illustrative scenarios (viral
  reactivation, EVA exertion, sleep shift, solar particle event).

---

## Herpes virus reactivation in astronauts (Rooney et al. 2019)

**What:** B. V. Rooney, B. E. Crucian, D. L. Pierson, M. L. Laudenslager and
S. K. Mehta, "Herpes Virus Reactivation in Astronauts During Spaceflight and
Its Application on Earth", NASA Johnson Space Center, *Frontiers in
Microbiology* 10:16 (2019), doi
[10.3389/fmicb.2019.00016](https://doi.org/10.3389/fmicb.2019.00016).

**Where ORBIT uses it:** why ORBIT watches VZV, HSV-1 and EBV, and why its
first procedure is a saliva viral-DNA test.

- `orbit/schema/signals.py`: the `saliva_ebv_dna`, `saliva_vzv_dna` and
  `saliva_hsv1_dna` signals.
- `orbit/modules/scorer.py`: virus DNA in saliva adds points that grow with
  viral load; signs typical of each virus (rash for VZV, mouth sores for HSV-1,
  swollen glands for EBV) weigh more than general symptoms.
- `cards/action_cards.jsonl`: `saliva-test` ("Take a saliva sample"), the
  first card at yellow, then `reduce-load` (VZV), `hsv-test` and `ebv-test`.
- The demo story: AST-01 develops a VZV (shingles) reactivation on days 89–90.

---

All medical content in ORBIT is illustrative. These resources explain why
ORBIT watches what it watches; they do not make its thresholds clinical.
