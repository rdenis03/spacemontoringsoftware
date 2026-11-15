"""The shared store (M4): one SQLite database every module reads and writes.

Why SQLite: it is a single file, needs no server, works offline and ships with
Python, which is exactly the situation on a spacecraft.

Design: each table keeps the full record as validated JSON (``doc``) plus a
few indexed columns used for filtering (astronaut, signal, time). Adding a
field to a model therefore needs no database migration, and everything read
back is re-validated against the M1 schema.

Writes are idempotent: saving the same observation twice, or re-running the
pipeline for the same day, replaces the old rows instead of duplicating them.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from orbit.schema import (
    SCHEMA_VERSION,
    ActionCard,
    Anomaly,
    Baseline,
    ContextEvent,
    CrewMember,
    Observation,
    Quality,
    RiskAssessment,
    SignalType,
    TriageSession,
)

from .interfaces import DayResult, EarthPacket

M = TypeVar("M", bound=BaseModel)

_TABLES = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crew (
    astronaut_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL, signal TEXT NOT NULL,
    ts INTEGER NOT NULL, quality TEXT NOT NULL, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS obs_by_astronaut ON observations (astronaut_id, ts);
CREATE INDEX IF NOT EXISTS obs_by_signal ON observations (astronaut_id, signal, ts);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, astronaut_id TEXT, start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS baselines (
    astronaut_id TEXT NOT NULL, signal TEXT NOT NULL, ts INTEGER NOT NULL,
    doc TEXT NOT NULL, PRIMARY KEY (astronaut_id, signal, ts));
CREATE TABLE IF NOT EXISTS anomalies (
    astronaut_id TEXT NOT NULL, signal TEXT NOT NULL, ts INTEGER NOT NULL,
    run_ts INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS anomalies_by_run ON anomalies (astronaut_id, run_ts);
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL, ts INTEGER NOT NULL,
    level TEXT NOT NULL, score REAL NOT NULL, doc TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_assessment_per_time ON assessments (astronaut_id, ts);
CREATE TABLE IF NOT EXISTS recommendations (
    assessment_id TEXT NOT NULL, position INTEGER NOT NULL, doc TEXT NOT NULL,
    PRIMARY KEY (assessment_id, position));
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL, created_ts INTEGER NOT NULL,
    deliver_ts INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS outbox_by_time ON outbox (astronaut_id, created_ts);
CREATE TABLE IF NOT EXISTS triage_sessions (
    id TEXT PRIMARY KEY, astronaut_id TEXT NOT NULL, started_ts INTEGER NOT NULL,
    status TEXT NOT NULL, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS triage_by_time ON triage_sessions (astronaut_id, started_ts);
"""


def _ts(value: datetime) -> int:
    """Datetime -> integer microseconds since 1970 (UTC), for fast range queries."""
    if value.tzinfo is None:
        raise ValueError("store queries need timezone-aware datetimes")
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)


class StoreError(RuntimeError):
    pass


