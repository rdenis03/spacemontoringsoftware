"""Tests for the M2 mission simulator, version 1: healthy crew (B02)."""

import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from orbit.core import Pipeline, Store, create
from orbit.core.config import load_settings
from orbit.modules.simulator import MissionSimulator
from orbit.schema import (
    AlertLevel,
    Observation,
    Quality,
    SignalType,
    read_labels,
    write_jsonl,
)

ROOT = Path(__file__).resolve().parent.parent


def _jsonl(sim: MissionSimulator, tmp_path: Path, name: str) -> bytes:
    path = tmp_path / name
    write_jsonl(sim.read().observations, path)
    return path.read_bytes()


def test_same_options_give_identical_output(tmp_path):
    first = _jsonl(MissionSimulator(days=30, seed=7), tmp_path, "a.jsonl")
    second = _jsonl(MissionSimulator(days=30, seed=7), tmp_path, "b.jsonl")
    assert first == second
    sim = MissionSimulator(days=30, seed=7)
    assert _jsonl(sim, tmp_path, "c.jsonl") == _jsonl(sim, tmp_path, "d.jsonl"), \
        "reading twice must give the same output"


def test_different_seed_gives_different_output(tmp_path):
    assert _jsonl(MissionSimulator(days=10, seed=1), tmp_path, "a.jsonl") != \
        _jsonl(MissionSimulator(days=10, seed=2), tmp_path, "b.jsonl")


def test_records_per_astronaut_per_day():
    sim = MissionSimulator(days=21, crew_size=3)
    batch = sim.read()
    assert batch.source_name == "simulator"
    assert [m.astronaut_id for m in batch.crew] == ["AST-01", "AST-02", "AST-03"]
    counts = Counter(
        (o.astronaut_id, o.timestamp.date(), o.source.value) for o in batch.observations
    )
    for member in batch.crew:
        for day in range(1, 22):
            date = sim.day_start(day).date()
            key = (member.astronaut_id, date)
            assert counts[(*key, "wearable")] == 7
            assert counts[(*key, "checkin")] == 10
            assert counts[(*key, "environment")] == 2
            assert counts[(*key, "lab")] == (3 if day % 7 == 1 else 0)


def test_records_are_valid_and_simulated():
    batch = MissionSimulator(days=14).read()
    ids = [o.observation_id for o in batch.observations]
    assert len(ids) == len(set(ids)), "IDs must be unique"
    for obs in batch.observations:
        Observation.model_validate(obs.model_dump())  # round-trips through validation
        assert obs.simulated is True
        assert obs.quality is Quality.GOOD
        assert obs.observation_id == (
            f"{obs.astronaut_id}-{obs.signal.value}-{obs.timestamp:%Y%m%d}")
    wearable = [o for o in batch.observations if o.source.value == "wearable"]
    assert all(o.device_id == f"wrist-{o.astronaut_id.lower()}" for o in wearable)


def test_healthy_crew_has_no_symptoms_and_low_saliva_dna():
    batch = MissionSimulator(days=60, scenarios=[]).read()
    by_category = Counter()
    for obs in batch.observations:
        if obs.category.value == "symptom":
            assert obs.value == 0
            by_category["symptom"] += 1
        if obs.signal.value.startswith("saliva_"):
            assert obs.value < 100
    assert by_category["symptom"] > 0
    assert MissionSimulator(scenarios=[]).labels() == []


def test_180_days_by_4_crew_is_fast():
    start = time.perf_counter()
    batch = MissionSimulator(days=180, crew_size=4, scenarios=[]).read()
    elapsed = time.perf_counter() - start
    assert elapsed < 5, f"took {elapsed:.1f} s"
    assert len(batch.observations) == 4 * (180 * 19 + 26 * 3)  # 26 lab days in 180

    start = time.perf_counter()
    MissionSimulator(days=180, crew_size=4).read()  # with random illness episodes
    assert time.perf_counter() - start < 5


