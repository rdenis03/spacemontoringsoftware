"""Tests for the M2 mission simulator, version 1: healthy crew (B02)."""

import time
from collections import Counter
from pathlib import Path

import pytest

from orbit.core import create
from orbit.core.config import load_settings
from orbit.modules.simulator import MissionSimulator
from orbit.schema import Observation, Quality, SignalType, write_jsonl

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
    batch = MissionSimulator(days=60).read()
    by_category = Counter()
    for obs in batch.observations:
        if obs.category.value == "symptom":
            assert obs.value == 0
            by_category["symptom"] += 1
        if obs.signal.value.startswith("saliva_"):
            assert obs.value < 100
    assert by_category["symptom"] > 0
    assert MissionSimulator().labels() == []


def test_180_days_by_4_crew_is_fast():
    start = time.perf_counter()
    batch = MissionSimulator(days=180, crew_size=4).read()
    elapsed = time.perf_counter() - start
    assert elapsed < 5, f"took {elapsed:.1f} s"
    assert len(batch.observations) == 4 * (180 * 19 + 26 * 3)  # 26 lab days in 180


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
