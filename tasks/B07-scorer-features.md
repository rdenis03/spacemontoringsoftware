# B07 · Feature extraction for the AI scorer

**Lane:** AI · **Needs:** none · **Branch:** `be/b07-scorer-features` · **Size:** S

## Goal

Turn one astronaut-day (the context plus the detector's anomalies) into a
fixed list of numbers, each with a plain-language reason. The trainer (B09)
learns a weight per number; the learned scorer (B08) multiplies them back into
points. Because both use this one function, training and runtime can never
disagree, and every point keeps a reason the astronaut can check.

## Read first

- `orbit/modules/scorer.py`: reuse `describe_anomaly`, `CHECKIN_FRESHNESS`,
  `EVENT_NAMES`, `SYMPTOM_WEIGHTS`, `VIRAL_DNA` instead of copying them.
- `orbit/core/interfaces.py`: `AssessmentContext` (`latest`, `events`, `as_of`).
- `orbit/schema/enums.py`: `SignalCategory`, `EventType`, `Severity`.
- `tests/test_contracts.py`: the `ctx` (sick AST-01, day 90) and `quiet_ctx`
  fixtures.

## Files

- `orbit/learning/__init__.py` (new)
- `orbit/learning/features.py` (new)
- `tests/test_features.py` (new)

## Build

```python
@dataclass(frozen=True)
class Feature:
    name: str                    # stable key, e.g. "dev:skin_temp"
    value: float                 # always >= 0
    label: str                   # reason shown to the astronaut if it earns points
    signal: SignalType | None = None
    event_id: str | None = None

FEATURE_NAMES: tuple[str, ...]   # every name extract() can return, fixed order
def extract(ctx, anomalies) -> list[Feature]       # non-zero features only
def vector(features) -> dict[str, float]           # all FEATURE_NAMES, zeros filled
```

Features (worrying direction only; the detector already filters direction):

| Name | Value | Label, signal / event |
|---|---|---|
| `dev:<signal>` for the 7 vital and sleep signals | `min(abs(deviation), 3.0)` of that signal's anomaly | `describe_anomaly(...)`, signal |
| `drift:<signal>` for the same 7 | 1.0 if that anomaly is a drift | same label, same signal |
| `vitals_moving` | number of vital anomalies when it is 2 or more, else 0 | "N vital signs moved together", signal = the most deviant one |
| `sym:<signal>` for the 8 symptoms | latest value within `CHECKIN_FRESHNESS` (0–3) | as in `rule_based`, signal |
| `dna:<signal>` for the 3 saliva DNA signals | 0 below 100 copies/mL, else `1 + log10(value / 100)` | as in `rule_based`, signal |
| `crp:high` | 1.0 if latest CRP > 10 mg/L | as in `rule_based`, `crp` |
| `stress:high`, `mood:low` | 1.0 if fresh stress ≥ 4 / mood ≤ 2 | as in `rule_based`, signal |
| `event:<event_type>` for each `EventType` | highest severity rank (low 1 … extreme 4) among events that started by `as_of` | `"<name> <n days ago>"`, `event_id` of that event |

Rules: pure (no clock, no I/O, no randomness); same input gives the same list
in the same order; every feature has `signal` or `event_id` set.

## Tests (`tests/test_features.py`)

- On `ctx` (AST-01, day 90): `dev:skin_temp`, `sym:symptom_rash_tingling` and
  `dna:saliva_vzv_dna` are present and positive.
- On `quiet_ctx` (AST-02): no `dev:*` and no `sym:*` features.
- `vector()` has exactly `FEATURE_NAMES` as keys, in that order.
- Calling `extract` twice gives equal results.

## Done when

- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

`FEATURE_NAMES` is the contract with B08 and B09. If you add a feature later,
add it at the end of the tuple and retrain (B09).
