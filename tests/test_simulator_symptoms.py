"""B24 step 1: symptom look-alikes and mild illness in the simulator (M2)."""

from __future__ import annotations

import hashlib
import json

import pytest

from orbit.core import create
from orbit.modules.simulator import MILD_VITAL_SCALE, MissionSimulator
from orbit.schema import ScenarioType, SignalType

S = SignalType
T = ScenarioType

# SHA-256 of seed 1's default read() + labels, recorded before B24 changed the simulator.
DEFAULT_SEED1_SHA256 = "1234dff1960446bc4e379f33351e34c6ead2a732a18645f9c6d3a0763e5c1640"


def _canon(item) -> dict:
    data = item.model_dump(mode="json")
    if "share_with_earth" in data:  # a set: its order changes with Python's hash seed
        data["share_with_earth"] = sorted(data["share_with_earth"])
    return data


def _sha(sim: MissionSimulator) -> str:
    batch = sim.read()
    doc = {"crew": [_canon(m) for m in batch.crew],
           "observations": [_canon(o) for o in batch.observations],
           "events": [_canon(e) for e in batch.events],
           "labels": [_canon(label) for label in sim.labels()]}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def _sim(**options) -> MissionSimulator:
    sim = create("source", "simulator", **options)
    assert isinstance(sim, MissionSimulator)
    return sim


def _checkin(sim: MissionSimulator, astronaut: str, day: int) -> dict[SignalType, float]:
    stamp = sim.day_start(day).strftime("%Y%m%d")
    return {o.signal: o.value for o in sim.read().observations
            if o.astronaut_id == astronaut and o.source == "checkin"
            and o.observation_id.endswith(stamp)}


def test_default_output_is_byte_identical_to_before_b24():
    assert _sha(_sim(seed=1)) == DEFAULT_SEED1_SHA256


def test_options_off_draw_no_random_numbers():
    assert _sha(_sim(seed=1, symptom_lookalikes=False, mild_illness_rate=0.0)) \
        == DEFAULT_SEED1_SHA256


def test_options_on_change_the_output_and_stay_deterministic():
    on = dict(seed=1, symptom_lookalikes=True, mild_illness_rate=0.3)
    first = _sha(_sim(**on))
    assert first != DEFAULT_SEED1_SHA256
    assert _sha(_sim(**on)) == first


def test_spacewalk_gives_aches_and_fatigue_the_next_morning():
    plan = [{"type": "eva_exertion", "astronaut": "AST-01", "day": 30}]
    sim = _sim(days=40, crew_size=1, scenarios=plan, symptom_lookalikes=True)
    same_day, next_day = _checkin(sim, "AST-01", 30), _checkin(sim, "AST-01", 31)
    assert same_day[S.SYMPTOM_MUSCLE_ACHES] == 0 and same_day[S.SYMPTOM_FATIGUE] == 0
    assert next_day[S.SYMPTOM_MUSCLE_ACHES] in (1, 2)
    assert next_day[S.SYMPTOM_FATIGUE] == 1
    assert _checkin(sim, "AST-01", 32)[S.SYMPTOM_MUSCLE_ACHES] == 0


def test_spacewalk_without_the_option_has_no_symptoms():
    plan = [{"type": "eva_exertion", "astronaut": "AST-01", "day": 30}]
    sim = _sim(days=40, crew_size=1, scenarios=plan)
    assert _checkin(sim, "AST-01", 31)[S.SYMPTOM_MUSCLE_ACHES] == 0


def test_sleep_shift_gives_fatigue_and_sometimes_headache():
    plan = [{"type": "sleep_shift", "astronaut": "AST-01", "day": 30, "nights": 3}]
    sim = _sim(days=40, crew_size=1, scenarios=plan, symptom_lookalikes=True)
    days = [_checkin(sim, "AST-01", d) for d in (30, 31, 32)]
    assert all(d[S.SYMPTOM_FATIGUE] == 1 for d in days)
    assert all(d[S.SYMPTOM_HEADACHE] in (0, 1) for d in days)
    assert _checkin(sim, "AST-01", 33)[S.SYMPTOM_FATIGUE] == 0


