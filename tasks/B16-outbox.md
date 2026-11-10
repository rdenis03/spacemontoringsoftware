# B16 · Outbox with comms delay

**Lane:** API (M13, part 2) · **Needs:** B15 (order only) · **Branch:** `be/b16-outbox` · **Size:** M

## Goal

What leaves the spacecraft goes through a queue with a realistic
communication delay, and every send is logged. The frontend's Earth comms
screen shows each packet as queued, with a countdown, then delivered. A
per-send delay override makes "Moon mode" and "Mars mode" possible in the demo.

## Read first

- SPEC.md Part 3, M13 (*Build* steps 2 and 3) and M4 (how to add a table).
- `orbit/core/store.py` (`_TABLES`, `_ts`, `_tx`, `_docs`, `counts`).
- `orbit/core/config.py` (`Settings`, `load_settings`), `orbit/__main__.py` (`cmd_serve`).
- `orbit/core/interfaces.py` (`EarthPacket`), `orbit/api/app.py`.

## Files

- `orbit/core/store.py` (the `outbox` table and its methods only)
- `orbit/core/config.py` (the `[comms]` section only)
- `orbit/api/app.py`, `orbit/__main__.py` (pass the delay into `create_app`)
- `orbit.toml` (add the `[comms]` block)
- `tests/test_sync.py` (new)

## Build

1. In `store.py`, a frozen pydantic model `OutboxEntry`: `id`,
   `astronaut_id`, `created_at`, `deliver_at`, `packet: EarthPacket`,
   `summary: str = ""` (B17 fills it), `auto: bool = False` (B18 sets it).
2. Table `outbox(id TEXT PRIMARY KEY, astronaut_id TEXT, created_ts INTEGER, deliver_ts INTEGER, doc TEXT)`
   following the M4 pattern; methods `queue(entry)` and
   `outbox(astronaut_id=None) -> list[OutboxEntry]` (newest first); add it to `counts()`.
3. `[comms] one_way_delay_minutes = 20` → `Settings.comms_delay_minutes: float = 20.0`.
   `create_app(..., comms_delay_minutes=...)`; `cmd_serve` and
   `create_app_from_settings` pass the setting.
4. `POST /api/crew/{id}/earth-packet/send?start=&end=&delay_minutes=`: builds
   the packet with `pipeline.earth_packet`, queues it with
   `deliver_at = created_at + delay` (the override if given, else the
   setting), and returns the entry with its status.
5. `GET /api/outbox?astronaut_id=`: entries with `status` = `queued` or
   `delivered` (`delivered` once the real current time ≥ `deliver_at`) and
   `seconds_left`. Comms delay is real time, not mission time, so the demo
   countdown is visible.
6. Keep `package()` pure: the queue lives in the store and the API, not in the sync slot.

## Tests (`tests/test_sync.py`)

- Send with `delay_minutes=0` → `delivered`; with 20 → `queued`, `seconds_left` about 1200.
- The packet in the outbox has no readings from categories the astronaut does not share.
- `counts()` includes `outbox`; an old database without the table still opens.

## Done when

- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

Tell the frontend the response shapes. For Mars mode it can send
`delay_minutes` between 4 and 24; for Moon mode, about 0.02 (1.3 seconds).
