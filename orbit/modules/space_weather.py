"""NASA DONKI space-weather feed (slot ``source``, team module M5).

Turns real space-weather events from NASA's DONKI database (Space Weather
Database Of Notifications, Knowledge, Information) into crew-wide
``ContextEvent`` records, so solar storms count as immune stressors.

On a real mission the ground fetches DONKI and uplinks the result; the
spacecraft only ever reads a local cache. This source models exactly that:

    mode = "fetch"   (ground)   download from api.nasa.gov, write cache_path, return events
    mode = "cache"   (onboard)  read cache_path only; never touches the network

Options (all have defaults):

    mode           "cache"                 "cache" or "fetch"
    cache_path     "data/donki_cache.json" raw DONKI responses keyed by endpoint
                                           ("SEP", "GST", ...) plus a "_meta" block
    real_start     None                    first real date (YYYY-MM-DD) to fetch or replay;
                                           required in fetch mode
    real_end       None                    last real date, inclusive; required in fetch mode
    mission_start  None                    if set, shift every event so real_start lands on
                                           this date: a simulated 2027 mission replays real
                                           solar history. Needs real_start.
    include_cme    False                   also read CMEs (on their own they are noisy;
                                           their effects show up as SEP/GST)
    include_flr    False                   also read solar flares (see "Flares" below)
    base_url       "https://api.nasa.gov/DONKI"
    timeout_s      30                      per request, fetch mode only

The API key comes from the ``NASA_API_KEY`` environment variable, falling back
to ``DEMO_KEY`` (heavily rate-limited). It is never written to the cache or to
error messages.

Mapping (every event: ``astronaut_id=None`` = whole crew, ``source="ground"``,
``external_id`` = the DONKI ID, ``event_id = "donki-<DONKI ID>"`` so re-ingesting
replaces instead of duplicating, ``simulated=False``):

    DONKI  EventType             start       end (assumption)               severity
    -----  --------------------  ----------  -----------------------------  ------------------------------
    SEP    solar_particle_event  eventTime   start + 12 h                   moderate
    GST    geomagnetic_storm     startTime   start + 3 h x number of Kp     max Kp 9 extreme, 8 high,
                                             readings (one Kp per 3 h)      7 moderate, below 7 low
    FLR    solar_flare           beginTime   endTime (else peakTime,        X10+ extreme, X high,
                                             else none)                     M moderate, C/B/A low
    CME    cme                   startTime   none                           low (assumption; SPEC is silent)

Kp values come in thirds (6.67 means "7-"); they are rounded down to the whole
number before the thresholds above.

Facts found on live responses (2026-11-15):

- One request may cover at most 60 days. Fetch mode splits longer windows.
- DONKI lists one solar particle event once per instrument or energy channel,
  so a single event can appear as up to ~9 SEP records within a few hours.
  Records whose ``eventTime`` lies within 6 hours of the first record of a
  group are merged into one event, which keeps the earliest record's
  ``sepID``; the description gives the number of merged records.
- Field names were checked on live SEP, GST and CME responses. The FLR
  endpoint answered HTTP 404 for every date tried, so the flare field names
  (``flrID``, ``beginTime``, ``peakTime``, ``endTime``, ``classType``) come
  from the SPEC and are not checked against a live response. That is why
  ``include_flr`` is off by default.

Errors: a missing or unreadable cache gives an empty batch with a ``RowError``
(onboard must keep running). Each record is checked on its own: IDs and times
must be non-empty strings (times in ISO form), Kp values finite numbers; a bad
record becomes a ``RowError`` naming the endpoint and its position, and the
rest of the batch still loads. A network or HTTP error in fetch mode raises
``DonkiFetchError`` with a clear message; the API key and any ``api_key=...``
are replaced with ``REDACTED`` in its text.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import parse, request

from orbit.core.interfaces import SourceBatch
from orbit.core.registry import register
from orbit.schema import ContextEvent, EventType, RowError, Severity

MAX_DAYS_PER_REQUEST = 60
SEP_MERGE_WINDOW = timedelta(hours=6)
SEP_DURATION = timedelta(hours=12)
KP_INTERVAL = timedelta(hours=3)
SOURCE_LABEL = "NASA DONKI"


class DonkiFetchError(RuntimeError):
    """Downloading from DONKI failed (fetch mode only)."""


# ---- small helpers -------------------------------------------------------------


def _parse_time(value: str) -> datetime:
    """DONKI times look like '2025-10-18T18:00Z'; return aware UTC."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _parse_date(value: str | date | None, option: str) -> date | None:
    if value is None or isinstance(value, date):
        return value if not isinstance(value, datetime) else value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"donki: {option} must be a date like 2025-10-16, got {value!r}") from exc


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%MZ")


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _text(record: dict, field: str) -> str:
    """A required, non-empty string field."""
    value = record.get(field)
    if value is None or value == "":
        raise ValueError(f"missing {field}")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text, got {type(value).__name__} {value!r}")
    return value


