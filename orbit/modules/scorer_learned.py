"""Learned risk scorer (slot ``scorer``, registered as ``learned``): M8, task B08.

The runtime half of the AI scorer. B07's ``extract`` turns an astronaut-day
into explained features; this module multiplies each one by a learned weight
and turns the result into points with reasons. No machine-learning library at
runtime: it is multiplication, so it runs offline and is deterministic. The
trainer (B09) only has to write a new weights file.

Weights file (JSON; default ``orbit/learning/weights.json``)::

    {
      "version": "placeholder-1",      # model_version becomes "learned-placeholder-1"
      "scale": 1.0,                    # multiplies every weight (>= 0)
      "weights": {"dev:skin_temp": 2.5, "sym:symptom_rash_tingling": 7.0, ...},
      "trained_on": null,              # B09: what the weights were trained on
      "notes": "..."                   # optional, free text
    }

Every key in ``weights`` must be one of ``FEATURE_NAMES`` (B07) and every
weight must be a number >= 0, or loading raises ``ValueError``. Features
missing from the file have weight 0. The shipped file holds hand-set
placeholder weights that mirror ``rule_based`` (about 2.5 per vital deviation,
1.5 per sleep deviation, 0.5 per drift, ``SYMPTOM_WEIGHTS`` for symptoms, 4 per
DNA unit, 8 for high CRP, 3 for stress and mood, 2.5 per event severity rank).
They are illustrative, not clinical.

Scoring: ``points = scale x weight x value`` per feature. Features that share a
reason (same ``signal``, or same ``event_id``) become one ``Contributor`` with
their points summed and the label of the first of them (in ``FEATURE_NAMES``
order) that earns points; reasons with zero points are dropped. Each reason's
points are rounded to 0.1, and ``score = min(100, round(sum of the reasons, 1))``,
so the reasons always add up to the score before the cap.

Options:

    weights_path   None   path to the weights JSON; None = the shipped file
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from orbit.core.interfaces import AssessmentContext
from orbit.core.registry import register
from orbit.schema import Anomaly, Contributor, RiskAssessment

if TYPE_CHECKING:
    from orbit.learning.features import Feature

# orbit.learning.features imports orbit.modules.scorer, and orbit.modules imports
# this file, so B07's features are imported inside the functions that use them
# (a top-level import would make `import orbit.learning` fail with a circular import).

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[1] / "learning" / "weights.json"


def load_weights(path: str | Path) -> tuple[str, float, dict[str, float]]:
    """(version, scale, weights) from a weights file; raises ValueError if invalid."""
    from orbit.learning.features import FEATURE_NAMES

    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"weights file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("weights"), dict):
        raise ValueError(f"{path}: needs a 'weights' object")

    version = str(doc.get("version") or "unversioned")
    scale = doc.get("scale", 1.0)
    if not _is_number(scale) or scale < 0:
        raise ValueError(f"{path}: scale must be a number >= 0, got {scale!r}")

    known = set(FEATURE_NAMES)
    weights: dict[str, float] = {}
    for name, weight in doc["weights"].items():
        if name not in known:
            raise ValueError(f"{path}: unknown feature {name!r} (see FEATURE_NAMES)")
        if not _is_number(weight) or weight < 0:
            raise ValueError(f"{path}: weight for {name!r} must be a number >= 0, got {weight!r}")
        weights[name] = float(weight)
    return version, float(scale), weights


def _is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


@register("scorer", "learned")
class LearnedScorer:
    def __init__(self, weights_path: str | None = None):
        self.weights_path = Path(weights_path) if weights_path else DEFAULT_WEIGHTS
        version, self.scale, self.weights = load_weights(self.weights_path)
        self.version = f"learned-{version}"

    def score(self, ctx: AssessmentContext, anomalies: Sequence[Anomaly]) -> RiskAssessment:
        from orbit.learning.features import extract

        reasons = self.contributors(extract(ctx, anomalies))
        total = min(100.0, round(sum(r.points for r in reasons), 1))
        return RiskAssessment(
            astronaut_id=ctx.astronaut_id,
            assessed_at=ctx.as_of,
            score=total,
            contributors=reasons,
            model_version=self.version[:32],
        )

    def contributors(self, features: Sequence["Feature"]) -> list[Contributor]:
        """Points per reason: features with the same signal or event_id are summed."""
        groups: dict[tuple, dict] = {}
        for feature in features:
            points = self.scale * self.weights.get(feature.name, 0.0) * feature.value
            key = ("signal", feature.signal) if feature.signal is not None \
                else ("event", feature.event_id)
            group = groups.setdefault(key, {"points": 0.0, "label": None, "feature": feature})
            group["points"] += points
            if group["label"] is None and points > 0:
                group["label"] = feature.label
        out = []
        for group in groups.values():
            points = round(group["points"], 1)
            if points <= 0:
                continue
            feature = group["feature"]
            out.append(Contributor(label=group["label"], points=points,
                                   signal=feature.signal, event_id=feature.event_id))
        return out
