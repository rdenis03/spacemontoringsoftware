import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from orbit.schema import (
    OBSERVATION_COLUMNS,
    SIGNALS,
    ContextEvent,
    Observation,
    RiskAssessment,
    SchemaError,
    from_dataframe,
    parse_csv,
    parse_jsonl,
    to_dataframe,
    write_csv,
    write_jsonl,
)
from orbit.schema.export import EXPORTED_MODELS, export_all

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture
def observations():
    base = dict(astronaut_id="AST-01", source="wearable")
    return [
        Observation(timestamp="2027-04-01T06:00:00Z", signal="skin_temp", value=34.4, **base),
        Observation(timestamp="2027-04-02T06:00:00Z", signal="skin_temp", value=34.5, **base),
        Observation(timestamp="2027-04-02T06:00:00Z", signal="hrv_rmssd", value=66, **base),
        Observation(astronaut_id="007", timestamp="2027-04-02T07:00:00Z",
                    signal="symptom_fatigue", value=1, source="checkin", note="tired, all good"),
    ]


def test_jsonl_round_trip(tmp_path, observations):
    path = tmp_path / "obs.jsonl"
    assert write_jsonl(observations, path) == 4
    assert parse_jsonl(path).raise_if_errors() == observations


def test_csv_round_trip_keeps_leading_zeros(tmp_path, observations):
    path = tmp_path / "obs.csv"
    write_csv(observations, path)
    loaded = parse_csv(path).raise_if_errors()
    assert loaded == observations
    assert loaded[3].astronaut_id == "007"


def test_dataframe_round_trip(observations):
    frame = to_dataframe(observations)
    assert tuple(frame.columns) == OBSERVATION_COLUMNS
    assert str(frame["timestamp"].dt.tz) == "UTC"
    assert frame["value"].dtype == "float64"
    assert (frame["signal"] == "skin_temp").sum() == 2
    assert from_dataframe(frame).raise_if_errors() == observations


def test_empty_dataframe_has_columns():
    frame = to_dataframe([])
    assert tuple(frame.columns) == OBSERVATION_COLUMNS
    assert len(frame) == 0


def test_bad_rows_reported_with_line_numbers(tmp_path, observations):
    path = tmp_path / "mixed.jsonl"
    good = observations[0].model_dump_json()
    path.write_text(
        "\n".join([
            good,
            "{not json",
            json.dumps({"astronaut_id": "AST-01", "timestamp": "2027-04-01T06:00:00",
                        "signal": "skin_temp", "value": 34.4, "source": "wearable"}),
            "",
            json.dumps({"astronaut_id": "AST-01", "timestamp": "2027-04-01T06:00:00Z",
                        "signal": "skin_temp", "value": 61, "source": "wearable"}),
            "[1, 2]",
        ]) + "\n",
        encoding="utf-8",
    )
    result = parse_jsonl(path)
    assert result.summary() == "1 valid, 4 rejected"
    assert [e.row for e in result.errors] == [2, 3, 5, 6]
    assert "not valid JSON" in result.errors[0].message
    assert "timezone" in result.errors[1].message
    assert "plausible range" in result.errors[2].message
    with pytest.raises(SchemaError, match="4 invalid record"):
        result.raise_if_errors()


def test_csv_errors_use_spreadsheet_line_numbers(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame([
        {"astronaut_id": "AST-01", "timestamp": "2027-04-01T06:00:00Z",
         "signal": "resting_hr", "value": "52", "source": "wearable"},
        {"astronaut_id": "AST-01", "timestamp": "2027-04-02T06:00:00Z",
         "signal": "resting_hr", "value": "", "source": "wearable"},
    ]).to_csv(path, index=False)
    result = parse_csv(path)
    assert len(result.valid) == 1
    assert result.errors[0].row == 3  # header is line 1
    assert "value" in result.errors[0].message


def test_example_files_are_valid():
    checks = {
        "observations.jsonl": Observation,
        "observations.csv": Observation,
        "context_events.jsonl": ContextEvent,
        "risk_assessments.jsonl": RiskAssessment,
        "crew.jsonl": EXPORTED_MODELS["crew_member"],
        "action_cards.jsonl": EXPORTED_MODELS["action_card"],
    }
    for name, model in checks.items():
        path = EXAMPLES / name
        reader = parse_csv if path.suffix == ".csv" else parse_jsonl
        assert reader(path, model).ok, name


def test_export_writes_valid_json(tmp_path):
    paths = export_all(tmp_path)
    assert len(paths) == len(EXPORTED_MODELS) + 1
    for path in paths:
        json.loads(path.read_text(encoding="utf-8"))
    registry = json.loads((tmp_path / "signals.json").read_text(encoding="utf-8"))
    assert [s["signal"] for s in registry["signals"]] == [s.value for s in SIGNALS]
    assert registry["alert_level_order"] == ["green", "yellow", "orange", "red"]


def test_cli_validate_exit_codes(tmp_path):
    good = subprocess.run(
        [sys.executable, "-m", "orbit.schema", "validate", str(EXAMPLES / "observations.jsonl")],
        capture_output=True, text=True,
    )
    assert good.returncode == 0, good.stderr
    assert "0 rejected" in good.stdout

    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text('{"astronaut_id": "AST-01"}\n', encoding="utf-8")
    bad = subprocess.run(
        [sys.executable, "-m", "orbit.schema", "validate", str(bad_file)],
        capture_output=True, text=True,
    )
    assert bad.returncode == 1
    assert "row 1" in bad.stdout