def test_mean_skin_temp_stays_near_personal_normal():
    sim = MissionSimulator(days=180)
    batch = sim.read()
    for member in sim.crew:
        temps = [o.value for o in batch.observations
                 if o.astronaut_id == member.astronaut_id and o.signal is SignalType.SKIN_TEMP]
        mean = sum(temps) / len(temps)
        assert abs(mean - sim.normals[member.astronaut_id][SignalType.SKIN_TEMP]) < 0.2


def test_effects_hook_adds_offsets():
    healthy = MissionSimulator(days=10).read()
    sim = MissionSimulator(days=10)
    sim.effects.append(lambda astronaut, day: (
        {SignalType.SKIN_TEMP: 0.5, SignalType.SYMPTOM_FATIGUE: 2}
        if astronaut == "AST-01" and day == 5 else {}))
    sick = sim.read()
    changed = {a.observation_id: b.value - a.value
               for a, b in zip(healthy.observations, sick.observations, strict=True)
               if a.value != b.value}
    assert set(changed) == {"AST-01-skin_temp-20270108", "AST-01-symptom_fatigue-20270108"}
    assert changed["AST-01-skin_temp-20270108"] == pytest.approx(0.5)
    assert changed["AST-01-symptom_fatigue-20270108"] == 2


def test_works_with_no_options_and_from_config():
    assert create("source", "simulator").read().observations
    settings = load_settings(ROOT / "experiments" / "sim180.toml")
    [source] = settings.sources
    assert source.use == "simulator" and source.options["days"] == 180
    assert Path(source.options["labels_path"]) == ROOT / "data" / "sim" / "labels.jsonl"
    assert Path(settings.database) == ROOT / "data" / "sim180.db"


# ---- B03: illness episodes and labels ---------------------------------------

VZV_DAY_40 = [{"type": "viral_reactivation", "astronaut": "AST-02", "virus": "vzv",
               "symptom_day": 40}]


def _values(batch, astronaut, signal):
    """{mission day: value} for one astronaut's signal (one reading per day)."""
    start = batch.crew[0].mission_start
    return {(o.timestamp - start).days + 1: o.value for o in batch.observations
            if o.astronaut_id == astronaut and o.signal is signal}


def test_viral_episode_raises_skin_temp_in_prodrome():
    sim = MissionSimulator(days=50, scenarios=VZV_DAY_40)
    temps = _values(sim.read(), "AST-02", SignalType.SKIN_TEMP)
    before = [temps[d] for d in range(24, 38)]  # the 14 days before day -2
    prodrome = [temps[d] for d in (38, 39)]
    assert sum(prodrome) / 2 - sum(before) / 14 > 0.15


def test_inline_scenario_lands_on_requested_astronaut_and_day():
    sim = MissionSimulator(days=50, scenarios=VZV_DAY_40)
    [label] = sim.labels()
    assert label.astronaut_id == "AST-02" and label.virus == "vzv"
    assert label.should_alert is True
    assert label.symptom_onset == sim.day_start(40) + timedelta(hours=7)
    assert label.onset == sim.day_start(38)  # default lead_days = 2
    batch = sim.read()
    rash = _values(batch, "AST-02", SignalType.SYMPTOM_RASH_TINGLING)
    assert rash[39] == 0 and rash[40] >= 1
    assert all(v == 0 for v in _values(batch, "AST-01", SignalType.SYMPTOM_RASH_TINGLING).values())
    assert _values(batch, "AST-02", SignalType.SYMPTOM_FATIGUE)[40] in (1, 2)


