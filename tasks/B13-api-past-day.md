# B13 · Past-day endpoint for replay

**Lane:** API · **Needs:** none · **Branch:** `data/b13-api-past-day` · **Size:** S

## Goal

The frontend's mission replay slider needs the full result of any past day,
including its action cards, not only the latest one. Everything is already
saved in the store; this endpoint just reads it back.

## Read first

- `orbit/api/app.py` (how `/status` is built) and `tests/test_api.py` (how API tests use `TestClient`).
- `orbit/core/pipeline.py`: `Pipeline.status` (the pattern to copy for a given time).
- `orbit/core/store.py`: `assessments`, `recommendations`, `anomalies_at`, `baselines`.

## Files

- `orbit/api/app.py`
- `tests/test_api_day.py` (new)

## Build

1. `GET /api/crew/{astronaut_id}/day?as_of=<ISO datetime>` returns a
   `DayResult` for the assessment saved at exactly that time: assessment,
   its action cards (`recommendations`), its anomalies and baselines.
   Naive times are UTC (use the existing `_utc` helper).
2. 404 with a clear message for an unknown astronaut or when nothing was
   assessed at that time.
3. Build it inside `app.py` with store methods. Do not change
   `orbit/core/`.

## Tests (`tests/test_api_day.py`)

- For every item in `/assessments` for AST-01, `/day?as_of=<assessed_at>`
  returns the same score and level.
- The latest day equals `/status` (same score, same card ids).
- A time with no assessment gives 404.

## Done when

- [ ] The endpoint appears in `/docs`.
- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Tell the frontend the endpoint is live; the replay slider takes `as_of`
values from `/assessments` (`assessed_at`).