class OutboxEntry(BaseModel):
    """One packet queued for Earth (M13, task B16): what was sent, when, when it arrives.

    The packet has already passed the consent gate. Delivery is simulated: a
    packet counts as delivered once the real current time reaches
    ``deliver_at``. The outbox doubles as the audit log of everything that
    left the spacecraft. ``summary`` is filled by B17, ``auto`` set by B18.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    astronaut_id: str
    created_at: datetime
    deliver_at: datetime
    packet: EarthPacket
    summary: str = Field(default="", description="Plain-language report for Earth (B17).")
    auto: bool = Field(default=False, description="Queued by ORBIT itself on orange/red (B18).")


class Store:
    """Thread-safe access to the ORBIT database.

    ``Store(":memory:")`` gives a throwaway database for tests and demos.
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._tx() as db:
            db.executescript(_TABLES)
            row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
            elif row[0].split(".")[0] != SCHEMA_VERSION.split(".")[0]:
                raise StoreError(
                    f"{self.path} was created with schema {row[0]}, this code uses "
                    f"{SCHEMA_VERSION}; delete the file or migrate it"
                )

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _docs(self, model: type[M], sql: str, params: Sequence = ()) -> list[M]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [model.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- crew ------------------------------------------------------------

    def upsert_crew(self, members: Iterable[CrewMember]) -> int:
        rows = [(m.astronaut_id, m.model_dump_json()) for m in members]
        with self._tx() as db:
            db.executemany("INSERT OR REPLACE INTO crew VALUES (?, ?)", rows)
        return len(rows)

    def crew(self) -> list[CrewMember]:
        return self._docs(CrewMember, "SELECT doc FROM crew ORDER BY astronaut_id")

    def member(self, astronaut_id: str) -> CrewMember | None:
        found = self._docs(CrewMember, "SELECT doc FROM crew WHERE astronaut_id=?", (astronaut_id,))
        return found[0] if found else None

    # ---- observations ----------------------------------------------------

    def add_observations(self, observations: Iterable[Observation]) -> int:
        rows = [
            (o.observation_id, o.astronaut_id, o.signal.value, _ts(o.timestamp),
             o.quality.value, o.model_dump_json())
            for o in observations
        ]
        with self._tx() as db:
            db.executemany("INSERT OR REPLACE INTO observations VALUES (?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def observations(
        self,
        astronaut_id: str,
        *,
        signals: Iterable[SignalType | str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        usable_only: bool = True,
    ) -> list[Observation]:
        """Readings for one astronaut in [start, end], oldest first."""
        sql = ["SELECT doc FROM observations WHERE astronaut_id = ?"]
        params: list = [astronaut_id]
        if signals is not None:
            names = [SignalType(s).value for s in signals]
            if not names:
                return []
            sql.append(f"AND signal IN ({','.join('?' * len(names))})")
            params += names
        if start is not None:
            sql.append("AND ts >= ?")
            params.append(_ts(start))
        if end is not None:
            sql.append("AND ts <= ?")
            params.append(_ts(end))
        if usable_only:
            sql.append("AND quality != ?")
            params.append(Quality.BAD.value)
        sql.append("ORDER BY ts, id")
        return self._docs(Observation, " ".join(sql), params)

    def data_range(self, astronaut_id: str | None = None) -> tuple[datetime, datetime] | None:
        """Time of the first and last observation, for one astronaut or everyone."""
        sql = "SELECT MIN(ts), MAX(ts) FROM observations"
        params: tuple = ()
        if astronaut_id is not None:
            sql += " WHERE astronaut_id = ?"
            params = (astronaut_id,)
        with self._lock:
            low, high = self._conn.execute(sql, params).fetchone()
        if low is None:
            return None
        to_dt = lambda us: datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc)  # noqa: E731
        return to_dt(low), to_dt(high)

    # ---- events ----------------------------------------------------------

    def add_events(self, events: Iterable[ContextEvent]) -> int:
        rows = [
            (e.event_id, e.astronaut_id, _ts(e.start), _ts(e.end or e.start), e.model_dump_json())
            for e in events
        ]
        with self._tx() as db:
            db.executemany("INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?, ?)", rows)
        return len(rows)

    def events(
        self,
        astronaut_id: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ContextEvent]:
        """Events overlapping [start, end]. For an astronaut, includes crew-wide events."""
        sql = ["SELECT doc FROM events WHERE 1=1"]
        params: list = []
        if astronaut_id is not None:
            sql.append("AND (astronaut_id IS NULL OR astronaut_id = ?)")
            params.append(astronaut_id)
        if start is not None:
            sql.append("AND end_ts >= ?")
            params.append(_ts(start))
        if end is not None:
            sql.append("AND start_ts <= ?")
            params.append(_ts(end))
        sql.append("ORDER BY start_ts, id")
        return self._docs(ContextEvent, " ".join(sql), params)

    # ---- analytics results ---------------------------------------------

    def save_day(self, result: DayResult) -> None:
        """Store one assessment run, replacing any earlier run for the same moment."""
        aid, run_ts = result.astronaut_id, _ts(result.as_of)
        with self._tx() as db:
            old = db.execute(
                "SELECT id FROM assessments WHERE astronaut_id=? AND ts=?", (aid, run_ts)
            ).fetchall()
            for (old_id,) in old:
                db.execute("DELETE FROM recommendations WHERE assessment_id=?", (old_id,))
            db.execute("DELETE FROM assessments WHERE astronaut_id=? AND ts=?", (aid, run_ts))
            db.execute("DELETE FROM anomalies WHERE astronaut_id=? AND run_ts=?", (aid, run_ts))
            db.execute("DELETE FROM baselines WHERE astronaut_id=? AND ts=?", (aid, run_ts))

            db.executemany(
                "INSERT OR REPLACE INTO baselines VALUES (?, ?, ?, ?)",
                [(b.astronaut_id, b.signal.value, _ts(b.as_of), b.model_dump_json())
                 for b in result.baselines],
            )
            db.executemany(
                "INSERT INTO anomalies VALUES (?, ?, ?, ?, ?)",
                [(a.astronaut_id, a.signal.value, _ts(a.detected_at), run_ts, a.model_dump_json())
                 for a in result.anomalies],
            )
            if result.assessment is not None:
                a = result.assessment
                db.execute(
                    "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?)",
                    (a.assessment_id, a.astronaut_id, _ts(a.assessed_at), a.level.value,
                     a.score, a.model_dump_json()),
                )
                db.executemany(
                    "INSERT INTO recommendations VALUES (?, ?, ?)",
                    [(a.assessment_id, i, card.model_dump_json())
                     for i, card in enumerate(result.actions)],
                )

    def assessments(
        self, astronaut_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[RiskAssessment]:
        sql = ["SELECT doc FROM assessments WHERE astronaut_id = ?"]
        params: list = [astronaut_id]
        if start is not None:
            sql.append("AND ts >= ?")
            params.append(_ts(start))
        if end is not None:
            sql.append("AND ts <= ?")
            params.append(_ts(end))
        sql.append("ORDER BY ts")
        return self._docs(RiskAssessment, " ".join(sql), params)

    def latest_assessment(self, astronaut_id: str) -> RiskAssessment | None:
        found = self._docs(
            RiskAssessment,
            "SELECT doc FROM assessments WHERE astronaut_id=? ORDER BY ts DESC LIMIT 1",
            (astronaut_id,),
        )
        return found[0] if found else None

    def recommendations(self, assessment_id: str) -> list[ActionCard]:
        return self._docs(
            ActionCard,
            "SELECT doc FROM recommendations WHERE assessment_id=? ORDER BY position",
            (assessment_id,),
        )

    def anomalies_at(self, astronaut_id: str, as_of: datetime) -> list[Anomaly]:
        """Anomalies found by the assessment run at ``as_of``."""
        return self._docs(
            Anomaly, "SELECT doc FROM anomalies WHERE astronaut_id=? AND run_ts=?",
            (astronaut_id, _ts(as_of)),
        )

    def baselines(
        self,
        astronaut_id: str,
        *,
        signal: SignalType | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Baseline]:
        """Baseline history, e.g. to draw the 'your normal' band over time."""
        sql = ["SELECT doc FROM baselines WHERE astronaut_id = ?"]
        params: list = [astronaut_id]
        if signal is not None:
            sql.append("AND signal = ?")
            params.append(SignalType(signal).value)
        if start is not None:
            sql.append("AND ts >= ?")
            params.append(_ts(start))
        if end is not None:
            sql.append("AND ts <= ?")
            params.append(_ts(end))
        sql.append("ORDER BY ts, signal")
        return self._docs(Baseline, " ".join(sql), params)

    # ---- outbox (M13) -------------------------------------------------------

    def queue(self, entry: OutboxEntry) -> None:
        """Add a packet to the outbox. Re-queuing the same ``id`` replaces it."""
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO outbox VALUES (?, ?, ?, ?, ?)",
                (entry.id, entry.astronaut_id, _ts(entry.created_at),
                 _ts(entry.deliver_at), entry.model_dump_json()),
            )

    def outbox(self, astronaut_id: str | None = None) -> list[OutboxEntry]:
        """Queued and delivered packets, newest first."""
        if astronaut_id is None:
            return self._docs(OutboxEntry, "SELECT doc FROM outbox ORDER BY created_ts DESC")
        return self._docs(
            OutboxEntry,
            "SELECT doc FROM outbox WHERE astronaut_id=? ORDER BY created_ts DESC",
            (astronaut_id,),
        )

    # ---- triage sessions (M15) ---------------------------------------------

    def save_session(self, session: TriageSession) -> None:
        """Save a triage chat. Saving the same ``session_id`` again replaces it."""
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO triage_sessions VALUES (?, ?, ?, ?, ?)",
                (session.session_id, session.astronaut_id, _ts(session.started_at),
                 session.status.value, session.model_dump_json()),
            )

    def session(self, session_id: str) -> TriageSession | None:
        found = self._docs(TriageSession, "SELECT doc FROM triage_sessions WHERE id=?", (session_id,))
        return found[0] if found else None

    def sessions(
        self, astronaut_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[TriageSession]:
        """One astronaut's triage chats started in [start, end], newest first."""
        sql = ["SELECT doc FROM triage_sessions WHERE astronaut_id = ?"]
        params: list = [astronaut_id]
        if start is not None:
            sql.append("AND started_ts >= ?")
            params.append(_ts(start))
        if end is not None:
            sql.append("AND started_ts <= ?")
            params.append(_ts(end))
        sql.append("ORDER BY started_ts DESC, id")
        return self._docs(TriageSession, " ".join(sql), params)

    def counts(self) -> dict[str, int]:
        tables = ("crew", "observations", "events", "baselines", "anomalies",
                  "assessments", "recommendations", "outbox", "triage_sessions")
        with self._lock:
            return {t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