def test_stress_load_in_list_mode():
    plan = [{"type": "stress_load", "astronaut": "AST-01", "day": 30, "nights": 3}]
    sim = _sim(days=40, crew_size=1, scenarios=plan)
    for day in (30, 31, 32):
        values = _checkin(sim, "AST-01", day)
        assert values[S.STRESS] in (4, 5)
        assert values[S.MOOD] == 2
        assert values[S.SYMPTOM_HEADACHE] == 1
    after = _checkin(sim, "AST-01", 33)
    assert after[S.MOOD] >= 3 and after[S.STRESS] <= 3  # healthy draws again
    (label,) = sim.labels()
    assert label.scenario is T.STRESS_LOAD and label.should_alert is False
    assert label.symptom_onset is None
    assert sim.events() == []  # no event, and no vital change:
    healthy = _sim(days=40, crew_size=1, scenarios=[]).read().observations
    stressed = sim.read().observations
    vitals = lambda obs: [(o.observation_id, o.value) for o in obs if o.source == "wearable"]
    assert vitals(stressed) == vitals(healthy)


@pytest.mark.parametrize("nights", [1, 5])
def test_stress_load_nights_are_checked(nights):
    plan = [{"type": "stress_load", "astronaut": "AST-01", "day": 30, "nights": nights}]
    with pytest.raises(ValueError, match="nights"):
        _sim(days=40, crew_size=1, scenarios=plan)


def test_random_mode_places_stress_load_only_with_the_option():
    def kinds(**kw):
        return {label.scenario for label in _sim(days=180, seed=1, **kw).labels()}
    assert T.STRESS_LOAD not in kinds()
    assert T.STRESS_LOAD in kinds(symptom_lookalikes=True)
    assert T.STRESS_LOAD not in kinds(symptom_lookalikes=True, confounders=False)


def test_symptom_lookalikes_keep_the_other_labels():
    plain = [label.label_id for label in _sim(days=180, seed=1).labels()]
    with_symptoms = _sim(days=180, seed=1, symptom_lookalikes=True).labels()
    assert [label.label_id for label in with_symptoms
            if label.scenario is not T.STRESS_LOAD] == plain


def test_mild_illness_scales_the_vitals_only():
    full = _sim(days=180, seed=1)
    mild = _sim(days=180, seed=1, mild_illness_rate=1.0)
    assert [e.symptom_day for e in mild.episodes] == [e.symptom_day for e in full.episodes]
    for usual, small in zip(full.episodes, mild.episodes, strict=True):
        lo, hi = MILD_VITAL_SCALE
        assert lo <= small.vital_scale <= hi
        day0 = usual.symptom_day
        a, b = usual(usual.astronaut_id, day0), small(small.astronaut_id, day0)
        for signal in (S.SKIN_TEMP, S.RESTING_HR, S.RESP_RATE):
            assert b[signal] == pytest.approx(a[signal] * small.vital_scale)
        for signal, level in usual.symptoms:
            assert b[signal] == a[signal] == level
        if usual.virus:
            dna = {"ebv": S.SALIVA_EBV_DNA, "vzv": S.SALIVA_VZV_DNA, "hsv1": S.SALIVA_HSV1_DNA}
            assert b[dna[usual.virus]] == a[dna[usual.virus]]
        assert small.label(mild.day_start).notes.startswith("Mild")


def test_mild_illness_rate_is_checked_and_ignored_in_list_mode():
    with pytest.raises(ValueError, match="mild_illness_rate"):
        _sim(mild_illness_rate=1.5)
    plan = [{"type": "viral_reactivation", "astronaut": "AST-01", "virus": "vzv", "symptom_day": 30}]
    sim = _sim(days=40, crew_size=1, scenarios=plan, mild_illness_rate=1.0)
    assert sim.episodes[0].vital_scale == 1.0
