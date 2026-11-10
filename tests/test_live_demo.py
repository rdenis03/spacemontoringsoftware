"""Tests for the live body demo tool (B20). In-process, no network."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbit.api import create_app
from orbit.core import Pipeline, Store, load_settings
from orbit.schema import AlertLevel, SignalType

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("live_demo", ROOT / "tools" / "live_demo.py")
live_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_demo)

S = SignalType
NOW = datetime(2027, 5, 20, 15, 30, tzinfo=timezone.utc)  # afternoon, like a pitch
NORMALS = {S.RESTING_HR: 62, S.SKIN_TEMP: 34.1, S.HRV_RMSSD: 55, S.RESP_RATE: 14,
           S.SPO2: 97, S.SLEEP_DURATION: 7.0}


@pytest.fixture
def pipeline():
    pipeline = Pipeline.from_settings(load_settings(ROOT / "orbit.toml"), store=Store(":memory:"))
    pipeline.ingest(live_demo.build_seed("AST-03", "Live", NORMALS, NOW))
    return pipeline


@pytest.fixture
def client(pipeline):
    return TestClient(create_app(pipeline))


def _push(client, readings, symptoms=None, when=NOW):
    sent = client.post("/api/observations", json=live_demo.build_push("AST-03", readings, when))
    assert sent.status_code == 200 and sent.json()["rejected"] == 0, sent.text
    response = client.post("/api/crew/AST-03/checkin",
                           json=live_demo.build_checkin(when, symptoms=symptoms))
    assert response.status_code == 200, response.text
    return response.json()


def test_seed_gives_14_normal_nights_ending_last_night(pipeline):
    readings = pipeline.store.observations("AST-03")
    stamps = sorted({o.timestamp for o in readings})
    assert len(stamps) == 14 and len(readings) == 14 * 6
    assert stamps[-1] == datetime(2027, 5, 20, 6, tzinfo=timezone.utc)
    assert all(o.source.value == "manual" for o in readings)
    hr = [o.value for o in readings if o.signal is S.RESTING_HR]
    assert abs(sum(hr) / len(hr) - 62) < 1.5


def test_after_seed_assessing_now_is_green(pipeline):
    result = pipeline.assess("AST-03", NOW, save=False)
    assert result.assessment.level is AlertLevel.GREEN
    assert result.baselines, "14 nights give a personal normal"


def test_hr_and_temp_jump_with_fever_turns_at_least_yellow(client):
    result = _push(client, {S.RESTING_HR: 92, S.SKIN_TEMP: 34.8},
                   symptoms={S.SYMPTOM_FEVER_CHILLS: 2})
    assessment = result["assessment"]
    assert AlertLevel(assessment["level"]).rank >= AlertLevel.YELLOW.rank, assessment
    assert result["as_of"].startswith("2027-05-20T15:30"), "assessed now, not at 10:00"
    signals = [r["signal"] for r in assessment["contributors"]]
    assert "resting_hr" in signals and "skin_temp" in signals
    text = live_demo.describe(result)
    assert text.startswith("AST-03: YELLOW") and "heart rate" in text.lower()


def test_hr_and_temp_alone_stay_green_with_starter_scorer(client):
    # Each vital adds at most 7.5 points; yellow needs 25. Why the stage script adds a symptom.
    assessment = _push(client, {S.RESTING_HR: 92, S.SKIN_TEMP: 34.8})["assessment"]
    assert assessment["score"] == pytest.approx(15.0)
    assert assessment["level"] == "green"


def test_cli_push_back_to_normal_clears_the_fever(client, monkeypatch):
    # Drive cmd_push through main(), with the HTTP calls routed to the in-process app.
    def post(url, body):
        response = client.post(url.removeprefix("http://test"), json=body)
        assert response.status_code == 200, response.text
        return response.json()

    clock = iter([NOW, NOW + timedelta(minutes=5)])

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(clock)

    monkeypatch.setattr(live_demo, "_post", post)
    monkeypatch.setattr(live_demo, "datetime", FakeDatetime)
    live_demo.main(["push", "--id", "AST-03", "--resting-hr", "92", "--skin-temp", "34.8",
                    "--fever", "2", "--api", "http://test"])
    assert client.get("/api/crew/AST-03/status").json()["assessment"]["level"] == "yellow"
    live_demo.main(["push", "--id", "AST-03", "--resting-hr", "63", "--skin-temp", "34.1",
                    "--api", "http://test"])
    assessment = client.get("/api/crew/AST-03/status").json()["assessment"]
    assert assessment["level"] == "green" and assessment["score"] == 0


def test_seeding_twice_replaces_instead_of_duplicating(pipeline):
    before = pipeline.store.counts()
    pipeline.ingest(live_demo.build_seed("AST-03", "Live", NORMALS, NOW))
    pipeline.ingest(live_demo.build_seed("AST-03", "Live", NORMALS, NOW + timedelta(hours=1)))
    assert pipeline.store.counts() == before
    assert [m.astronaut_id for m in pipeline.store.crew()] == ["AST-03"]


def test_builders_are_deterministic():
    assert live_demo.build_seed("AST-03", "Live", NORMALS, NOW) == \
        live_demo.build_seed("AST-03", "Live", NORMALS, NOW)
    records = live_demo.build_push("AST-03", {S.RESTING_HR: 95}, NOW)
    assert records == [{
        "observation_id": "AST-03-resting_hr-live-20270520T153000", "astronaut_id": "AST-03",
        "timestamp": "2027-05-20T15:30:00+00:00", "signal": "resting_hr", "value": 95,
        "source": "manual", "note": "live demo"}]


def test_night_stamps_before_six_end_yesterday():
    early = datetime(2027, 5, 20, 5, 0, tzinfo=timezone.utc)
    assert live_demo.night_stamps(early, 2) == [
        datetime(2027, 5, 18, 6, tzinfo=timezone.utc), datetime(2027, 5, 19, 6, tzinfo=timezone.utc)]


def test_from_csv_imports_a_watch_export(tmp_path, capsys):
    # B11's wearable_csv source exists now. A temporary config keeps the real database clean.
    database = tmp_path / "live.db"
    config = tmp_path / "live.toml"
    config.write_text(f'[storage]\ndatabase = "{database.as_posix()}"\n', encoding="utf-8")
    now = datetime.now(timezone.utc)
    export = tmp_path / "watch.csv"
    rows = [f"{night.isoformat()},{62 + i % 2},34.1,55,14,97,7.0"
            for i, night in enumerate(live_demo.night_stamps(now, 14))]
    export.write_text("date,resting_hr,skin_temp,hrv_rmssd,resp_rate,spo2,sleep_duration\n"
                      + "\n".join(rows) + "\n", encoding="utf-8")

    live_demo.main(["seed", "--id", "AST-03", "--from-csv", str(export), "--config", str(config)])

    assert "GREEN" in capsys.readouterr().out.upper()
    store = Store(str(database))
    readings = store.observations("AST-03")
    assert len(readings) == 14 * 6 and {o.source for o in readings} == {"wearable"}
    assert store.latest_assessment("AST-03").level is AlertLevel.GREEN
