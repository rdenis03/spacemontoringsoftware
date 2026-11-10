# B03 · Simulator v2: illness episodes and labels

**Lane:** Simulator (M2) · **Needs:** B02 · **Branch:** `data/b03-simulator-illness` · **Size:** M

## Goal

Add the illnesses ORBIT must catch: viral reactivation (EBV, VZV, HSV-1) and
respiratory infection, each with a ground-truth `ScenarioLabel`. The gap
between physiological onset and symptom onset is the early-warning window the
whole pitch is about.

## Read first

- SPEC.md Part 3, M2: the `viral_reactivation` and `respiratory_infection`
  rows, the `scenarios`, `illness_rate` and `labels_path` options.
- `orbit/modules/simulator.py` docstring (the effect hook B02 described).
- `orbit/schema/labels.py` (B01).

## Files

- `orbit/modules/simulator.py`
- `tests/test_simulator.py` (add tests)

## Build

1. `viral_reactivation` with `virus` in `ebv`, `vzv`, `hsv1` and
   `lead_days` (default 2, allowed 1 to 3): vitals and sleep shift from
   day −`lead_days` with the ramps in SPEC M2; that virus's saliva DNA rises
   from day −3 (extra lab tests during the episode, IDs with the hour added);
   from day 0, fatigue 1–2 plus the virus's own sign (VZV
   `symptom_rash_tingling`, HSV-1 `symptom_mouth_sores`, EBV
   `symptom_swollen_glands` and `symptom_sore_throat`); recovery over 5–10 days.
2. `respiratory_infection`: the effects in SPEC M2, with CRP lab readings.
3. `scenarios` option: `"random"`, or a list of inline tables such as
   `{type = "viral_reactivation", astronaut = "AST-02", virus = "vzv", symptom_day = 90}`.
   `"random"` places episodes at `illness_rate` per astronaut per 90 days,
   never overlapping for one astronaut, never in the first 21 days (so a
   baseline exists).
4. One `ScenarioLabel` per episode: `onset` = physiological onset,
   `symptom_onset` = day 0 at 07:00, `resolved` = end of recovery,
   `should_alert=True`. `labels()` returns them; when `labels_path` is set,
   `read()` also writes them with `write_labels`.
5. Keep every value inside the plausible range and every record valid.

## Tests

- An injected viral episode raises mean skin temperature in its prodrome
  (day −2 to −1) compared with the 14 days before.
- `symptom_onset >= onset` for every label; labels are deterministic.
- An inline scenario lands on the requested astronaut and day.
- With `scenarios="random"`, 180 days × 4 crew gives about
  `illness_rate × 2` episodes per astronaut (allow a wide range).

## Done when

- [ ] With the starter modules, an injected VZV episode turns that astronaut
      at least yellow on or before symptom day (SPEC M2 *Done when*).
- [ ] `python -m orbit --config experiments/sim180.toml demo` runs.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

B04 adds look-alikes through the same effect hook. B06 and B09 call
`MissionSimulator(...).read()` and `.labels()`; keep those two calls stable.
