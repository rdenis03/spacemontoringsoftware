"""M5: NASA DONKI space-weather source. Never touches the network."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request

import pytest

from orbit.core import create
from orbit.modules.space_weather import DonkiFetchError, flare_severity, storm_severity
from orbit.schema import EventType, Severity

FIXTURES = Path(__file__).parent / "fixtures" / "donki"
UTC = timezone.utc

# Real responses for 2025-10-16..2025-10-26 (tests/fixtures/donki/*.json).
REAL = {name: json.loads((FIXTURES / f"{name}.json").read_text()) for name in ("SEP", "GST", "CME")}

# Hand-written samples (not real responses): the FLR endpoint answered 404 when
# M5 was built, so these follow the SPEC's field names; the SEP sample shows
# one event listed once per instrument.
FLR_SAMPLE = [
    {"flrID": "2030-01-01T01:00:00-FLR-001", "beginTime": "2030-01-01T01:00Z",
     "peakTime": "2030-01-01T01:20Z", "endTime": "2030-01-01T01:45Z", "classType": "X12.1"},
    {"flrID": "2030-01-01T05:00:00-FLR-001", "beginTime": "2030-01-01T05:00Z",
     "peakTime": "2030-01-01T05:10Z", "endTime": None, "classType": "X1.4"},
    {"flrID": "2030-01-02T05:00:00-FLR-001", "beginTime": "2030-01-02T05:00Z",
     "peakTime": None, "endTime": None, "classType": "M3.2"},
    {"flrID": "2030-01-03T05:00:00-FLR-001", "beginTime": "2030-01-03T05:00Z",
     "peakTime": "2030-01-03T05:05Z", "endTime": "2030-01-03T05:30Z", "classType": "C4.0"},
]
SEP_SAMPLE = [
    {"sepID": "2030-02-01T03:10:00-SEP-001", "eventTime": "2030-02-01T03:10Z"},
    {"sepID": "2030-02-01T02:00:00-SEP-002", "eventTime": "2030-02-01T02:00Z"},
    {"sepID": "2030-02-01T02:00:00-SEP-001", "eventTime": "2030-02-01T02:00Z"},
    {"sepID": "2030-02-01T08:00:00-SEP-001", "eventTime": "2030-02-01T08:00Z"},   # exactly 6 h later
    {"sepID": "2030-02-01T08:01:00-SEP-001", "eventTime": "2030-02-01T08:01Z"},   # 6 h 1 min: new event
]


def donki(**options):
    return create("source", "donki", **options)


def write_cache(tmp_path, data):
    path = tmp_path / "donki_cache.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the network was touched")

    monkeypatch.setattr(request, "urlopen", refuse)


@pytest.fixture
def real_cache(tmp_path):
    return write_cache(tmp_path, {"SEP": REAL["SEP"], "GST": REAL["GST"], "CME": REAL["CME"]})


# ---- mapping of each type -------------------------------------------------------


def test_real_sep_and_gst_map_to_crew_wide_ground_events(real_cache, no_network):
    batch = donki(cache_path=str(real_cache)).read()
    assert batch.source_name == "donki" and batch.errors == ()
    storm, sep = batch.events
    assert storm.event_id == "donki-2025-10-18T18:00:00-GST-001"
    assert storm.external_id == "2025-10-18T18:00:00-GST-001"
    assert storm.event_type is EventType.GEOMAGNETIC_STORM
    assert storm.start == datetime(2025, 10, 18, 18, tzinfo=UTC)
    assert storm.end == storm.start + timedelta(hours=3)          # 1 Kp reading x 3 h
    assert storm.severity is Severity.LOW                          # max Kp 6.0
    assert storm.description == "NASA DONKI GST 2025-10-18T18:00Z, max Kp 6 (real event)"

    assert sep.event_id == "donki-2025-10-22T00:09:00-SEP-001"
    assert sep.event_type is EventType.SOLAR_PARTICLE_EVENT
    assert sep.end == sep.start + timedelta(hours=12)
    assert sep.severity is Severity.MODERATE
    assert sep.description == "NASA DONKI SEP 2025-10-22T00:09Z, 1 record (real event)"
    for event in batch.events:
        assert event.astronaut_id is None and event.source.value == "ground" and not event.simulated


def test_flare_mapping_from_hand_written_sample(tmp_path, no_network):
    cache = write_cache(tmp_path, {"FLR": FLR_SAMPLE, "SEP": [], "GST": []})
    events = donki(cache_path=str(cache), include_flr=True).read().events
    assert [e.event_type for e in events] == [EventType.SOLAR_FLARE] * 4
    assert [e.severity for e in events] == [Severity.EXTREME, Severity.HIGH, Severity.MODERATE, Severity.LOW]
    assert events[0].end == datetime(2030, 1, 1, 1, 45, tzinfo=UTC)   # endTime
    assert events[1].end == datetime(2030, 1, 1, 5, 10, tzinfo=UTC)   # no endTime: peakTime
    assert events[2].end is None                                       # neither
    assert events[0].description == "NASA DONKI FLR 2030-01-01T01:00Z, class X12.1 (real event)"


def test_duplicate_sep_records_within_6_hours_merge(tmp_path, no_network):
    cache = write_cache(tmp_path, {"SEP": SEP_SAMPLE, "GST": []})
    first, second = donki(cache_path=str(cache)).read().events
    assert first.event_id == "donki-2030-02-01T02:00:00-SEP-001"      # earliest record's sepID
    assert first.start == datetime(2030, 2, 1, 2, tzinfo=UTC)
    assert first.description == "NASA DONKI SEP 2030-02-01T02:00Z, 4 records (real event)"
    assert second.event_id == "donki-2030-02-01T08:01:00-SEP-001"
    assert second.description.endswith(", 1 record (real event)")


def test_flares_and_cmes_are_off_by_default(real_cache, no_network):
    types = {e.event_type for e in donki(cache_path=str(real_cache)).read().events}
    assert types == {EventType.GEOMAGNETIC_STORM, EventType.SOLAR_PARTICLE_EVENT}


def test_include_cme_adds_real_cmes(real_cache, no_network):
    events = donki(cache_path=str(real_cache), include_cme=True).read().events
    cmes = [e for e in events if e.event_type is EventType.CME]
    assert len(cmes) == len(REAL["CME"]) == 78
    assert cmes[0].event_id == "donki-2025-10-16T01:25:00-CME-001"
    assert all(e.severity is Severity.LOW and e.end is None for e in cmes)


def test_bad_records_become_row_errors(tmp_path, no_network):
    cache = write_cache(tmp_path, {"SEP": [{"sepID": "x"}], "GST": [{"gstID": "y", "startTime": "2025-10-18T18:00Z"}]})
    batch = donki(cache_path=str(cache)).read()
    assert batch.events == ()
    assert [str(e) for e in batch.errors] == [
        "row 1: donki_cache.json: SEP record 1: missing eventTime",
        "row 1: donki_cache.json: GST record 1: no Kp readings",
    ]


# ---- severity thresholds -----------------------------------------------------------


@pytest.mark.parametrize(("kp", "severity"), [
    (5.0, Severity.LOW), (6.67, Severity.LOW), (7.0, Severity.MODERATE), (7.67, Severity.MODERATE),
    (8.0, Severity.HIGH), (8.67, Severity.HIGH), (9.0, Severity.EXTREME),
])
def test_storm_severity(kp, severity):
    assert storm_severity(kp) is severity


@pytest.mark.parametrize(("cls", "severity"), [
    ("X10.0", Severity.EXTREME), ("X28", Severity.EXTREME), ("X9.9", Severity.HIGH), ("X1.0", Severity.HIGH),
    ("M9.9", Severity.MODERATE), ("M1.0", Severity.MODERATE), ("C3.1", Severity.LOW), ("B8", Severity.LOW),
])
def test_flare_severity(cls, severity):
    assert flare_severity(cls) is severity


def test_unknown_flare_class_is_an_error():
    with pytest.raises(ValueError, match="unknown flare class"):
        flare_severity("Z1.0")


# ---- time shift and window ------------------------------------------------------------


def test_mission_start_shifts_real_dates(real_cache, no_network):
    batch = donki(cache_path=str(real_cache), real_start="2025-10-16", real_end="2025-10-26",
                  mission_start="2027-03-14").read()
    storm, sep = batch.events
    assert storm.start == datetime(2027, 3, 16, 18, tzinfo=UTC)       # mission day 72
    assert storm.end == datetime(2027, 3, 16, 21, tzinfo=UTC)
    assert sep.start == datetime(2027, 3, 20, 0, 9, tzinfo=UTC)       # mission day 76
    assert storm.external_id == "2025-10-18T18:00:00-GST-001"          # the real ID is kept
    assert storm.description == "NASA DONKI GST 2025-10-18T18:00Z, max Kp 6 (real event, replayed)"


def test_real_window_filters_records(real_cache, no_network):
    events = donki(cache_path=str(real_cache), real_start="2025-10-20", real_end="2025-10-26").read().events
    assert [e.event_type for e in events] == [EventType.SOLAR_PARTICLE_EVENT]


def test_mission_start_needs_real_start():
    with pytest.raises(ValueError, match="mission_start needs real_start"):
        donki(mission_start="2027-03-14")


# ---- cache, network and errors ------------------------------------------------------


def test_cache_mode_never_touches_the_network(real_cache, no_network):
    assert donki(cache_path=str(real_cache), mode="cache").read().events


def test_missing_cache_gives_empty_batch_with_error(tmp_path, no_network):
    batch = donki(cache_path=str(tmp_path / "nope.json")).read()
    assert batch.events == () and len(batch.errors) == 1
    assert "DONKI cache not found" in batch.errors[0].message


def test_cache_without_an_endpoint_reports_it(tmp_path, no_network):
    batch = donki(cache_path=str(write_cache(tmp_path, {"SEP": REAL["SEP"]}))).read()
    assert len(batch.events) == 1
    assert [e.message for e in batch.errors] == ["donki_cache.json: no GST responses in the cache"]


def test_fetch_error_raises_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("NASA_API_KEY", "secret-test-key")

    def unreachable(url, timeout):
        raise urlerror.URLError("Name or service not known")

    monkeypatch.setattr(request, "urlopen", unreachable)
    source = donki(mode="fetch", cache_path=str(tmp_path / "c.json"),
                   real_start="2025-10-16", real_end="2025-10-26")
    with pytest.raises(DonkiFetchError, match="NASA DONKI SEP request for 2025-10-16..2025-10-26 failed") as info:
        source.read()
    assert "secret-test-key" not in str(info.value)
    assert not (tmp_path / "c.json").exists()


def test_fetch_http_error_names_the_status(tmp_path, monkeypatch):
    def not_found(url, timeout):
        raise urlerror.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(request, "urlopen", not_found)
    source = donki(mode="fetch", cache_path=str(tmp_path / "c.json"), include_flr=True,
                   real_start="2025-10-16", real_end="2025-10-26")
    with pytest.raises(DonkiFetchError, match="NASA DONKI FLR request .* HTTP 404"):
        source.read()


class _Response:
    def __init__(self, body):
        self.body = body.encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_splits_into_60_day_requests_and_writes_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("NASA_API_KEY", raising=False)
    urls = []

    def fake(url, timeout):
        urls.append(url)
        if "/SEP?" in url and "startDate=2025-10-17" in url:
            return _Response(json.dumps(REAL["SEP"]))
        if "/GST?" in url and "startDate=2025-10-17" in url:
            return _Response(json.dumps(REAL["GST"]))
        return _Response("")  # DONKI sends an empty body when nothing happened

    monkeypatch.setattr(request, "urlopen", fake)
    cache = tmp_path / "out" / "donki_cache.json"
    batch = donki(mode="fetch", cache_path=str(cache), real_start="2025-08-18", real_end="2025-10-26").read()
    # 70 days -> 2025-08-18..2025-10-16 (60 days) and 2025-10-17..2025-10-26, per endpoint.
    assert len(urls) == 4
    assert "startDate=2025-08-18&endDate=2025-10-16" in urls[0]
    assert "startDate=2025-10-17&endDate=2025-10-26" in urls[1]
    assert all("api_key=DEMO_KEY" in u for u in urls)
    assert len(batch.events) == 2
    written = json.loads(cache.read_text())
    assert written["SEP"] == REAL["SEP"] and written["GST"] == REAL["GST"]
    assert "api_key" not in cache.read_text() and "DEMO_KEY" not in cache.read_text()

    # The written cache replays offline to the same events.
    monkeypatch.setattr(request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    again = donki(cache_path=str(cache), real_start="2025-08-18", real_end="2025-10-26").read()
    assert again.events == batch.events


def test_example_cache_is_the_recorded_responses():
    root = Path(__file__).resolve().parents[1]
    cache = json.loads((root / "examples" / "donki_cache.json").read_text())
    assert cache["SEP"] == REAL["SEP"] and cache["GST"] == REAL["GST"]


def test_replayed_events_reach_the_scorer(ran_pipeline):
    """In the demo, the real storm and SEP land on days 72 and 76 and appear as reasons."""
    events = {e.event_id for e in ran_pipeline.store.events()}
    assert {"donki-2025-10-18T18:00:00-GST-001", "donki-2025-10-22T00:09:00-SEP-001"} <= events
    day_76 = datetime(2027, 3, 20, 10, tzinfo=UTC)
    reasons = {a.assessed_at: a for a in ran_pipeline.store.assessments("AST-01")}[day_76].contributors
    labels = {c.event_id: c.label for c in reasons if c.event_id}
    assert labels == {"donki-2025-10-22T00:09:00-SEP-001": "Solar particle event today",
                      "donki-2025-10-18T18:00:00-GST-001": "Geomagnetic storm 3 days ago"}


def test_demo_story_unchanged_with_real_events(ran_pipeline):
    scores = {a.assessed_at: a for a in ran_pipeline.store.assessments("AST-01")}
    day_89 = datetime(2027, 4, 2, 10, tzinfo=UTC)
    assert scores[day_89].score == 27.7 and scores[day_89 + timedelta(days=1)].score == 70.2
    for aid in ("AST-01", "AST-02"):
        yellow_or_worse = [a.assessed_at for a in ran_pipeline.store.assessments(aid) if a.score >= 25]
        assert yellow_or_worse == ([day_89, day_89 + timedelta(days=1)] if aid == "AST-01" else [])


# ---- review fixes: key redaction and per-record checks -----------------------------

DUMMY_KEY = "dummy-key-8f3a"


@pytest.mark.parametrize("make_error", [
    lambda url: urlerror.URLError(f"failed GET {url}"),
    lambda url: urlerror.HTTPError(url, 403, f"Forbidden for {url}", None, None),
])
def test_fetch_errors_never_show_the_key(tmp_path, monkeypatch, make_error):
    monkeypatch.setenv("NASA_API_KEY", DUMMY_KEY)

    def fail(url, timeout):
        # The reason quotes the request URL, the key and an unrelated api_key=.
        raise make_error(f"{url} (retry with api_key=OTHER-KEY-42)")

    monkeypatch.setattr(request, "urlopen", fail)
    source = donki(mode="fetch", cache_path=str(tmp_path / "c.json"),
                   real_start="2025-10-16", real_end="2025-10-26")
    with pytest.raises(DonkiFetchError) as info:
        source.read()
    message = str(info.value)
    assert DUMMY_KEY not in message and "OTHER-KEY-42" not in message
    assert "api_key=REDACTED" in message and message.startswith("NASA DONKI SEP request")


def test_each_bad_record_is_isolated(tmp_path, no_network):
    good_sep = {"sepID": "2025-10-22T00:09:00-SEP-001", "eventTime": "2025-10-22T00:09Z"}
    good_gst = {"gstID": "2025-10-18T18:00:00-GST-001", "startTime": "2025-10-18T18:00Z",
                "allKpIndex": [{"kpIndex": 6}]}
    cache = write_cache(tmp_path, {
        "SEP": [
            {"sepID": "2025-10-01T00:00:00-SEP-001", "eventTime": 123},
            {"sepID": 42, "eventTime": "2025-10-02T00:00Z"},
            {"sepID": "2025-10-03T00:00:00-SEP-001", "eventTime": "not a time"},
            good_sep,
        ],
        "GST": [
            {"startTime": "2025-10-05T00:00Z", "allKpIndex": [{"kpIndex": 7}]},
            {"gstID": "2025-10-06T00:00:00-GST-001", "startTime": "2025-10-06T00:00Z", "allKpIndex": []},
            {"gstID": "2025-10-07T00:00:00-GST-001", "startTime": "2025-10-07T00:00Z",
             "allKpIndex": [{"kpIndex": "7.0"}]},
            good_gst,
        ],
    })
    batch = donki(cache_path=str(cache)).read()
    assert {e.event_id for e in batch.events} == {
        "donki-2025-10-22T00:09:00-SEP-001", "donki-2025-10-18T18:00:00-GST-001"}
    assert [str(e) for e in batch.errors] == [
        "row 1: donki_cache.json: SEP record 1: eventTime must be text, got int 123",
        "row 2: donki_cache.json: SEP record 2: sepID must be text, got int 42",
        "row 3: donki_cache.json: SEP record 3: eventTime is not an ISO time: 'not a time'",
        "row 1: donki_cache.json: GST record 1: missing gstID",
        "row 2: donki_cache.json: GST record 2: no Kp readings",
        "row 3: donki_cache.json: GST record 3: Kp reading 1 is not a number: '7.0'",
    ]


def test_a_record_the_schema_rejects_does_not_stop_the_batch(tmp_path, no_network):
    too_long = "x" * 70  # event_id allows 64 characters
    cache = write_cache(tmp_path, {"SEP": [{"sepID": too_long, "eventTime": "2025-10-21T00:00Z"},
                                           {"sepID": "ok-SEP", "eventTime": "2025-10-23T00:00Z"}],
                                   "GST": []})
    batch = donki(cache_path=str(cache)).read()
    assert [e.event_id for e in batch.events] == ["donki-ok-SEP"]
    assert len(batch.errors) == 1 and batch.errors[0].message.startswith("donki_cache.json: SEP record 1:")