def _time(record: dict, field: str) -> datetime:
    """A required ISO time string field, as aware UTC."""
    text = _text(record, field)
    try:
        return _parse_time(text)
    except ValueError:
        raise ValueError(f"{field} is not an ISO time: {text!r}") from None


def _kp_readings(record: dict) -> list[float]:
    """Every Kp value of a storm; each must be a finite number."""
    entries = record.get("allKpIndex")
    if not isinstance(entries, list) or not entries:
        raise ValueError("no Kp readings")
    readings = []
    for n, entry in enumerate(entries, start=1):
        kp = entry.get("kpIndex") if isinstance(entry, dict) else None
        if isinstance(kp, bool) or not isinstance(kp, (int, float)) or not math.isfinite(kp):
            raise ValueError(f"Kp reading {n} is not a number: {kp!r}")
        readings.append(float(kp))
    return readings


_KEY_IN_TEXT = re.compile(r"api_key=[^&\s'\"<>]*", re.IGNORECASE)


def redact(text: str, key: str | None) -> str:
    """Remove the API key from text: the key itself and any 'api_key=...'."""
    if key:
        text = text.replace(key, "REDACTED")
    return _KEY_IN_TEXT.sub("api_key=REDACTED", text)


def flare_severity(class_type: str) -> Severity:
    """'X12.3' -> extreme, 'X1.0' -> high, 'M5' -> moderate, 'C2' / 'B9' / 'A1' -> low."""
    match = re.fullmatch(r"\s*([ABCMX])\s*(\d+(?:\.\d+)?)?\s*", class_type or "", re.IGNORECASE)
    if not match:
        raise ValueError(f"unknown flare class {class_type!r}")
    letter = match.group(1).upper()
    magnitude = float(match.group(2) or 1.0)
    if letter == "X":
        return Severity.EXTREME if magnitude >= 10 else Severity.HIGH
    if letter == "M":
        return Severity.MODERATE
    return Severity.LOW


def storm_severity(max_kp: float) -> Severity:
    """Max Kp 9 extreme, 8 high, 7 moderate, below 7 low (thirds round down)."""
    kp = math.floor(max_kp + 1e-9)
    if kp >= 9:
        return Severity.EXTREME
    if kp >= 8:
        return Severity.HIGH
    if kp >= 7:
        return Severity.MODERATE
    return Severity.LOW


# ---- the source ----------------------------------------------------------------


