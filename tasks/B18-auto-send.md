# B18 · Auto-send on orange or red

**Lane:** API · **Needs:** B17 · **Branch:** `data/b18-auto-send` · **Size:** S

## Goal

When an astronaut reaches orange or red, ORBIT queues a report to Earth by
itself, so the ground learns about a serious change without anyone pressing
send. The crew still gets their action cards at once; Earth hears later,
after the comms delay. This is the "ORBIT acts first, Earth confirms later" moment of the demo.

## Read first

- `orbit/core/pipeline.py` (`Pipeline.on("assessed", callback)`: failing listeners are logged and ignored).
- `orbit/__main__.py` (`cmd_serve`: the first run happens **before** `create_app`).
- `orbit/api/app.py`, `orbit/api/earth_report.py` (B17), `orbit/core/store.py` (B16).

## Files

- `orbit/api/app.py`
- `orbit/core/config.py` (one more `[comms]` key only)
- `orbit.toml` (`[comms]` block)
- `tests/test_auto_send.py` (new)

## Build

1. `[comms] auto_send_level = "orange"` (`"off"` disables it) →
   `Settings.comms_auto_send_level`, passed into `create_app` like the delay.
2. In `create_app`, register `pipeline.on("assessed", ...)`: when the result's
   level ranks at or above the setting, queue a packet covering the last 3
   days up to `as_of`, with `summary` from B17 and `auto=True`.
3. At most one auto packet per astronaut per assessment day (the UTC date of
   `as_of`): check the outbox first.
4. At startup, check every astronaut's latest status once, because `serve`
   assesses before the hook exists.
5. Never raise from the listener: a failed send must not break an assessment.

## Tests (`tests/test_auto_send.py`)

- A check-in that takes AST-01 to orange queues exactly one auto packet;
  a second check-in on the same day queues none.
- AST-02 (green) gets none. With `"off"`, nobody gets one.
- The auto packet respects consent, like a manual one.

## Done when

- [ ] With `python -m orbit serve`, `GET /api/outbox` shows an auto packet for AST-01 right after startup.
- [ ] `python -m pytest` and `python -m orbit demo` pass.
