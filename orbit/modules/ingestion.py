"""Wearable CSV import (slot ``source``, registered as ``wearable_csv``): M3, task B11.

Loads a real watch or ring export safely. Vendors name columns their own way,
use their own units and often leave the timezone out, so this source maps the
columns to ORBIT signals, converts the units, attaches a timezone, keeps
doubtful data with a quality flag instead of dropping it, and reports every
problem with its row number. Nothing is guessed: what cannot be read safely
becomes a ``RowError``.

The file is "wide": one row per night, one column per signal::

    date,Resting HR,Skin Temp,SpO2
    2027-03-14,52,94.1,0.97

Options (all defaulted):

    path              None     the CSV file; without it ``read()`` returns an empty
                               batch with one error
    astronaut_id      None     used for rows without an ``astronaut_id`` column value
    timestamp_column  "date"   column with the date or time of the reading
    timezone          None     IANA name (e.g. "Europe/Bucharest") applied to
                               timestamps that carry no timezone; required for those
    columns           {}       vendor column -> signal, e.g. {"Resting HR" = "resting_hr"}
    units             {}       signal -> vendor unit, e.g. {skin_temp = "degF"}
    device_id         None     stored on every reading
    suspect_column    None     vendor flag column (e.g. low wear time); a row where
                               it is 1, true, yes, y or low is stored as ``suspect``

Columns. A column named exactly like a signal (``resting_hr``) is read without
being listed. ``columns`` adds the vendor's names; they match the header
exactly, or ignoring case and outer spaces. Only wearable signals are accepted
(vitals and sleep). Other columns are ignored. A column listed in ``columns``
that is missing from the file is an error on row 1 (the header).

Units. Without an entry in ``units`` a column is taken to be in the signal's
own unit. Known conversions:

    skin_temp          degF -> degC      (x - 32) x 5/9
    spo2               fraction -> pct   x 100
    sleep_efficiency   fraction -> pct   x 100
    sleep_duration     min -> h, s -> h  / 60, / 3600

Any other unit is an error on row 1 and that column is not read: never a
guess. Relative "deviation" columns (as some rings export for temperature)
cannot become absolute values and are rejected the same way.

Timestamps. ISO dates or date-times. A date without a time is taken as 06:00
that day (the wake-up time, as in the example data). A timestamp without a
timezone needs ``timezone``; without it every such row is an error.

Quality. A value outside the signal's plausible range is kept with
``quality="bad"`` and a note giving the raw value. A row flagged in
``suspect_column`` is ``suspect``. Empty cells are skipped silently. The same
astronaut, signal and timestamp twice: the last row wins.

Output: ``SourceBatch(source_name="wearable_csv:<file name>", observations,
errors)`` with ``source="wearable"`` on every reading and no crew (unknown
astronauts are rejected by ``Pipeline.ingest``). IDs are
``f"{astronaut}-{signal}-{yyyymmddThhmmss}"`` in UTC, so importing the same
file again replaces the readings.

``normalize_records(records, **options)`` does the same for rows already in
memory and returns a ``ParseResult`` (rows numbered from 1).
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, time, tzinfo
from datetime import timezone as _timezone  # `timezone` is also an option name below
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from orbit.core.interfaces import SourceBatch
from orbit.core.registry import register
from orbit.schema import (
    Observation,
    ParseResult,
    Quality,
    RowError,
    SignalType,
    Source,
    get_spec,
)

S = SignalType
ASTRONAUT_COLUMN = "astronaut_id"
WAKE_UP = time(6, 0)  # a date without a time is taken as this local time
SUSPECT_VALUES = frozenset({"1", "true", "yes", "y", "low"})
HEADER_ROW = 1
_UTC = _timezone.utc

# signal -> {vendor unit (matched ignoring case): conversion to the signal's own unit}
CONVERSIONS: dict[SignalType, dict[str, Callable[[float], float]]] = {
    S.SKIN_TEMP: {"degF": lambda x: (x - 32) * 5 / 9},
    S.SPO2: {"fraction": lambda x: x * 100},
    S.SLEEP_EFFICIENCY: {"fraction": lambda x: x * 100},
    S.SLEEP_DURATION: {"min": lambda x: x / 60, "s": lambda x: x / 3600},
}


def _wearable_signals() -> dict[str, SignalType]:
    return {s.value: s for s in SignalType if Source.WEARABLE in get_spec(s).allowed_sources}


def _is_deviation(name: str) -> bool:
    return "deviation" in name.lower()


class _Column:
    """One CSV column that is read: which signal it is and how to convert it."""

    def __init__(self, header: str, signal: SignalType, unit: str,
                 convert: Callable[[float], float] | None):
        self.header = header
        self.signal = signal
        self.unit = unit  # the vendor's unit, as shown in notes
        self.convert = convert


def _plan(headers: list[str], columns: Mapping[str, str], units: Mapping[str, str],
          errors: list[RowError]) -> list[_Column]:
    """Decide which columns are read. Problems become errors on the header row."""
    wearable = _wearable_signals()
    lookup = {h.strip().lower(): h for h in headers}
    chosen: dict[str, SignalType] = {}  # header -> signal

    for header in headers:  # columns named like a signal need no mapping
        if header.strip().lower() in wearable:
            chosen[header] = wearable[header.strip().lower()]

    for name, target in columns.items():
        header = name if name in headers else lookup.get(str(name).strip().lower())
        if header is None:
            errors.append(RowError(HEADER_ROW, f"column '{name}' is not in the file "
                                               f"(found: {', '.join(headers) or 'none'})"))
            continue
        if _is_deviation(header):
            chosen.pop(header, None)
            errors.append(RowError(HEADER_ROW, f"column '{header}' is a relative deviation and "
                                               "cannot become an absolute value; it is not read"))
            continue
        signal = wearable.get(str(target).strip().lower())
        if signal is None:
            errors.append(RowError(HEADER_ROW, f"column '{header}': '{target}' is not a wearable "
                                               f"signal (use one of: {', '.join(wearable)})"))
            continue
        chosen[header] = signal

    vendor_units: dict[SignalType, str] = {}
    for name, unit in units.items():
        signal = wearable.get(str(name).strip().lower())
        if signal is None:
            errors.append(RowError(HEADER_ROW, f"units: '{name}' is not a wearable signal"))
        else:
            vendor_units[signal] = str(unit).strip()

    plan: list[_Column] = []
    seen: dict[SignalType, str] = {}
    for header in headers:
        signal = chosen.get(header)
        if signal is None:
            continue
        if signal in seen:
            errors.append(RowError(HEADER_ROW, f"columns '{seen[signal]}' and '{header}' both map "
                                               f"to {signal.value}; '{header}' is not read"))
            continue
        spec = get_spec(signal)
        unit = vendor_units.get(signal, spec.unit)
        convert = None
        if unit.lower() != spec.unit.lower():
            if _is_deviation(unit):
                errors.append(RowError(HEADER_ROW, f"column '{header}': a relative deviation "
                                                   "cannot become an absolute value; it is not read"))
                continue
            convert = {name.lower(): fn for name, fn in
                       CONVERSIONS.get(signal, {}).items()}.get(unit.lower())
            if convert is None:
                known = ", ".join([spec.unit, *CONVERSIONS.get(signal, {})])
                errors.append(RowError(HEADER_ROW, f"column '{header}': unknown unit '{unit}' for "
                                                   f"{signal.value} (known: {known}); it is not read"))
                continue
        seen[signal] = header
        plan.append(_Column(header, signal, unit, convert))
    return plan


def _timestamp(text: str, zone: tzinfo | None) -> datetime:
    """Parse an ISO date or date-time. Raises ValueError with a plain message."""
    try:
        if len(text) <= 10:  # a date without a time
            when = datetime.combine(datetime.fromisoformat(text).date(), WAKE_UP)
        else:
            when = datetime.fromisoformat(text.replace(" ", "T", 1) if "T" not in text else text)
    except ValueError:
        raise ValueError(f"'{text}' is not an ISO date or time (e.g. 2027-03-14 or "
                         "2027-03-14T06:30:00)") from None
    if when.tzinfo is None:
        if zone is None:
            raise ValueError(f"'{text}' has no timezone; set the `timezone` option "
                             "(an IANA name such as Europe/Bucharest)")
        when = when.replace(tzinfo=zone)
    return when


def _number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError
    return value


def _cell(row: Mapping[str, Any], header: str) -> str:
    value = row.get(header)
    return "" if value is None else str(value).strip()


def normalize_records(
    records: Iterable[Mapping[str, Any]],
    *,
    astronaut_id: str | None = None,
    timestamp_column: str = "date",
    timezone: str | None = None,
    columns: Mapping[str, str] | None = None,
    units: Mapping[str, str] | None = None,
    device_id: str | None = None,
    suspect_column: str | None = None,
    first_row: int = 1,
) -> ParseResult[Observation]:
    """Wide rows (one per night) -> observations plus row-numbered errors.

    ``first_row`` is the number of the first record (2 for a CSV with a header).
    """
    rows = list(records)
    result: ParseResult[Observation] = ParseResult()
    errors = result.errors

    zone = None
    if timezone:
        try:
            zone = ZoneInfo(timezone)
        except Exception:  # unknown name, or no timezone database on this machine
            errors.append(RowError(0, f"unknown timezone '{timezone}': use an IANA name "
                                      "such as Europe/Bucharest"))
            return result

    headers: list[str] = []
    for row in rows:
        headers += [str(h) for h in row if h is not None and str(h) not in headers]
    if rows and timestamp_column not in headers:
        errors.append(RowError(HEADER_ROW, f"timestamp column '{timestamp_column}' is not in the "
                                           f"file (found: {', '.join(headers) or 'none'})"))
        return result
    plan = _plan(headers, columns or {}, units or {}, errors)

    kept: dict[tuple[str, SignalType, datetime], Observation] = {}
    for number, row in enumerate(rows, start=first_row):
        if not any(_cell(row, column.header) for column in plan):
            continue  # nothing to read on this row
        who = _cell(row, ASTRONAUT_COLUMN) or (astronaut_id or "")
        if not who:
            errors.append(RowError(number, "no astronaut: add an astronaut_id column or set "
                                           "the `astronaut_id` option"))
            continue
        try:
            when = _timestamp(_cell(row, timestamp_column), zone)
        except ValueError as exc:
            errors.append(RowError(number, f"{timestamp_column}: {exc}"))
            continue
        suspect = bool(suspect_column) and _cell(row, suspect_column).lower() in SUSPECT_VALUES

        for column in plan:
            raw = _cell(row, column.header)
            if not raw:
                continue  # empty cells are skipped silently
            try:
                value = _number(raw)
            except ValueError:
                errors.append(RowError(number, f"column '{column.header}': '{raw}' is not a number"))
                continue
            spec = get_spec(column.signal)
            if column.convert is not None:
                value = round(column.convert(value), 4)
            quality, note = (Quality.SUSPECT, f"Flagged by the device ({suspect_column})") \
                if suspect else (Quality.GOOD, None)
            if not spec.is_plausible(value):
                quality = Quality.BAD
                note = f"Outside the plausible range; raw value {raw} {column.unit}"
            try:
                obs = Observation(
                    astronaut_id=who, timestamp=when, signal=column.signal, value=value,
                    source=Source.WEARABLE, quality=quality, device_id=device_id, note=note,
                    observation_id=f"{who}-{column.signal.value}-"
                                   f"{when.astimezone(tz=_UTC):%Y%m%dT%H%M%S}",
                )
            except ValidationError as exc:
                problems = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
                errors.append(RowError(number, f"column '{column.header}': {problems}"))
                continue
            # The same astronaut, signal and time again: the last row wins.
            kept[(obs.astronaut_id, obs.signal, obs.timestamp)] = obs

    result.valid.extend(kept.values())
    return result


@register("source", "wearable_csv")
class WearableCsvSource:
    def __init__(
        self,
        path: str | None = None,
        astronaut_id: str | None = None,
        timestamp_column: str = "date",
        timezone: str | None = None,
        columns: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
        device_id: str | None = None,
        suspect_column: str | None = None,
    ):
        self.path = path
        self.astronaut_id = astronaut_id
        self.timestamp_column = timestamp_column
        self.timezone = timezone
        self.columns = dict(columns or {})
        self.units = dict(units or {})
        self.device_id = device_id
        self.suspect_column = suspect_column

    def read(self) -> SourceBatch:
        if not self.path:
            return SourceBatch("wearable_csv", errors=(
                RowError(0, "no file given: set `path` to a wearable CSV export"),))
        file = Path(self.path)
        name = f"wearable_csv:{file.name}"
        if not file.is_file():
            return SourceBatch(name, errors=(RowError(0, f"{file}: file not found"),))
        with file.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            headers = [h for h in (reader.fieldnames or []) if h is not None]
        if not headers:
            return SourceBatch(name, errors=(RowError(0, f"{file.name}: the file is empty"),))
        # Keep the header order even when a column is empty on every row.
        rows = [{h: row.get(h) for h in headers} for row in rows] or [dict.fromkeys(headers, "")]
        result = normalize_records(
            rows, astronaut_id=self.astronaut_id, timestamp_column=self.timestamp_column,
            timezone=self.timezone, columns=self.columns, units=self.units,
            device_id=self.device_id, suspect_column=self.suspect_column, first_row=2,
        )
        return SourceBatch(name, observations=tuple(result.valid), errors=tuple(result.errors))
