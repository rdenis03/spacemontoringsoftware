# B11 · Wearable CSV import

**Lane:** Data (M3) · **Needs:** none · **Branch:** `be/b11-wearable-import` · **Size:** M

## Goal

Load a real watch or ring export safely: map the vendor's columns to ORBIT
signals, convert units, attach a timezone, flag bad data instead of dropping
it, and report every problem with its row number. This is what makes the
"live body demo" (B20) able to use a teammate's real data.

## Read first

- SPEC.md Part 3, M3: options, conversions, quality rules, output. Follow it exactly.
- `orbit/schema/io.py` (`parse_records`, `ParseResult`, `RowError`).
- `orbit/schema/signals.py` (units, plausible ranges, allowed sources).
- `orbit/modules/sources.py` (`FileSource`).

## Files

- `orbit/modules/ingestion.py` (new)
- `orbit/modules/__init__.py` (one import line)
- `tests/fixtures/ingestion/*.csv` (new, small hand-made files)
- `tests/test_ingestion.py` (new)

## Build

1. `@register("source", "wearable_csv")` with the options in SPEC M3
   (`path`, `astronaut_id`, `timestamp_column`, `timezone`, `columns`,
   `units`, `device_id`). With no options, `read()` returns an empty batch
   with a clear `RowError`, so the contract test passes.
2. The conversions in SPEC M3 (°F→°C, fraction→percent for `spo2` and
   `sleep_efficiency`, minutes and seconds→hours for sleep duration). An unknown
   unit is a `RowError`, never a guess. Relative "deviation" columns are
   rejected with a clear message.
3. Quality rules from SPEC M3: out of range → kept with `quality="bad"` and a
   note with the raw value; vendor low-wear flag → `suspect`; duplicates →
   keep the last; empty cells → skipped silently.
4. Naive timestamps need `timezone` (IANA name, `zoneinfo`); without it, every
   row is a `RowError`.
5. `source_name = f"wearable_csv:{filename}"`. `source="wearable"` on readings.
6. Optional: `normalize_records(records) -> ParseResult` for later API use. Do
   not change the API.

## Tests (`tests/test_ingestion.py`)

One fixture per case: °F temperatures, fraction SpO₂, naive timestamps with a
timezone, an out-of-range value, a duplicate row, an unknown unit, a
deviation column. Assert values, quality flags and row-numbered errors.

## Done when

- [ ] Every fixture imports as SPEC M3 specifies; the source contract test passes.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Add a commented-out `[[sources]] use = "wearable_csv"` example block to
`orbit.toml`'s data sources section, with `columns` for one common export.
