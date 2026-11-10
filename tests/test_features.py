"""Tests for the AI scorer's feature extraction (B07)."""

import pytest
from conftest import DAY_90

from orbit.core import AssessmentContext, create
from orbit.learning import FEATURE_NAMES, Feature, extract, vector


@pytest.fixture
def ctx(loaded_pipeline) -> AssessmentContext:
    return loaded_pipeline.context("AST-01", DAY_90)


@pytest.fixture
def quiet_ctx(loaded_pipeline) -> AssessmentContext:
    return loaded_pipeline.context("AST-02", DAY_90)


def features_for(context: AssessmentContext) -> list[Feature]:
    baselines = {b.signal: b for b in create("baseline", "rolling_median").compute(context)}
    anomalies = create("detector", "robust_z").detect(context, baselines)
    return extract(context, anomalies)


def test_sick_day_has_key_features(ctx):
    values = {f.name: f.value for f in features_for(ctx)}
    for name in ("dev:skin_temp", "sym:symptom_rash_tingling", "dna:saliva_vzv_dna"):
        assert values.get(name, 0) > 0, name


def test_quiet_day_has_no_deviation_or_symptom(quiet_ctx):
    names = [f.name for f in features_for(quiet_ctx)]
    assert not [n for n in names if n.startswith(("dev:", "sym:"))]


def test_vector_has_all_names_in_order(ctx):
    vec = vector(features_for(ctx))
    assert tuple(vec) == FEATURE_NAMES
    assert vector([]) == dict.fromkeys(FEATURE_NAMES, 0.0)


def test_extract_is_deterministic(ctx):
    assert features_for(ctx) == features_for(ctx)


def test_every_feature_is_explained_and_ordered(ctx):
    features = features_for(ctx)
    assert features
    assert all(f.value > 0 and f.label for f in features)
    assert all(f.signal is not None or f.event_id is not None for f in features)
    positions = [FEATURE_NAMES.index(f.name) for f in features]
    assert positions == sorted(positions)
    assert len(set(FEATURE_NAMES)) == len(FEATURE_NAMES)
