from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import DAY_89, DAY_90

from orbit.core import (
    ConfigError,
    Pipeline,
    RegistryError,
    Store,
    create,
    load_settings,
    register,
)
from orbit.schema import AlertLevel


def test_demo_scenario_end_to_end(ran_pipeline):
    """AST-01 goes green -> yellow -> orange as the illness develops; AST-02 stays green."""
    store = ran_pipeline.store
    sick = {a.assessed_at: a for a in store.assessments("AST-01")}
    assert sick[DAY_90 - timedelta(days=2)].level is AlertLevel.GREEN
    assert sick[DAY_89].level is AlertLevel.YELLOW
    assert sick[DAY_90].level is AlertLevel.ORANGE
    assert {a.level for a in store.assessments("AST-02")} == {AlertLevel.GREEN}

    status = ran_pipeline.status("AST-01")
    assert status.mission_day == 90
    assert status.actions and status.actions[0].card_id == "reduce-load"
    assert any("VZV" in c.label for c in status.assessment.contributors)
    assert status.baselines and status.anomalies


def test_context_windows_do_not_overlap(loaded_pipeline):
    ctx = loaded_pipeline.context("AST-01", DAY_90)
    assert ctx.history and ctx.recent
    assert max(o.timestamp for o in ctx.history) < ctx.recent_start
    assert min(o.timestamp for o in ctx.recent) >= ctx.recent_start
    assert max(o.timestamp for o in ctx.recent) <= ctx.as_of
    assert all(o.is_usable for o in ctx.history + ctx.recent)
    assert {e.event_id for e in ctx.events} == {"sep-20270402", "eva-20270401"}


def test_rerun_is_idempotent(ran_pipeline):
    before = ran_pipeline.store.counts()
    ran_pipeline.run()
    assert ran_pipeline.store.counts() == before


def test_failing_module_does_not_stop_the_day(loaded_pipeline):
    class BrokenDetector:
        def detect(self, ctx, baselines):
            raise RuntimeError("divide by zero in my new algorithm")

    loaded_pipeline.detector = BrokenDetector()
    result = loaded_pipeline.assess("AST-01", DAY_90)
    assert result.errors == ("detector: RuntimeError: divide by zero in my new algorithm",)
    assert result.assessment is not None  # still scored from symptoms, lab and events
    assert result.assessment.score > 0
    assert result.actions


def test_hooks_receive_results(loaded_pipeline):
    seen = []
    loaded_pipeline.on("assessed", seen.append)
    loaded_pipeline.on("assessed", lambda r: 1 / 0)  # a broken listener is ignored
    loaded_pipeline.run(date(2027, 4, 2), date(2027, 4, 3), ["AST-01"])
    assert [r.mission_day for r in seen] == [89, 90]
    with pytest.raises(ValueError, match="unknown hook"):
        loaded_pipeline.on("exploded", print)


def test_ingest_rejects_unknown_astronaut(loaded_pipeline):
    from orbit.schema import Observation

    stray = Observation(astronaut_id="AST-99", timestamp=DAY_90, signal="skin_temp",
                        value=34.0, source="wearable")
    report = loaded_pipeline.ingest(create("source", "memory", observations=[stray]))
    assert report.observations == 0
    assert "unknown astronaut 'AST-99'" in report.errors[0].message


def test_earth_packet_follows_consent(ran_pipeline):
    packet = ran_pipeline.earth_packet("AST-01", DAY_90 - timedelta(days=3), DAY_90)
    assert packet.withheld.get("symptom", 0) > 0
    assert all(o.category.value != "symptom" for o in packet.observations)


# ---- registry and config ---------------------------------------------------------


def test_register_and_create_custom_module():
    @register("baseline", "test_constant")
    class ConstantBaseline:
        def __init__(self, value: float = 1.0):
            self.value = value

        def compute(self, ctx):
            return []

    assert create("baseline", "test_constant", value=2.0).value == 2.0
    with pytest.raises(RegistryError, match="bad options"):
        create("baseline", "test_constant", nonsense=1)
    with pytest.raises(RegistryError, match="no 'baseline' module called 'nope'"):
        create("baseline", "nope")


def test_registry_rejects_wrong_interface():
    @register("scorer", "test_wrong_method")
    class WrongMethod:
        def calculate(self, ctx, anomalies):
            return None

    with pytest.raises(RegistryError, match="does not implement RiskScorer"):
        create("scorer", "test_wrong_method")


def test_config_resolves_paths_relative_to_file(settings):
    cards = Path(settings.modules["actions"].options["cards_path"])
    assert cards.is_absolute() and cards.is_file()
    assert Path(settings.sources[0].options["observations_path"]).is_file()
    assert settings.recent_days == 3 and settings.assessment_hour_utc == 10


def test_config_errors(tmp_path):
    bad_slot = tmp_path / "a.toml"
    bad_slot.write_text('[modules.magic]\nuse = "x"\n')
    with pytest.raises(ConfigError, match="not a slot"):
        load_settings(bad_slot)
    no_use = tmp_path / "b.toml"
    no_use.write_text("[modules.scorer]\nweight = 2\n")
    with pytest.raises(ConfigError, match="use ="):
        load_settings(no_use)
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "missing.toml")


def test_defaults_without_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORBIT_CONFIG", raising=False)
    settings = load_settings()
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    assert pipeline.module_names["scorer"] == "rule_based"
