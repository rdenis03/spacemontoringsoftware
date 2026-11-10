"""B11 (M3): wearable CSV import. One small hand-made fixture per case."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbit.core import Pipeline, Store, available, create, load_settings
from orbit.modules.ingestion import WearableCsvSource, normalize_records
from orbit.schema import Quality, SignalType, Source

from conftest import CONFIG

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"
S = SignalType


def read(name, **options):
    options.setdefault("astronaut_id", "AST-01")
    return create("source", "wearable_csv", path=str(FIXTURES / name), **options).read()


def values(batch, signal):
    """{UTC day of month: value} for one signal."""
    return {o.timestamp.day: o.value for o in batch.observations if o.signal is signal}


def utc(day, hour=6, minute=0):
    return datetime(2027, 3, day, hour, minute, tzinfo=timezone.utc)


# ---- registration and the empty source -------------------------------------------


def test_registered_and_empty_without_options():
    assert "wearable_csv" in available("source")
    batch = create("source", "wearable_csv").read()
    assert batch.source_name == "wearable_csv" and not batch.observations
    [error] = batch.errors
    assert error.row == 0 and "path" in error.message


def test_missing_file_is_an_error_not_a_crash(tmp_path):
    batch = WearableCsvSource(path=str(tmp_path / "nope.csv"), astronaut_id="AST-01").read()
    assert batch.source_name == "wearable_csv:nope.csv" and not batch.observations
    assert "file not found" in batch.errors[0].message


# ---- units -----------------------------------------------------------------------


def test_fahrenheit_becomes_celsius():
    batch = read("fahrenheit.csv", columns={"Resting HR": "resting_hr", "Skin Temp": "skin_temp"},
                 units={"skin_temp": "degF"}, device_id="ring-7")
    assert batch.source_name == "wearable_csv:fahrenheit.csv" and not batch.errors
    assert values(batch, S.SKIN_TEMP) == pytest.approx({14: 34.5, 15: 34.3889, 16: 35.0})
    assert values(batch, S.RESTING_HR) == {14: 52, 15: 53}, "the empty cell is skipped silently"
    for obs in batch.observations:
        assert obs.source is Source.WEARABLE and obs.quality is Quality.GOOD
        assert obs.device_id == "ring-7" and obs.astronaut_id == "AST-01"
        assert obs.unit == obs.spec.unit and not obs.simulated
    first = min(batch.observations, key=lambda o: (o.timestamp, o.signal.value))
    assert first.observation_id == "AST-01-resting_hr-20270314T060000"


def test_fractions_and_minutes_are_converted():
    batch = read("fraction.csv",
                 columns={"SpO2": "spo2", "Sleep Efficiency": "sleep_efficiency",
                          "Sleep Minutes": "sleep_duration"},
                 units={"spo2": "fraction", "sleep_efficiency": "fraction",
                        "sleep_duration": "min"})
    assert not batch.errors
    assert values(batch, S.SPO2) == pytest.approx({14: 97.0, 15: 96.5})
    assert values(batch, S.SLEEP_EFFICIENCY) == pytest.approx({14: 91.0, 15: 88.5})
    assert values(batch, S.SLEEP_DURATION) == pytest.approx({14: 7.2, 15: 6.75})


def test_seconds_become_hours():
    result = normalize_records([{"date": "2027-03-14T06:00:00Z", "sleep_duration": "25200"}],
                               astronaut_id="AST-01", units={"sleep_duration": "s"})
    assert [o.value for o in result.valid] == [7.0] and result.ok


def test_unknown_unit_is_an_error_never_a_guess():
    batch = read("unknown_unit.csv", columns={"Skin Temp": "skin_temp"},
                 units={"skin_temp": "kelvin"})
    [error] = batch.errors
    assert error.row == 1 and "unknown unit 'kelvin'" in error.message
    assert "skin_temp" in error.message and "degF" in error.message
    assert values(batch, S.SKIN_TEMP) == {}, "the column is not read"
    assert values(batch, S.RESTING_HR) == {14: 52, 15: 53}, "other columns still import"


def test_fraction_without_a_unit_is_flagged_not_converted():
    batch = read("fraction.csv", columns={"SpO2": "spo2"})
    assert not batch.errors
    assert {o.quality for o in batch.observations} == {Quality.BAD}
    assert all("raw value 0.9" in o.note for o in batch.observations)


def test_deviation_column_is_rejected():
    batch = read("deviation.csv", columns={"Temperature Deviation": "skin_temp",
                                           "Resting HR": "resting_hr"})
    [error] = batch.errors
    assert error.row == 1 and "Temperature Deviation" in error.message
    assert "relative deviation" in error.message
    assert values(batch, S.SKIN_TEMP) == {}
    assert values(batch, S.RESTING_HR) == {14: 52, 15: 53}

    as_unit = read("deviation.csv", columns={"Resting HR": "skin_temp"},
                   units={"skin_temp": "deviation"})
    assert "relative deviation" in as_unit.errors[0].message and not as_unit.observations


# ---- timestamps ------------------------------------------------------------------


def test_naive_timestamps_get_the_timezone():
    batch = read("naive.csv", timezone="Europe/Bucharest")  # UTC+2 in mid-March
    assert not batch.errors
    times = sorted({o.timestamp for o in batch.observations})
    assert times == [utc(14, 4, 30), utc(15, 4, 0)], "a date alone is 06:00 local"
    assert values(batch, S.HRV_RMSSD) == {14: 61, 15: 58}, "signal-named columns need no mapping"


def test_naive_timestamps_without_timezone_are_row_errors():
    batch = read("naive.csv")
    assert not batch.observations
    assert [e.row for e in batch.errors] == [2, 3]
    assert all("no timezone" in e.message and "timezone" in e.message for e in batch.errors)


def test_bad_timezone_and_bad_timestamp():
    batch = read("naive.csv", timezone="Mars/Olympus_Mons")
    assert not batch.observations and "unknown timezone" in batch.errors[0].message

    result = normalize_records([{"date": "14/03/2027", "resting_hr": "52"}],
                               astronaut_id="AST-01", timezone="UTC")
    assert not result.valid
    assert result.errors[0].row == 1 and "not an ISO date" in result.errors[0].message

    missing = read("naive.csv", timestamp_column="night")
    assert missing.errors[0].row == 1 and "'night' is not in the file" in missing.errors[0].message


# ---- quality ---------------------------------------------------------------------


def test_out_of_range_is_kept_as_bad_and_low_wear_as_suspect():
    batch = read("out_of_range.csv", suspect_column="wear_flag")
    by_day = {(o.timestamp.day, o.signal): o for o in batch.observations}

    bad = by_day[(15, S.RESTING_HR)]
    assert bad.value == 420 and bad.quality is Quality.BAD and not bad.is_usable
    assert "raw value 420 bpm" in bad.note
    assert by_day[(15, S.SPO2)].quality is Quality.GOOD, "only the absurd cell is flagged"

    assert by_day[(16, S.RESTING_HR)].quality is Quality.SUSPECT
    assert by_day[(16, S.SPO2)].quality is Quality.SUSPECT
    assert "wear_flag" in by_day[(16, S.SPO2)].note
    assert by_day[(14, S.RESTING_HR)].quality is Quality.GOOD

    [error] = batch.errors
    assert error.row == 5 and "'abc' is not a number" in error.message
    assert (17, S.RESTING_HR) not in by_day and by_day[(17, S.SPO2)].value == 97


def test_duplicate_rows_keep_the_last():
    batch = read("duplicate.csv", astronaut_id=None)
    assert not batch.errors
    hr = {o.astronaut_id: o.value for o in batch.observations if o.signal is S.RESTING_HR}
    assert hr == {"AST-01": 54, "AST-02": 60}, "the later row wins; the astronaut column is used"
    resp = {o.astronaut_id: o.value for o in batch.observations if o.signal is S.RESP_RATE}
    assert resp == {"AST-01": 14.2, "AST-02": 15.1}, "an empty cell does not erase a value"
    assert len(batch.observations) == 4


def test_no_astronaut_is_a_row_error():
    batch = read("fahrenheit.csv", astronaut_id=None, columns={"Resting HR": "resting_hr"})
    assert not batch.observations
    assert [e.row for e in batch.errors] == [2, 3], "row 4 has nothing to read"
    assert "astronaut" in batch.errors[0].message


# ---- column mapping ----------------------------------------------------------------


def test_column_mapping_problems_are_reported_on_the_header_row():
    batch = read("fahrenheit.csv", columns={"Heart": "resting_hr", "Skin Temp": "mood",
                                            "resting hr": "resting_hr"})
    messages = [e.message for e in batch.errors]
    assert all(e.row == 1 for e in batch.errors)
    assert any("'Heart' is not in the file" in m for m in messages)
    assert any("'mood' is not a wearable signal" in m for m in messages)
    assert values(batch, S.RESTING_HR) == {14: 52, 15: 53}, "headers match ignoring case"


# ---- end to end ------------------------------------------------------------------


def test_import_goes_through_the_pipeline():
    pipeline = Pipeline.from_settings(load_settings(CONFIG), store=Store(":memory:"))
    for choice in load_settings(CONFIG).sources:
        pipeline.ingest(create("source", choice.use, **choice.options))
    before = pipeline.store.counts()["observations"]
    source = create("source", "wearable_csv", path=str(FIXTURES / "duplicate.csv"))
    report = pipeline.ingest(source)
    assert report.observations == 4 and not report.errors
    assert pipeline.ingest(source).observations == 4
    assert pipeline.store.counts()["observations"] == before + 4, "importing again replaces"

    unknown = pipeline.ingest(create("source", "wearable_csv", astronaut_id="AST-77",
                                     path=str(FIXTURES / "naive.csv"), timezone="UTC"))
    assert unknown.observations == 0 and "unknown astronaut" in unknown.errors[0].message
