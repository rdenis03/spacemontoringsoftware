"""Export the schema for non-Python teammates (frontend, other languages).

Writes:
    <name>.schema.json  standard JSON Schema for each model
    signals.json        the signal registry, alert levels and thresholds

JSON Schema cannot express the cross-field rules (unit must match the signal,
plausible ranges ...). Those live in signals.json, so a JavaScript client can
apply the same checks and show the same labels and units as the backend.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .enums import AlertLevel, SignalCategory
from .models import (
    DEFAULT_SHARED_CATEGORIES,
    LEVEL_THRESHOLDS,
    SCHEMA_VERSION,
    ActionCard,
    Anomaly,
    Baseline,
    ContextEvent,
    CrewMember,
    Observation,
    RiskAssessment,
)
from .signals import SIGNALS

EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "observation": Observation,
    "context_event": ContextEvent,
    "crew_member": CrewMember,
    "baseline": Baseline,
    "anomaly": Anomaly,
    "risk_assessment": RiskAssessment,
    "action_card": ActionCard,
}
OUTPUT_MODELS = frozenset({"baseline", "anomaly", "risk_assessment", "action_card"})


def registry_document() -> dict:
    """Everything a frontend needs to label, group and validate signals."""
    return {
        "schema_version": SCHEMA_VERSION,
        "categories": [c.value for c in SignalCategory],
        "default_shared_categories": sorted(c.value for c in DEFAULT_SHARED_CATEGORIES),
        "alert_levels": [
            {"level": level.value, "min_score": minimum}
            for minimum, level in sorted(LEVEL_THRESHOLDS)
        ],
        "alert_level_order": [level.value for level in AlertLevel],
        "signals": [spec.to_dict() for spec in SIGNALS.values()],
    }


def export_all(out_dir: str | Path) -> list[Path]:
    """Write every schema file into ``out_dir``. Returns the paths written."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTED_MODELS.items():
        # Inputs: describe what may be sent in. Outputs: what clients will receive.
        mode = "serialization" if name in OUTPUT_MODELS else "validation"
        schema = model.model_json_schema(mode=mode)
        schema["$id"] = f"orbit/{SCHEMA_VERSION}/{name}.schema.json"
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    path = out / "signals.json"
    path.write_text(
        json.dumps(registry_document(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written.append(path)
    return written
