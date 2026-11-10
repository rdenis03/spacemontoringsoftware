"""Data sources (slot ``source``).

``files``   reads crew, observations and events from JSONL or CSV files.
``memory``  wraps records already in memory (tests, the check-in API).

The M2 simulator and M5 space-weather feed become new sources: a class with a
``read() -> SourceBatch`` method, registered with ``@register("source", ...)``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from orbit.core.interfaces import SourceBatch
from orbit.core.registry import register
from orbit.schema import (
    ContextEvent,
    CrewMember,
    Observation,
    RowError,
    parse_csv,
    parse_jsonl,
)


def _read(path: str | None, model):
    if not path:
        return [], []
    file = Path(path)
    if not file.is_file():
        return [], [RowError(0, f"{file}: file not found")]
    reader = parse_csv if file.suffix.lower() == ".csv" else parse_jsonl
    result = reader(file, model)
    errors = [RowError(e.row, f"{file.name}: {e.message}") for e in result.errors]
    return result.valid, errors


@register("source", "files")
class FileSource:
    def __init__(
        self,
        crew_path: str | None = None,
        observations_path: str | None = None,
        events_path: str | None = None,
    ):
        self.crew_path = crew_path
        self.observations_path = observations_path
        self.events_path = events_path

    def read(self) -> SourceBatch:
        crew, crew_errors = _read(self.crew_path, CrewMember)
        observations, obs_errors = _read(self.observations_path, Observation)
        events, event_errors = _read(self.events_path, ContextEvent)
        return SourceBatch(
            source_name="files",
            crew=tuple(crew),
            observations=tuple(observations),
            events=tuple(events),
            errors=tuple(crew_errors + obs_errors + event_errors),
        )


@register("source", "memory")
class MemorySource:
    def __init__(
        self,
        crew: Iterable[CrewMember] = (),
        observations: Iterable[Observation] = (),
        events: Iterable[ContextEvent] = (),
        name: str = "memory",
    ):
        self._batch = SourceBatch(name, tuple(crew), tuple(observations), tuple(events))

    def read(self) -> SourceBatch:
        return self._batch
