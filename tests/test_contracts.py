"""Contract tests: every registered implementation of every slot must pass these.

When a teammate registers a new module (``@register("detector", "cusum")``),
it is picked up here automatically. If these pass, the module plugs into the
pipeline. Each module must also work with its default options.
"""

from dataclasses import replace

import pytest
from conftest import DAY_90

from orbit.core import AssessmentContext, EarthPacket, SourceBatch, available, create
from orbit.schema import (
    ActionCard,
    AlertLevel,
    Anomaly,
    Baseline,
    RiskAssessment,
    SignalCategory,
    level_for_score,
)


@pytest.fixture
def ctx(loaded_pipeline) -> AssessmentContext:
    return loaded_pipeline.context("AST-01", DAY_90)


@pytest.fixture
def quiet_ctx(loaded_pipeline) -> AssessmentContext:
    return loaded_pipeline.context("AST-02", DAY_90)


# ---- source -----------------------------------------------------------------


@pytest.mark.parametrize("name", available("source"))
def test_source_contract(name):
    batch = create("source", name).read()
    assert isinstance(batch, SourceBatch)
    assert isinstance(batch.source_name, str) and batch.source_name


# ---- baseline ---------------------------------------------------------------


@pytest.mark.parametrize("name", available("baseline"))
def test_baseline_contract(name, ctx):
    engine = create("baseline", name)
    baselines = engine.compute(ctx)
    assert baselines, "should find a baseline in two weeks of data"
    assert all(isinstance(b, Baseline) for b in baselines)
    assert all(b.astronaut_id == ctx.astronaut_id and b.as_of == ctx.as_of for b in baselines)
    assert len({b.signal for b in baselines}) == len(baselines), "one baseline per signal"


@pytest.mark.parametrize("name", available("baseline"))
def test_baseline_ignores_recent_data(name, ctx):
    """'Your normal' must come from history only, or an illness hides itself."""
    engine = create("baseline", name)
    without_recent = replace(ctx, recent=())
    assert engine.compute(ctx) == engine.compute(without_recent)


@pytest.mark.parametrize("name", available("baseline"))
def test_baseline_with_no_history(name, ctx):
    assert create("baseline", name).compute(replace(ctx, history=())) == []


# ---- detector ---------------------------------------------------------------


@pytest.mark.parametrize("name", available("detector"))
def test_detector_contract(name, ctx):
    baselines = {b.signal: b for b in create("baseline", "rolling_median").compute(ctx)}
    anomalies = create("detector", name).detect(ctx, baselines)
    assert all(isinstance(a, Anomaly) for a in anomalies)
    assert all(a.astronaut_id == ctx.astronaut_id for a in anomalies)
    assert {a.signal for a in anomalies} <= set(baselines)
    assert anomalies, "the day-90 scenario should produce anomalies"


@pytest.mark.parametrize("name", available("detector"))
def test_detector_without_baselines(name, ctx):
    assert create("detector", name).detect(ctx, {}) == []


# ---- scorer -------------------------------------------------------------------


@pytest.mark.parametrize("name", available("scorer"))
def test_scorer_contract(name, ctx, quiet_ctx):
    scorer = create("scorer", name)
    for context in (ctx, quiet_ctx):
        result = scorer.score(context, [])
        assert isinstance(result, RiskAssessment)
        assert result.astronaut_id == context.astronaut_id
        assert result.assessed_at == context.as_of
        assert scorer.score(context, []).score == result.score, "must be deterministic"


@pytest.mark.parametrize("name", available("scorer"))
def test_scorer_ranks_sick_above_well(name, ctx, quiet_ctx):
    baseline, detector = create("baseline", "rolling_median"), create("detector", "robust_z")

    def run(context):
        found = {b.signal: b for b in baseline.compute(context)}
        return create("scorer", name).score(context, detector.detect(context, found)).score

    assert run(ctx) > run(quiet_ctx)


# ---- actions ------------------------------------------------------------------


@pytest.mark.parametrize("name", available("actions"))
@pytest.mark.parametrize("score", [0, 30, 60, 90])
def test_actions_never_leave_astronaut_without_a_step(name, score, ctx):
    assessment = RiskAssessment(astronaut_id=ctx.astronaut_id, assessed_at=ctx.as_of, score=score)
    cards = create("actions", name).recommend(assessment, ctx)
    assert cards and all(isinstance(c, ActionCard) for c in cards)
    assert all(c.level.rank <= level_for_score(score).rank for c in cards)


# ---- sync -----------------------------------------------------------------------


@pytest.mark.parametrize("name", available("sync"))
def test_sync_respects_consent(name, loaded_pipeline):
    member = loaded_pipeline.store.member("AST-01")
    observations = loaded_pipeline.store.observations("AST-01", usable_only=False)
    assessment = RiskAssessment(
        astronaut_id="AST-01", assessed_at=DAY_90, score=40,
        contributors=[{"label": "Fatigue: moderate", "points": 6, "signal": "symptom_fatigue"},
                      {"label": "Skin temp up", "points": 9, "signal": "skin_temp"}],
    )
    packet = create("sync", name).package(member, observations, [assessment])
    assert isinstance(packet, EarthPacket)
    sent_categories = {o.category for o in packet.observations}
    assert sent_categories <= member.share_with_earth
    assert SignalCategory.SYMPTOM not in sent_categories
    assert len(packet.observations) + sum(packet.withheld.values()) == len(observations)
    sent = packet.assessments[0]
    assert sent.score == 40 and sent.level is AlertLevel.YELLOW
    assert all("Fatigue" not in c.label for c in sent.contributors)
    assert any(c.label == "Skin temp up" for c in sent.contributors)
