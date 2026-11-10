"""Tests for the learned scorer (B08) with the shipped weights (trained by B09)."""

import json
from pathlib import Path

import pytest
from conftest import DAY_89, DAY_90

from orbit.core import Pipeline, Store, create, load_settings
from orbit.learning import FEATURE_NAMES, extract
from orbit.modules.scorer_learned import DEFAULT_WEIGHTS, LearnedScorer, load_weights
from orbit.schema import AlertLevel

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ctx(loaded_pipeline):
    return loaded_pipeline.context("AST-01", DAY_90)


def anomalies_for(context):
    baselines = {b.signal: b for b in create("baseline", "rolling_median").compute(context)}
    return create("detector", "robust_z").detect(context, baselines)


def write_weights(tmp_path, weights, **extra) -> str:
    path = tmp_path / "weights.json"
    path.write_text(json.dumps({"version": "test-1", "scale": 1.0, "weights": weights,
                                "trained_on": None, **extra}), encoding="utf-8")
    return str(path)


def test_points_add_up_and_every_reason_is_explained(ctx):
    result = LearnedScorer().score(ctx, anomalies_for(ctx))
    assert result.contributors
    assert all(c.signal is not None or c.event_id is not None for c in result.contributors)
    assert all(c.points > 0 for c in result.contributors)
    assert result.score == pytest.approx(min(100, sum(c.points for c in result.contributors)))
    assert len({c.signal or c.event_id for c in result.contributors}) == len(result.contributors), \
        "one reason per signal or event"


def test_same_input_same_output_and_version(ctx):
    anomalies = anomalies_for(ctx)
    first = LearnedScorer().score(ctx, anomalies)
    second = LearnedScorer().score(ctx, anomalies)
    assert first.score == second.score and first.contributors == second.contributors
    assert first.model_version.startswith("learned-")
    assert first.model_version == f"learned-{load_weights(DEFAULT_WEIGHTS)[0]}"[:32]
    assert first.assessed_at == ctx.as_of and first.astronaut_id == "AST-01"


def test_features_of_one_signal_become_one_reason(ctx):
    # dev:skin_temp and drift:skin_temp share the skin_temp signal on day 90.
    features = extract(ctx, anomalies_for(ctx))
    names = {f.name for f in features}
    assert {"dev:skin_temp", "drift:skin_temp"} <= names
    weights = load_weights(DEFAULT_WEIGHTS)[2]
    value = {f.name: f.value for f in features}
    expected = round(weights["dev:skin_temp"] * value["dev:skin_temp"]
                     + weights["drift:skin_temp"] * value["drift:skin_temp"], 1)
    [skin] = [c for c in LearnedScorer().contributors(features) if c.signal == "skin_temp"]
    assert skin.points == pytest.approx(expected)
    assert skin.label.startswith("Skin temperature")


def test_shipped_weights_cover_every_feature():
    # B09 replaced the placeholder weights with trained ones: check the format, not the values.
    version, scale, weights = load_weights(DEFAULT_WEIGHTS)
    assert version.startswith("trained-") and scale == 1.0
    assert len(f"learned-{version}") <= 32, "model_version must not be cut"
    assert list(weights) == list(FEATURE_NAMES)
    assert all(w >= 0 for w in weights.values())
    assert weights["dev:skin_temp"] > 0 and weights["crp:high"] > 0
    trained_on = json.loads(DEFAULT_WEIGHTS.read_text(encoding="utf-8"))["trained_on"]
    assert not set(trained_on["seeds"]) & set(range(101, 106)), "101-105 are held out for B10"


def test_negative_weight_is_refused(tmp_path):
    with pytest.raises(ValueError, match="dev:skin_temp"):
        LearnedScorer(write_weights(tmp_path, {"dev:skin_temp": -1.0}))


def test_unknown_feature_and_bad_files_are_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown feature"):
        LearnedScorer(write_weights(tmp_path, {"dev:mood_ring": 1.0}))
    with pytest.raises(ValueError, match="scale"):
        LearnedScorer(write_weights(tmp_path, {"dev:skin_temp": 1.0}, scale=-2))
    with pytest.raises(ValueError, match="not found"):
        LearnedScorer(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        LearnedScorer(str(bad))


def test_custom_weights_path_is_used(tmp_path, ctx):
    path = write_weights(tmp_path, {"sym:symptom_rash_tingling": 10.0}, scale=2.0)
    result = LearnedScorer(path).score(ctx, anomalies_for(ctx))
    assert result.model_version == "learned-test-1"
    [rash] = result.contributors
    assert rash.signal == "symptom_rash_tingling"
    assert rash.points == pytest.approx(20.0)  # scale 2 x weight 10 x mild (1)
    assert result.score == pytest.approx(20.0)


def test_score_is_capped_at_100(tmp_path, ctx):
    path = write_weights(tmp_path, {name: 50.0 for name in FEATURE_NAMES})
    result = LearnedScorer(path).score(ctx, anomalies_for(ctx))
    assert result.score == 100 and result.level is AlertLevel.RED
    assert sum(c.points for c in result.contributors) > 100


def test_learned_config_alerts_on_the_demo_story():
    # With the trained weights (B09) AST-01 is red on days 89 and 90, not yellow then
    # orange. orbit.toml keeps rule_based and the pinned story; B10 decides on the switch.
    settings = load_settings(ROOT / "experiments" / "learned.toml")
    assert settings.modules["scorer"].use == "learned"
    assert load_settings(ROOT / "orbit.toml").modules["scorer"].use == "rule_based", \
        "orbit.toml keeps the starter until B10"
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    for choice in settings.sources:
        pipeline.ingest(create("source", choice.use, **choice.options))
    day89 = pipeline.assess("AST-01", DAY_89, save=False).assessment
    day90 = pipeline.assess("AST-01", DAY_90, save=False).assessment
    assert day89.level.rank >= AlertLevel.YELLOW.rank
    assert day90.level.rank >= AlertLevel.YELLOW.rank and day90.score >= day89.score
    assert pipeline.assess("AST-02", DAY_90, save=False).assessment.level is AlertLevel.GREEN