def test_extra_lab_tests_start_on_symptom_day():
    sim = MissionSimulator(days=50, scenarios=[
        *VZV_DAY_40,
        {"type": "respiratory_infection", "astronaut": "AST-03", "symptom_day": 35},
    ])
    batch = sim.read()
    extra = [o for o in batch.observations if o.observation_id.endswith("-09")]
    assert extra and all(o.timestamp.hour == 9 and o.source.value == "lab" for o in extra)
    vzv = [o for o in extra if o.signal is SignalType.SALIVA_VZV_DNA]
    crp = [o for o in extra if o.signal is SignalType.CRP]
    assert {o.astronaut_id for o in vzv} == {"AST-02"}
    assert {o.astronaut_id for o in crp} == {"AST-03"}
    assert min(o.timestamp for o in vzv) == sim.day_start(40) + timedelta(hours=9)
    assert min(o.timestamp for o in crp) == sim.day_start(35) + timedelta(hours=9)
    assert max(o.value for o in vzv) > 100 and max(o.value for o in crp) > 10
    ids = [o.observation_id for o in batch.observations]
    assert len(ids) == len(set(ids))


def test_labels_are_consistent_and_deterministic(tmp_path):
    sim = MissionSimulator(days=180, seed=3)
    labels = sim.labels()
    assert labels, "180 days x 4 crew should contain an illness"
    for label in labels:
        assert label.symptom_onset >= label.onset
        assert label.resolved > label.symptom_onset
        assert label.onset >= sim.day_start(22)
    assert labels == MissionSimulator(days=180, seed=3).labels()

    path = tmp_path / "sim" / "labels.jsonl"
    MissionSimulator(days=180, seed=3, labels_path=str(path)).read()
    assert read_labels(path) == labels


def test_random_episodes_follow_illness_rate():
    counts = []
    for seed in range(1, 6):
        sim = MissionSimulator(days=180, crew_size=4, seed=seed)
        per_astronaut = Counter(label.astronaut_id for label in sim.labels())
        counts += [per_astronaut[m.astronaut_id] for m in sim.crew]
        for member in sim.crew:
            own = [e for e in sim.episodes if e.astronaut_id == member.astronaut_id]
            for x, y in zip(own, own[1:]):
                assert y.first_day > x.last_day, "episodes of one astronaut must not overlap"
            assert all(e.first_day >= 22 and e.last_day <= 180 for e in own)
    mean = sum(counts) / len(counts)  # illness_rate 1.0 per 90 days -> about 2
    assert 1.0 <= mean <= 3.0, counts


def test_illness_episodes_keep_records_valid():
    batch = MissionSimulator(days=180, seed=2).read()
    for obs in batch.observations:
        Observation.model_validate(obs.model_dump())
        assert obs.quality is Quality.GOOD and obs.simulated is True


def test_bad_inline_scenarios_are_rejected():
    for bad in (
        [{"type": "viral_reactivation", "astronaut": "AST-01", "symptom_day": 30}],  # no virus
        [{"type": "eva_exertion", "astronaut": "AST-01", "symptom_day": 30}],
        [{"type": "respiratory_infection", "astronaut": "AST-09", "symptom_day": 30}],
        [{"type": "respiratory_infection", "astronaut": "AST-01", "symptom_day": 99}],
        [{"type": "respiratory_infection", "astronaut": "AST-01", "symptom_day": 30, "x": 1}],
        [{"type": "viral_reactivation", "astronaut": "AST-01", "virus": "ebv",
          "symptom_day": 30, "lead_days": 4}],
        VZV_DAY_40 * 2,  # overlapping
        "sometimes",
    ):
        with pytest.raises(ValueError):
            MissionSimulator(days=50, scenarios=bad)


def test_injected_vzv_turns_starter_pipeline_yellow_by_symptom_day():
    settings = load_settings(ROOT / "orbit.toml")
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    sim = MissionSimulator(days=45, scenarios=VZV_DAY_40)
    pipeline.ingest(sim.read())
    levels = {day: pipeline.assess("AST-02", sim.day_start(day) + timedelta(hours=10),
                                   save=False).assessment.level
              for day in range(30, 41)}
    assert levels[30] is AlertLevel.GREEN
    assert max(level.rank for level in levels.values()) >= AlertLevel.YELLOW.rank, levels
