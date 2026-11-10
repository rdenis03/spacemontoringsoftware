# B15 · Shared status for the crew view

**Lane:** API (M14, backend part) · **Needs:** B14 (order only) · **Branch:** `be/b15-api-shared-status` · **Size:** S

## Goal

The commander and the crew medical officer see who needs attention, without
seeing private details the astronaut has not shared. The status endpoint gets
a `view=shared` mode that runs the result through the consent gate.

## Read first

- SPEC.md Part 3, M14.
- `orbit/modules/consent.py` (`ConsentGate.package`, `PRIVATE_LABEL`).
- `orbit/api/app.py` (`/status`, and `/day` from B13).

## Files

- `orbit/api/app.py`
- `tests/test_api_shared.py` (new)

## Build

1. `GET /api/crew/{id}/status?view=shared` (and the same on `/day` from B13).
   `view` is `"full"` (default) or `"shared"`.
2. For `shared`: pass the assessment through
   `pipeline.sync.package(member, [], [assessment])` and use the redacted
   assessment it returns. Drop anomalies and baselines whose signal category
   the astronaut does not share. Keep score, level, action cards and
   `escalate_to`.
3. `"full"` behaves exactly as today.

## Tests (`tests/test_api_shared.py`)

By default, symptoms and wellbeing are not shared.

- AST-01's shared status keeps score and level, but symptom reasons show
  `PRIVATE_LABEL`, and no symptom anomalies are returned.
- Vital reasons are unchanged.
- After sharing `symptom` with B14's endpoint, the rash reason shows in the shared view.

## Done when

- [ ] `python -m pytest` and `python -m orbit demo` pass.