@register("source", "donki")
class DonkiSource:
    def __init__(
        self,
        mode: str = "cache",
        cache_path: str = "data/donki_cache.json",
        real_start: str | None = None,
        real_end: str | None = None,
        mission_start: str | None = None,
        include_cme: bool = False,
        include_flr: bool = False,
        base_url: str = "https://api.nasa.gov/DONKI",
        timeout_s: float = 30.0,
    ):
        if mode not in ("cache", "fetch"):
            raise ValueError(f"donki: mode must be 'cache' or 'fetch', got {mode!r}")
        self.mode = mode
        self.cache_path = Path(cache_path)
        self.real_start = _parse_date(real_start, "real_start")
        self.real_end = _parse_date(real_end, "real_end")
        self.mission_start = _parse_date(mission_start, "mission_start")
        if self.mission_start is not None and self.real_start is None:
            raise ValueError("donki: mission_start needs real_start (the real date to replay from)")
        if self.real_start and self.real_end and self.real_end < self.real_start:
            raise ValueError("donki: real_end is before real_start")
        self.include_cme = include_cme
        self.include_flr = include_flr
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    # -- public ------------------------------------------------------------

    @property
    def endpoints(self) -> tuple[str, ...]:
        names = ["SEP", "GST"]
        if self.include_flr:
            names.insert(0, "FLR")
        if self.include_cme:
            names.append("CME")
        return tuple(names)

    @property
    def shift(self) -> timedelta:
        """How far real dates move forward to land in the mission."""
        if self.mission_start is None or self.real_start is None:
            return timedelta(0)
        return _midnight(self.mission_start) - _midnight(self.real_start)

    def read(self) -> SourceBatch:
        if self.mode == "fetch":
            responses = self.fetch()
            self._write_cache(responses)
        else:
            responses, error = self._read_cache()
            if error is not None:
                return SourceBatch(source_name="donki", errors=(error,))
        events, errors = self.to_events(responses)
        return SourceBatch(source_name="donki", events=tuple(events), errors=tuple(errors))

    def fetch(self) -> dict[str, list]:
        """Download every endpoint for [real_start, real_end] in pieces of at most 60 days."""
        if self.real_start is None or self.real_end is None:
            raise ValueError("donki: fetch mode needs real_start and real_end")
        key = os.environ.get("NASA_API_KEY") or "DEMO_KEY"
        responses: dict[str, list] = {}
        for endpoint in self.endpoints:
            records: list = []
            for start, end in self._chunks():
                records += self._get(endpoint, start, end, key)
            responses[endpoint] = records
        return responses

    def to_events(self, responses: dict[str, list]) -> tuple[list[ContextEvent], list[RowError]]:
        """Map raw DONKI records (as returned by the API) to ContextEvents."""
        events: list[ContextEvent] = []
        errors: list[RowError] = []
        mappers: dict[str, Callable] = {
            "FLR": self._map_flr, "SEP": self._map_sep, "GST": self._map_gst, "CME": self._map_cme,
        }
        for endpoint in self.endpoints:
            records = responses.get(endpoint)
            if records is None:
                errors.append(RowError(0, f"{self._where()}: no {endpoint} responses in the cache"))
                continue
            if not isinstance(records, list):
                errors.append(RowError(0, f"{self._where()}: {endpoint} is not a list of records"))
                continue
            new, bad = mappers[endpoint](records)
            events += new
            errors += bad
        events.sort(key=lambda e: (e.start, e.event_id))
        return events, errors

    # -- mapping -----------------------------------------------------------

    def _in_window(self, moment: datetime) -> bool:
        day = moment.date()
        if self.real_start and day < self.real_start:
            return False
        return not (self.real_end and day > self.real_end)

    def _event(self, *, external_id: str, event_type: EventType, start: datetime,
               end: datetime | None, severity: Severity, what: str) -> ContextEvent:
        replayed = ", replayed" if self.shift else ""
        return ContextEvent(
            event_id=f"donki-{external_id}",
            event_type=event_type,
            start=start + self.shift,
            end=end + self.shift if end is not None else None,
            severity=severity,
            astronaut_id=None,
            source="ground",
            external_id=external_id,
            description=f"{SOURCE_LABEL} {what} (real event{replayed})",
            simulated=False,
        )

    def _row_error(self, endpoint: str, position: int, exc: Exception) -> RowError:
        return RowError(position, f"{self._where()}: {endpoint} record {position}: {exc}")

    def _records(self, endpoint: str, records: list, id_field: str, time_field: str,
                 extra: Callable[[dict, datetime], object] = lambda record, start: None):
        """Check each record on its own. Returns (position, DONKI ID, real start, extra)
        for the good records inside the real window, and one RowError per bad record."""
        good, errors = [], []
        for i, record in enumerate(records, start=1):
            try:
                if not isinstance(record, dict):
                    raise ValueError(f"expected an object, got {type(record).__name__}")
                external_id = _text(record, id_field)
                start = _time(record, time_field)
                more = extra(record, start)
            except (ValueError, TypeError) as exc:
                errors.append(self._row_error(endpoint, i, exc))
                continue
            if self._in_window(start):
                good.append((i, external_id, start, more))
        return good, errors

    def _build(self, endpoint: str, items, make: Callable[..., ContextEvent]):
        """Build one event per item; a record the schema rejects becomes a RowError."""
        events, errors = [], []
        for position, *args in items:
            try:
                events.append(make(*args))
            except (ValueError, TypeError) as exc:  # pydantic's ValidationError is a ValueError
                errors.append(self._row_error(endpoint, position, exc))
        return events, errors

    def _map_sep(self, records: list):
        good, errors = self._records("SEP", records, "sepID", "eventTime")
        good.sort(key=lambda item: (item[2], item[1]))
        groups: list[list] = []
        for item in good:
            if groups and item[2] - groups[-1][0][2] <= SEP_MERGE_WINDOW:
                groups[-1].append(item)
            else:
                groups.append([item])

        def make(sep_id: str, start: datetime, count: int) -> ContextEvent:
            what = f"SEP {_stamp(start)}, {count} record{'s' if count != 1 else ''}"
            return self._event(external_id=sep_id, event_type=EventType.SOLAR_PARTICLE_EVENT,
                               start=start, end=start + SEP_DURATION, severity=Severity.MODERATE, what=what)

        items = [(g[0][0], g[0][1], g[0][2], len(g)) for g in groups]
        events, bad = self._build("SEP", items, make)
        return events, errors + bad

    def _map_gst(self, records: list):
        good, errors = self._records("GST", records, "gstID", "startTime",
                                     extra=lambda record, start: _kp_readings(record))

        def make(gst_id: str, start: datetime, readings: list[float]) -> ContextEvent:
            max_kp = max(readings)
            return self._event(external_id=gst_id, event_type=EventType.GEOMAGNETIC_STORM,
                               start=start, end=start + KP_INTERVAL * len(readings),
                               severity=storm_severity(max_kp), what=f"GST {_stamp(start)}, max Kp {max_kp:g}")

        events, bad = self._build("GST", good, make)
        return events, errors + bad

    def _map_flr(self, records: list):
        def extra(record: dict, start: datetime):
            class_type = _text(record, "classType")
            severity = flare_severity(class_type)
            end = None
            for field in ("endTime", "peakTime"):  # endTime, else peakTime, else none
                if record.get(field) not in (None, ""):
                    end = _time(record, field)
                    break
            if end is not None and end < start:
                end = None
            return class_type, severity, end

        good, errors = self._records("FLR", records, "flrID", "beginTime", extra=extra)

        def make(flr_id: str, start: datetime, info) -> ContextEvent:
            class_type, severity, end = info
            return self._event(external_id=flr_id, event_type=EventType.SOLAR_FLARE, start=start, end=end,
                               severity=severity, what=f"FLR {_stamp(start)}, class {class_type}")

        events, bad = self._build("FLR", good, make)
        return events, errors + bad

    def _map_cme(self, records: list):
        good, errors = self._records("CME", records, "activityID", "startTime")

        def make(cme_id: str, start: datetime, _unused) -> ContextEvent:
            return self._event(external_id=cme_id, event_type=EventType.CME, start=start,
                               end=None, severity=Severity.LOW, what=f"CME {_stamp(start)}")

        events, bad = self._build("CME", good, make)
        return events, errors + bad

    # -- cache and network -------------------------------------------------

    def _where(self) -> str:
        return self.cache_path.name

    def _read_cache(self) -> tuple[dict, RowError | None]:
        if not self.cache_path.is_file():
            return {}, RowError(0, f"{self.cache_path}: DONKI cache not found (run once with mode = \"fetch\" on the ground)")
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {}, RowError(0, f"{self.cache_path}: cannot read DONKI cache: {exc}")
        if not isinstance(data, dict):
            return {}, RowError(0, f"{self.cache_path}: DONKI cache must be a JSON object keyed by endpoint")
        return data, None

    def _write_cache(self, responses: dict[str, list]) -> None:
        document = {
            "_meta": {
                "source": "NASA DONKI via https://api.nasa.gov/",
                "real_start": self.real_start.isoformat() if self.real_start else None,
                "real_end": self.real_end.isoformat() if self.real_end else None,
                "fetched_at": _stamp(datetime.now(timezone.utc)),
                "endpoints": list(responses),
            },
            **responses,
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")

    def _chunks(self):
        start = self.real_start
        while start <= self.real_end:
            end = min(start + timedelta(days=MAX_DAYS_PER_REQUEST - 1), self.real_end)
            yield start, end
            start = end + timedelta(days=1)

    def _get(self, endpoint: str, start: date, end: date, key: str) -> list:
        query = parse.urlencode({"startDate": start.isoformat(), "endDate": end.isoformat(), "api_key": key})
        url = f"{self.base_url}/{endpoint}?{query}"
        what = f"NASA DONKI {endpoint} request for {start}..{end}"
        try:
            with request.urlopen(url, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8")
        except urlerror.HTTPError as exc:
            reason = redact(str(exc.reason), key)
            raise DonkiFetchError(f"{what} failed: HTTP {exc.code} {reason}") from None
        except (urlerror.URLError, OSError) as exc:
            reason = redact(str(getattr(exc, "reason", exc)), key)
            raise DonkiFetchError(f"{what} failed: cannot reach {self.base_url} ({reason})") from None
        if not body.strip():
            return []  # DONKI answers an empty body when there are no events
        try:
            data = json.loads(body)
        except ValueError:
            raise DonkiFetchError(f"{what} returned something that is not JSON") from None
        if not isinstance(data, list):
            raise DonkiFetchError(f"{what} returned {type(data).__name__}, expected a list")
        return data
