# B12 · NASA space weather feed

**Lane:** Data (M5) · **Needs:** none · **Branch:** `data/b12-space-weather` · **Size:** M

## Goal

Turn real solar flares, particle events and geomagnetic storms from NASA's
DONKI service into ORBIT events, so solar storms count as immune stressors. On
a real mission the ground fetches and uplinks; the spacecraft reads a local
cache. Model exactly that, and make it possible to replay a real storm (for
example May 2024) inside the 2027 demo mission.

## Human step first (needs internet)

An agent may not have internet. Before mapping any fields, a person records one
real response per endpoint into `tests/fixtures/donki/` (PowerShell, from the repo folder):

```powershell
mkdir tests\fixtures\donki
foreach ($e in "FLR","SEP","CME","GST") {
  curl.exe -s "https://api.nasa.gov/DONKI/${e}?startDate=2024-05-08&endDate=2024-05-14&api_key=DEMO_KEY" -o "tests\fixtures\donki\${e}_2024-05.json"
}
```

Use your own `NASA_API_KEY` instead of `DEMO_KEY` if you hit the rate limit.
Check that each file holds a JSON list, not an error message.

## Read first

- SPEC.md Part 3, M5: API, options, mapping, severity, end times, requirements.
- The recorded fixtures: confirm the field names before mapping.
- `orbit/schema/models.py` (`ContextEvent`), `orbit/schema/enums.py` (`EventType`, `Severity`).

## Files

- `orbit/modules/space_weather.py` (new)
- `orbit/modules/__init__.py` (one import line)
- `tests/fixtures/donki/*.json` (recorded by a person)
- `tests/test_space_weather.py` (new)
- `experiments/donki.toml` (new)

## Build

1. `@register("source", "donki")` with the options in SPEC M5 (`mode`,
   `cache_path`, `real_start`, `real_end`, `mission_start`, `include_cme`).
2. `mode="cache"` reads only the cache file: no network, ever. A missing cache
   gives an empty batch with a `RowError`, not a crash.
3. `mode="fetch"` downloads with `urllib` (no new dependency), key from
   `NASA_API_KEY` or `DEMO_KEY`, writes the cache, and raises a clear error on
   a network failure.
4. Mapping, severity and end times exactly as SPEC M5, assumptions written in
   the docstring. `event_id = f"donki-{external_id}"`, `astronaut_id=None`,
   `source="ground"`.
5. Time shift: with `mission_start` set, every date moves so `real_start`
   lands on `mission_start`.
6. `experiments/donki.toml`: `orbit.toml` plus a `donki` source in cache mode
   with `real_start = "2024-05-08"`, `real_end = "2024-05-14"` and
   `mission_start = "2027-03-30T00:00:00Z"`, so the May 10–11 storm lands on
   mission days 88–89 of the demo.

## Tests (`tests/test_space_weather.py`)

From the fixtures only (no network): the mapping per endpoint, severity
rules, the time shift, a missing cache, and that CMEs are skipped unless
`include_cme = true`.

## Done when

- [ ] `python -m orbit --config experiments/donki.toml demo` shows the storm
      among AST-01's reasons around day 88–89.
- [ ] `python -m pytest` and `python -m orbit demo` pass.
