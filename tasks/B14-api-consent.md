# B14 · Consent editing endpoint

**Lane:** API (M13, part 1) · **Needs:** B13 (order only) · **Branch:** `be/b14-api-consent` · **Size:** S

## Goal

Let the astronaut choose which kinds of data may leave the spacecraft. The
consent gate already respects `CrewMember.share_with_earth`; this endpoint
lets the frontend change it.

## Read first

- SPEC.md Part 3, M13, *Build* step 1.
- `orbit/schema/models.py` (`CrewMember`, `DEFAULT_SHARED_CATEGORIES`),
  `orbit/schema/enums.py` (`SignalCategory`).
- `orbit/modules/consent.py`, `orbit/api/app.py`.

## Files

- `orbit/api/app.py`
- `tests/test_api_consent.py` (new)

## Build

1. `PUT /api/crew/{astronaut_id}/consent` with body
   `{"share_with_earth": ["vital", "sleep"]}`.
2. Validate every value against `SignalCategory` (pydantic does this if the
   body model uses `list[SignalCategory]`): unknown → 422 with the message.
3. Save with `store.upsert_crew([CrewMember.model_validate({**member.model_dump(), "share_with_earth": ...})])`
   and return the updated `CrewMember`.
4. An empty list is allowed (share nothing). Score and level still go to
   Earth regardless (that is the consent gate's job, not this endpoint's).

## Tests (`tests/test_api_consent.py`)

- `PUT ["vital"]` then `GET /api/crew` shows only `vital` for that astronaut.
- After that, `/earth-packet` withholds sleep readings.
- An unknown category gives 422; an unknown astronaut gives 404.

## Done when

- [ ] `python -m pytest` and `python -m orbit demo` pass.
