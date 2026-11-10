# B17 · Plain-language report for Earth

**Lane:** API · **Needs:** B16 · **Branch:** `be/b17-earth-report` · **Size:** S

## Goal

Each packet sent to Earth carries a short report a flight surgeon can read in
ten seconds: status, top reasons, actions taken, and what the astronaut kept
private. Built from templates, so it works offline and never invents medical
content.

Example:

> AST-01 Vega · ORANGE (70) · mission day 90 · Skin temperature 0.45 °C above normal for 2 days; resting heart rate up; saliva VZV DNA 850 copies/mL · Actions: reduce workload, crew medical officer informed · Withheld by the astronaut: symptom (8), wellbeing (2)

## Read first

- `orbit/core/interfaces.py` (`EarthPacket`), `orbit/core/store.py` (`OutboxEntry`, B16).
- `orbit/modules/consent.py` (`PRIVATE_LABEL`), `orbit/schema/models.py` (`ActionCard.triggers`).
- `orbit/api/app.py` (the send endpoint from B16).

## Files

- `orbit/api/earth_report.py` (new)
- `orbit/api/app.py` (fill `summary` when sending)
- `tests/test_earth_report.py` (new)

## Build

1. `build_report(member, packet, actions=()) -> str`, pure: no clock, no I/O.
2. Use only what is in the packet, which is already consent-filtered: the
   latest assessment's level, score and mission day; its top 3 reasons, with
   private reasons counted ("2 private reasons") rather than listed; the
   `withheld` counts per category.
3. Actions: list a card's title and `escalate_to` only when all its
   `triggers` are in categories the astronaut shares; otherwise count it as
   "1 private action". A card title can reveal a symptom.
4. One line, at most 600 characters, sentence case, no medication, no diagnosis words.
5. The send endpoint sets `summary = build_report(member, packet, latest actions)`.

## Tests (`tests/test_earth_report.py`)

- AST-01 day 90 with default sharing: mentions `ORANGE` and the score; does
  not contain "rash" or "fatigue" (symptoms are private by default).
- After sharing `symptom`, the rash reason appears.
- Same input gives the same text; length ≤ 600.

## Done when

- [ ] `GET /api/outbox` shows the `summary` for new packets.
- [ ] `python -m pytest` and `python -m orbit demo` pass.
