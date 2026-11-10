# B05 · Evaluation metrics

**Lane:** Evaluation (M9) · **Needs:** B01 · **Branch:** `be/b05-eval-metrics` · **Size:** S

## Goal

The pure math behind the pitch numbers: given a list of assessments and a list
of labels, compute sensitivity, lead time and false alarms exactly as SPEC M9
defines them. No simulator or pipeline here, so it can be built and tested
before the simulator is finished.

## Read first

- SPEC.md Part 3, M9: *Metrics (exact definitions)*.
- `orbit/schema/labels.py` (B01): `ScenarioLabel.window()`.
- `orbit/schema/models.py`: `RiskAssessment`, `AlertLevel`.

## Files

- `orbit/evaluation/__init__.py` (new)
- `orbit/evaluation/metrics.py` (new)
- `tests/test_evaluation.py` (new)

## Build

Pure functions, no I/O, no clock:

1. `alerts(assessments, min_level=AlertLevel.YELLOW) -> list[RiskAssessment]`.
2. `episodes(assessments, min_level) -> list[Episode]`: runs of consecutive
   days with alerts, per astronaut (`Episode`: astronaut, start, end).
3. `sensitivity(assessments, labels, min_level) -> float | None`: share of
   `should_alert` labels with at least one alert in their window.
4. `lead_times(...) -> list[float]`: per detected label,
   `symptom_onset − first alert in the window`, in days (positive = before
   symptoms). Plus a `summary` helper giving median, min and max.
5. `false_alarms(...) -> FalseAlarmReport`: episodes that overlap no
   `should_alert` window, as a count and per 30 astronaut-days; and,
   reported separately, how many of them overlap a confounder window.
6. `evaluate(assessments, labels, min_level, astronaut_days) -> dict`, which
   bundles all of the above into one JSON-ready dict.

## Tests (`tests/test_evaluation.py`)

Build tiny hand-made inputs (3 to 10 assessments, 1 to 3 labels) and assert
exact numbers:

- An alert 2 days before symptom onset gives lead time 2.0.
- An alert only after the window gives sensitivity 0.
- An alert run during a spacewalk label counts as a false alarm and as a
  confounder alarm.
- Two separate alert runs give two episodes; one run of 3 days gives one.
- No labels gives sensitivity `None`, not a division error.

## Done when

- [ ] `python -m pytest` and `python -m orbit demo` pass.

## Hand-off

B06 calls `evaluate(...)` once per config and seed. Document the returned
dict's keys in the module docstring.
