"""Reading and writing ORBIT data, with row-level error reports.

Every reader returns a ``ParseResult`` instead of stopping at the first bad
row, so the ingestion module (M3) can keep good data and report the rest::

    result = parse_jsonl("wearable_export.jsonl")
    print(result.summary())          # "980 valid, 20 rejected"
    for err in result.errors[:5]:
        print(err)                   # "row 17: value: 61.2 °C is outside ..."

    observations = result.raise_if_errors()   # or: fail on any bad row

File formats:
    JSONL  one JSON object per line. The native format; lossless.
    CSV    one row per record, header = field names. Handy for spreadsheets.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar, get_args

import pandas as pd
from pydantic import BaseModel, ValidationError

from .models import Observation

M = TypeVar("M", bound=BaseModel)

OBSERVATION_COLUMNS: tuple[str, ...] = tuple(Observation.model_fields)
"""Column order for observation tables and CSV files."""


@dataclass(frozen=True)
class RowError:
    """One rejected record. ``row`` is the 1-based line number in the file."""

    row: int
    message: str

    def __str__(self) -> str:
        return f"row {self.row}: {self.message}"


class SchemaError(ValueError):
    """Raised by ``ParseResult.raise_if_errors`` when any record was rejected."""

    def __init__(self, errors: list[RowError], source: str | None = None):
        self.errors = errors
        where = f" in {source}" if source else ""
        shown = "\n  ".join(str(e) for e in errors[:10])
        more = f"\n  ... and {len(errors) - 10} more" if len(errors) > 10 else ""
        super().__init__(f"{len(errors)} invalid record(s){where}:\n  {shown}{more}")


@dataclass
class ParseResult(Generic[M]):
    valid: list[M] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    source: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_errors(self) -> list[M]:
        """Return the valid records, or raise ``SchemaError`` if any were rejected."""
        if self.errors:
            raise SchemaError(self.errors, self.source)
        return self.valid

    def summary(self) -> str:
        return f"{len(self.valid)} valid, {len(self.errors)} rejected"


def _describe(exc: ValidationError) -> str:
    """Turn a pydantic error into one readable line."""
    parts = []
    for err in exc.errors():
        location = ".".join(str(p) for p in err["loc"])
        message = err["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)


def parse_records(
    records: Iterable[Mapping[str, Any]],
    model: type[M] = Observation,
    *,
    start_row: int = 1,
    source: str | None = None,
) -> ParseResult[M]:
    """Validate dictionaries into models, collecting errors instead of raising."""
    result: ParseResult[M] = ParseResult(source=source)
    for row, record in enumerate(records, start=start_row):
        try:
            result.valid.append(model.model_validate(dict(record)))
        except ValidationError as exc:
            result.errors.append(RowError(row, _describe(exc)))
    return result


# --------------------------------------------------------------------------
# JSONL
# --------------------------------------------------------------------------


def parse_jsonl(path: str | Path, model: type[M] = Observation) -> ParseResult[M]:
    """Read a JSON-lines file. Blank lines are skipped."""
    path = Path(path)
    result: ParseResult[M] = ParseResult(source=str(path))
    with path.open(encoding="utf-8") as handle:
        for row, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                result.errors.append(RowError(row, f"not valid JSON ({exc.msg})"))
                continue
            if not isinstance(record, dict):
                result.errors.append(RowError(row, "expected a JSON object"))
                continue
            try:
                result.valid.append(model.model_validate(record))
            except ValidationError as exc:
                result.errors.append(RowError(row, _describe(exc)))
    return result


def write_jsonl(items: Iterable[BaseModel], path: str | Path) -> int:
    """Write models as JSON lines. Returns the number of records written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(item.model_dump_json() + "\n")
            count += 1
    return count


# --------------------------------------------------------------------------
# pandas
# --------------------------------------------------------------------------


def _datetime_fields(model: type[BaseModel]) -> list[str]:
    names = []
    for name, info in model.model_fields.items():
        annotation = info.annotation
        if annotation is datetime or datetime in get_args(annotation):
            names.append(name)
    return names


def to_dataframe(items: Iterable[BaseModel], model: type[BaseModel] = Observation) -> pd.DataFrame:
    """Convert models to a DataFrame: one row per record, timestamps as UTC.

    Enum fields become plain strings ("skin_temp"), so filtering is simple::

        df[df.signal == "skin_temp"]
    """
    columns = list(model.model_fields)
    rows = [item.model_dump(mode="json") for item in items]
    frame = pd.DataFrame(rows, columns=columns)
    for name in _datetime_fields(model):
        frame[name] = pd.to_datetime(frame[name], utc=True, format="ISO8601")
    if model is Observation:
        frame["value"] = frame["value"].astype("float64")
        frame["simulated"] = frame["simulated"].astype("bool")
    return frame


def _clean_cell(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return value.item()  # numpy scalar -> Python scalar
    return value


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False  # lists, dicts and other non-scalars are never "missing"


def from_dataframe(
    frame: pd.DataFrame,
    model: type[M] = Observation,
    *,
    start_row: int = 1,
    source: str | None = None,
) -> ParseResult[M]:
    """Validate DataFrame rows into models. Empty cells use the field's default."""
    records = (
        {key: _clean_cell(val) for key, val in row.items() if not _is_missing(val)}
        for row in frame.to_dict(orient="records")
    )
    return parse_records(records, model, start_row=start_row, source=source)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------


def write_csv(items: Iterable[BaseModel], path: str | Path, model: type[BaseModel] = Observation) -> int:
    """Write models to CSV. Timestamps are ISO 8601 with a UTC offset."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = to_dataframe(items, model)
    for name in _datetime_fields(model):
        frame[name] = frame[name].map(lambda t: t.isoformat() if not pd.isna(t) else "")
    frame.to_csv(path, index=False)
    return len(frame)


def parse_csv(path: str | Path, model: type[M] = Observation) -> ParseResult[M]:
    """Read a CSV file. Row numbers in errors match spreadsheet line numbers."""
    path = Path(path)
    # Read everything as text so IDs like "007" survive; the models convert types.
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    return from_dataframe(frame, model, start_row=2, source=str(path))
