"""Tests for the scorer trainer (B09). Skipped when scikit-learn is not installed."""

import json

import pytest

pytest.importorskip("sklearn")

from conftest import CONFIG  # noqa: E402

from orbit.learning import FEATURE_NAMES  # noqa: E402
from orbit.learning.train import main, parse_seeds, seeds_label, train  # noqa: E402
from orbit.modules.scorer_learned import LearnedScorer, load_weights  # noqa: E402

# Seed 2: seed 1 has no illness in 40 days x 2 crew, so there is nothing to learn from.
TINY = ["--days", "40", "--crew", "2", "--seeds", "2", "--config", str(CONFIG)]


def test_tiny_run_writes_weights_the_learned_scorer_loads(tmp_path):
    out = tmp_path / "weights.json"
    assert main([*TINY, "--out", str(out)]) == 0

    version, scale, weights = load_weights(out)
    assert version == "trained-s2-d40-c2" and scale == 1.0
    assert list(weights) == list(FEATURE_NAMES)
    assert all(w >= 0 for w in weights.values())
    assert any(w > 0 for w in weights.values())

    scorer = LearnedScorer(str(out))
    assert scorer.version == "learned-trained-s2-d40-c2"
    assert len(scorer.version) <= 32

    info = json.loads(out.read_text(encoding="utf-8"))["trained_on"]
    assert (info["seeds"], info["days"], info["crew"]) == ([2], 40, 2)
    assert info["samples"] == 2 * (40 - 22 + 1)
    assert 0 < info["positives"] < info["samples"]
    assert info["intercept"] < 0
    assert 0.5 <= info["training_auc"] <= 1
    # Dropped and unseen features weigh nothing.
    for name in info["dropped_features"] + info["unseen_features"]:
        assert weights[name] == 0


def test_two_identical_runs_write_identical_files(tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    assert main([*TINY, "--out", str(first)]) == 0
    assert main([*TINY, "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()


def test_seed_arguments():
    assert parse_seeds("1-20") == list(range(1, 21))
    assert parse_seeds("1,2,5") == [1, 2, 5]
    assert parse_seeds("7,1-3") == [1, 2, 3, 7]
    assert seeds_label(range(1, 21)) == "1-20"
    assert seeds_label([1, 2, 3, 7]) == "1-3.7"
    for bad in ("", "a-b", "5-1"):
        with pytest.raises(ValueError):
            parse_seeds(bad)


def test_held_out_seeds_are_refused(tmp_path):
    with pytest.raises(ValueError, match="held out"):
        train([1, 101], days=40, crew=2, out=tmp_path / "w.json", config=CONFIG)
    assert not (tmp_path / "w.json").exists()
