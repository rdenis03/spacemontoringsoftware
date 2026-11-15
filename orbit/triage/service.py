"""Triage service (M15, not a slot): the only place triage modules meet.

As the pipeline is for the analytics, the service is for the chat check-in.
It owns all I/O (the store and the pipeline) and the wall clock used for
session timeouts; the extractor and reasoner slots stay pure.

One turn (``start`` or ``answer``)::

    red-flag rules (text and answer) ──▶ extractor (new text only) ──▶ merge answers into findings
        ──▶ preview = pipeline.assess(as_of, save=False) ──▶ reasoner.rank ──▶ reasoner.next_question

* Red flags run first and only grow. Any red flag: status ``escalated``, no
  question, the rule's card first in ``procedures``.
* Nothing is saved but the session itself. The preview is not saved, so
  B18's auto-send ignores it.
* Each step runs in an error boundary; errors go to ``TriageResult.errors``
  as ``"<step>: <ExceptionType>: <message>"`` and the rest still works.
* ``procedures`` is empty while asking; it is built when the session is
  ready or escalated, and again on confirm.

``confirm`` turns the findings into ordinary check-in observations
(``observation_id = f"{astronaut}-{signal}-{as_of:%Y%m%dT%H%M%S}"``,
``note = f"triage {session_id}"``, never the raw text), calls
``pipeline.assess(astronaut, as_of)`` (saved, so hooks and auto-send run as
for any check-in), ranks again with the re-assessment as the preview, merges
the cards and re-saves that run with them. A denied symptom is stored as 0
and a symptom mentioned without a severity as 1 (mild). Complaints outside
the 8 signals write nothing and stay in the session.

Times: ``as_of`` is the session's timestamp (mission time in the demo) and
the only "now" the analytics see. ``started_at`` and ``updated_at`` come from
``clock`` (real time); an open session expires ``session_timeout_minutes``
after its last turn, when it is next read.

Safety rules (B23 review):

* **Screen before validating.** The red-flag rules read the free text and
  any string answer before anything else is checked. If a flag fires, the
  turn escalates even when the answer is invalid or for the wrong question;
  the problem goes to ``errors`` instead of a 422 that would drop the words.
* **Red flags only grow, even with parallel requests.** Every
  read-modify-write of a session (turns, confirm, cancel, expiry) holds one
  lock per session id, and saving merges red flags and reports with what is
  stored instead of overwriting them.
* **No chat text in logs.** A failing step logs only its name, the exception
  type and the session id.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from orbit.core.interfaces import (
    AssessmentContext,
    DayResult,
    SymptomExtractor,
    TriageEvidence,
    TriageReasoner,
)
from orbit.core.pipeline import Pipeline
from orbit.core.registry import create
from orbit.schema import (
    ActionCard,
    AlertLevel,
    Observation,
    PatternScore,
    SignalCategory,
    SignalType,
    SymptomFinding,
    SymptomReport,
    TriageAnswer,
    TriageQuestion,
    TriageResult,
    TriageSession,
    TriageStatus,
    get_spec,
)

from .config import DEFAULT_EXTRACTOR, DEFAULT_REASONER, TriageSettings
from .library import TriageLibrary, merge_procedures
from .red_flags import RedFlagRules, flagged_strings, screen_payload

log = logging.getLogger("orbit.triage")

UNRATED_SEVERITY = 1
"""Stored value for a symptom confirmed without a severity: 'mild'."""


class TriageError(Exception):
    """Base class; the API maps the subclasses to 404, 409 and 422."""


class UnknownAstronaut(TriageError, LookupError):
    pass


class SessionNotFound(TriageError, LookupError):
    pass


class SessionClosed(TriageError):
    """The session is confirmed, cancelled or expired."""


class BadAnswer(TriageError, ValueError):
    """Wrong question, a value outside its answers, bad text or a bad correction."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise BadAnswer("timestamp needs a timezone, e.g. 2027-04-02T10:30:00Z")
    return value.astimezone(timezone.utc)


def _key(finding: SymptomFinding) -> SignalType | str:
    return finding.signal or finding.label


def _merge_findings(old: Sequence[SymptomFinding], new: Iterable[SymptomFinding]) -> list[SymptomFinding]:
    """Add newly extracted findings; a new mention of the same symptom updates the old one."""
    merged = list(old)
    for finding in new:
        index = next((i for i, f in enumerate(merged) if _key(f) == _key(finding)), None)
        if index is None:
            merged.append(finding)
            continue
        before = merged[index]
        if finding.severity is not None:
            severity = finding.severity
        else:
            severity = None if before.negated else before.severity
        merged[index] = before.model_copy(update={
            "negated": finding.negated,
            "severity": 0 if finding.negated else severity,
            "evidence": tuple(dict.fromkeys(before.evidence + finding.evidence)),
            "confidence": max(before.confidence, finding.confidence),
            "onset_hours": finding.onset_hours if finding.onset_hours is not None else before.onset_hours,
            "body_site": finding.body_site or before.body_site,
            "side": finding.side or before.side,
        })
    return merged


def _set_severity(findings: Sequence[SymptomFinding], signal: SignalType, severity: int) -> list[SymptomFinding]:
    """What a symptom answer or correction says: severity 0-3 (0 = denied)."""
    update = {"severity": severity, "negated": severity == 0}
    if any(f.signal is signal for f in findings):
        return [f.model_copy(update=update) if f.signal is signal else f for f in findings]
    return [*findings, SymptomFinding(signal=signal, label=get_spec(signal).label, **update)]


def _checkin_value(finding: SymptomFinding) -> int:
    if finding.negated:
        return 0
    return finding.severity if finding.severity is not None else UNRATED_SEVERITY


class TriageService:
    """The chat check-in. Build it with ``from_settings`` or with ready modules (tests)."""

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        extractor: SymptomExtractor | None = None,
        reasoner: TriageReasoner | None = None,
        library: TriageLibrary | None = None,
        red_flags: RedFlagRules | None = None,
        session_timeout_minutes: float = 120.0,
        clock: Callable[[], datetime] | None = None,
        module_names: Mapping[str, str] | None = None,
    ):
        if not 0 < session_timeout_minutes <= 24 * 60:
            raise ValueError("session_timeout_minutes must be in (0, 1440]")
        self.pipeline = pipeline
        self.store = pipeline.store
        self.extractor = extractor if extractor is not None else create("extractor", DEFAULT_EXTRACTOR)
        self.reasoner = reasoner if reasoner is not None else create("reasoner", DEFAULT_REASONER)
        day_cards = tuple(getattr(pipeline.actions, "cards", ()))
        self.library = library if library is not None else TriageLibrary.load(day_cards=day_cards)
        self.red_flags = red_flags if red_flags is not None else RedFlagRules.load()
        questions = tuple(getattr(self.reasoner, "questions", ()))
        self.red_flags.check_bank(questions)
        self.red_flags.check_cards(self.library.has_card)
        self._bank = {q.question_id: q for q in questions}
        self.timeout = timedelta(minutes=session_timeout_minutes)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self.module_names = dict(module_names or {
            "extractor": type(self.extractor).__name__, "reasoner": type(self.reasoner).__name__})
        versions = (getattr(m, "version", type(m).__name__) for m in (self.extractor, self.reasoner))
        self.model_version = "+".join(versions)[:64]

    @classmethod
    def from_settings(cls, triage_settings: TriageSettings, pipeline: Pipeline,
                      clock: Callable[[], datetime] | None = None) -> TriageService:
        """Build the modules and libraries chosen in ``[triage]``."""
        ts = triage_settings
        return cls(
            pipeline,
            extractor=create("extractor", ts.extractor.use, **ts.extractor.options),
            reasoner=create("reasoner", ts.reasoner.use, **ts.reasoner.options),
            library=TriageLibrary.load(ts.patterns_path, ts.triage_cards_path,
                                       getattr(pipeline.actions, "cards", ())),
            red_flags=RedFlagRules.load(ts.red_flags_path),
            session_timeout_minutes=ts.session_timeout_minutes,
            clock=clock,
            module_names={"extractor": ts.extractor.use, "reasoner": ts.reasoner.use},
        )

    # ---- the conversation ---------------------------------------------------------------

    # Every write goes through a ``*_raw`` method: the red-flag gate first, on the raw
    # body, then the session lookup, then validation. With a flag, nothing below the gate
    # raises: the session is escalated and saved, and the problems go to ``errors``.
    # The keyword methods (start, answer, confirm, cancel) build a raw body and use the same path.

    def start(self, astronaut_id: str, text: str, timestamp: datetime | None = None) -> TriageResult:
        """Open a session with the astronaut's first message. ``timestamp`` is the moment assessed."""
        raw: dict[str, Any] = {"text": text}
        if timestamp is not None:
            raw["timestamp"] = timestamp
        return self.start_raw(astronaut_id, raw)

    def answer(self, session_id: str, *, question_id: str | None = None, value: Any = None,
               text: str | None = None, done: bool = False) -> TriageResult:
        """Answer the open question (``value=None`` skips it), add text, and/or end the questions."""
        raw: dict[str, Any] = {}
        if question_id is not None:
            raw.update(question_id=question_id, value=value)
        if text is not None:
            raw["text"] = text
        if done:
            raw["done"] = True
        return self.answer_raw(None, session_id, raw)

    def screen(self, raw: Any) -> list[str]:
        """The safety gate: red-flag rule ids anywhere in a request body (never raises)."""
        return screen_payload(raw, self.red_flags, self._bank)

    def start_raw(self, astronaut_id: str, raw: Any) -> TriageResult:
        """Start from a raw request body (parsed JSON, or the text of a non-JSON body)."""
        flags = self.screen(raw)  # the gate, before anything else
        if self.store.member(astronaut_id) is None:
            raise UnknownAstronaut(f"unknown astronaut '{astronaut_id}'")
        body, problems = self._body(raw, flags, ("text", "timestamp"), text_body=True)
        text = self._text(body.get("text"), problems, required=True, flags=flags)
        as_of = self._timestamp(body.get("timestamp"), problems)
        self._fail_unless_flagged(problems, flags)
        return self._new_session(astronaut_id, raw, text, as_of, flags, problems)

    def answer_raw(self, astronaut_id: str | None, session_id: str, raw: Any) -> TriageResult:
        """Answer from a raw request body: ``{question_id, value}``, ``{text}`` and/or ``{done}``.

        ``astronaut_id`` (from the URL) lets a flagged message to an unknown,
        closed or foreign session start a new escalated session instead of being lost.
        """
        flags = self.screen(raw)  # the gate, before anything else
        with self._lock(session_id):
            session, fallback = self._session_for_write(astronaut_id, session_id, raw, flags)
            if fallback is not None:
                return fallback
            body, problems = self._body(raw, flags, ("question_id", "value", "text", "done"), text_body=True)
            question_id = body.get("question_id")
            if question_id is not None and not isinstance(question_id, str):
                problems.append("question_id must be a string")
                question_id = None
            done = body.get("done", False)
            if not isinstance(done, bool):
                problems.append("done must be true or false")
                done = False
            text = self._text(body.get("text"), problems, required=False, flags=flags)
            if question_id is None and "text" not in body and not done and not problems:
                problems.append("send a question_id with a value, some text, or done")
            answer = pending = None
            if question_id is not None:
                try:
                    pending, answer = self._validate_answer(session, question_id, body.get("value"))
                except BadAnswer as exc:
                    problems.append(f"answer: {exc}")
            self._fail_unless_flagged(problems, flags)
            reports = self._reports(session.astronaut_id, session.as_of, text, raw, flags)
            return self._turn(session, reports=reports, answer=answer, question=pending, done=done,
                              flags=flags, problems=problems)

    def _session_for_write(self, astronaut_id: str | None, session_id: str, raw: Any,
                           flags: Sequence[str]) -> tuple[TriageSession | None, TriageResult | None]:
        """The open session, or (with a flag) a new escalated session instead of a 404 or 409."""
        try:
            session = self._open(session_id)
            if astronaut_id is not None and session.astronaut_id != astronaut_id:
                raise SessionNotFound(f"unknown triage session '{session_id}' for '{astronaut_id}'")
            return session, None
        except (SessionNotFound, SessionClosed) as exc:
            if not flags or astronaut_id is None or self.store.member(astronaut_id) is None:
                raise
            now = self.clock()
            return None, self._new_session(astronaut_id, raw, None, now, flags,
                                           [f"session: {exc}; started a new session for the red flag"])

    def _new_session(self, astronaut_id: str, raw: Any, text: str | None, as_of: datetime | None,
                     flags: Sequence[str], problems: Sequence[str]) -> TriageResult:
        now = self.clock()
        as_of = as_of or now
        session = TriageSession(session_id=f"tri-{uuid.uuid4().hex[:12]}", astronaut_id=astronaut_id,
                                started_at=now, updated_at=now, as_of=as_of)
        reports = self._reports(astronaut_id, as_of, text, raw, flags)
        with self._lock(session.session_id):
            return self._turn(session, reports=reports, flags=flags, problems=problems)

    def _body(self, raw: Any, flags: Sequence[str], fields: tuple[str, ...],
              text_body: bool = False) -> tuple[dict[str, Any], list[str]]:
        """The body as a dict of known fields, and the problems found (no raising here)."""
        problems: list[str] = []
        if raw is None:
            return {}, problems
        if isinstance(raw, str) and text_body:
            problems.append("the body is not JSON")
            return ({"text": raw} if flags else {}), problems
        if not isinstance(raw, Mapping):
            problems.append("the body must be a JSON object")
            return {}, problems
        unknown = sorted(str(k) for k in raw if k not in fields)
        if unknown:
            problems.append(f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(fields)}")
        return {k: v for k, v in raw.items() if k in fields}, problems

    @staticmethod
    def _text(value: Any, problems: list[str], *, required: bool, flags: Sequence[str]) -> str | None:
        """Free text, 1 to 1,000 characters. With a red flag, longer text is cut (and said so)."""
        if value is None:
            if required:
                problems.append("text is required (1 to 1,000 characters)")
            return None
        if not isinstance(value, str) or not value.strip():
            problems.append("text must be 1 to 1,000 characters of text")
            return None
        if len(value) > 1000:
            if flags:
                problems.append(f"text was cut to its first 1,000 of {len(value):,} characters")
                return value[:1000]
            problems.append(f"text must be 1 to 1,000 characters; got {len(value):,}")
            return None
        return value

    def _timestamp(self, value: Any, problems: list[str]) -> datetime | None:
        """A timezone-aware time. ISO strings without a timezone count as UTC (as elsewhere in the API)."""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                problems.append(f"timestamp '{value}' is not an ISO time like 2027-04-02T10:30:00Z")
                return None
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else _utc(parsed)
        if isinstance(value, datetime):
            try:
                return _utc(value)
            except BadAnswer as exc:
                problems.append(str(exc))
                return None
        problems.append("timestamp must be an ISO time like 2027-04-02T10:30:00Z")
        return None

    @staticmethod
    def _fail_unless_flagged(problems: Sequence[str], flags: Sequence[str]) -> None:
        if problems and not flags:
            raise BadAnswer("; ".join(problems))

    def _reports(self, astronaut_id: str, as_of: datetime, text: str | None, raw: Any,
                 flags: Sequence[str]) -> tuple[SymptomReport, ...]:
        """The valid text, plus any other flagged words in the body, so they stay onboard."""
        kept: list[str] = [text.strip()] if text and text.strip() else []
        for words in flagged_strings(raw, self.red_flags) if flags else []:
            if text and words.startswith(text):
                continue  # the text itself (perhaps cut to 1,000 characters)
            stored = words.strip()[:1000].strip()
            if stored and stored not in kept:
                kept.append(stored)
        return tuple(SymptomReport(astronaut_id=astronaut_id, reported_at=as_of, text=t) for t in kept)

    def _validate_answer(self, session: TriageSession, question_id: str,
                         value: Any) -> tuple[TriageQuestion, TriageAnswer]:
        pending = session.result.next_question if session.result else None
        if pending is None:
            raise BadAnswer("no question is open in this session")
        if question_id != pending.question_id:
            raise BadAnswer(f"'{question_id}' is not the open question; answer '{pending.question_id}'")
        try:
            normal = pending.normalize(value)
        except ValueError as exc:
            raise BadAnswer(str(exc)) from exc
        return pending, TriageAnswer(question_id=question_id, value=normal, answered_at=self.clock())

    def _lock(self, session_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.RLock())

    def confirm(self, session_id: str, corrections: Mapping[SignalType | str, int] | None = None
                ) -> tuple[TriageResult, DayResult | None]:
        """Save the findings as a check-in, re-assess, and save the chat's cards with that run."""
        return self.confirm_raw(None, session_id, {"corrections": corrections} if corrections else None)

    def confirm_raw(self, astronaut_id: str | None, session_id: str, raw: Any
                    ) -> tuple[TriageResult, DayResult | None]:
        """Confirm from a raw body ``{corrections?: {signal: 0-3}}``.

        With a red flag in the body, the flag is recorded first; if the body is
        also invalid, the session is escalated and not confirmed (``day`` is None).
        """
        flags = self.screen(raw)  # the gate, before anything else
        with self._lock(session_id):
            session, fallback = self._session_for_write(astronaut_id, session_id, raw, flags)
            if fallback is not None:
                return fallback, None
            body, problems = self._body(raw, flags, ("corrections",))
            corrections = self._corrections(body.get("corrections"), problems)
            self._fail_unless_flagged(problems, flags)
            if flags:
                reports = self._reports(session.astronaut_id, session.as_of, None, raw, flags)
                escalated = self._turn(session, reports=reports, flags=flags, problems=problems + (
                    ["confirm: not saved because the request had problems"] if problems else []))
                if problems:
                    return escalated, None
                session = self._open(session_id)
            return self._confirm(session, corrections)

    @staticmethod
    def _corrections(value: Any, problems: list[str]) -> dict[SignalType, int]:
        """Symptom signal -> whole number 0-3. Booleans, strings and floats are refused."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            problems.append("corrections must be an object like {\"symptom_fatigue\": 2}")
            return {}
        clean: dict[SignalType, int] = {}
        for raw_signal, severity in value.items():
            try:
                signal = SignalType(raw_signal)
            except ValueError:
                problems.append(f"'{raw_signal}' is not a signal")
                continue
            if get_spec(signal).category is not SignalCategory.SYMPTOM:
                problems.append(f"{signal.value} is not a symptom; corrections take the 8 symptoms")
            elif type(severity) is not int or not 0 <= severity <= 3:
                problems.append(f"severity for {signal.value} must be a whole number 0-3; got {severity!r}")
            else:
                clean[signal] = severity
        return clean

    def _confirm(self, session: TriageSession, corrections: Mapping[SignalType, int]
                 ) -> tuple[TriageResult, DayResult]:
        previous = session.result
        findings = list(previous.findings)
        for signal, severity in corrections.items():
            findings = _set_severity(findings, signal, severity)

        aid, as_of = session.astronaut_id, session.as_of
        stamp = f"{as_of:%Y%m%dT%H%M%S}"
        self.store.add_observations([
            Observation(observation_id=f"{aid}-{f.signal.value}-{stamp}", astronaut_id=aid,
                        timestamp=as_of, signal=f.signal, value=_checkin_value(f), source="checkin",
                        note=f"triage {session.session_id}")
            for f in findings if f.signal is not None
        ])
        day = self.pipeline.assess(aid, as_of)  # saved: hooks and auto-send run as for any check-in

        errors: list[str] = []
        ctx = self.pipeline.context(aid, as_of)
        evidence = TriageEvidence(findings=tuple(findings), answers=session.answers,
                                  asked=tuple(a.question_id for a in session.answers),
                                  preview=day.assessment, anomalies=day.anomalies)
        ranking = self._rank(evidence, ctx, errors, session.session_id)
        procedures = self._procedures(previous.red_flags, ranking, day)
        day = day.model_copy(update={"actions": procedures})
        self.store.save_day(day)

        result = TriageResult(
            session_id=session.session_id, astronaut_id=aid, as_of=as_of, status=TriageStatus.CONFIRMED,
            findings=tuple(findings), ranking=ranking, red_flags=previous.red_flags,
            procedures=procedures, errors=tuple(errors), model_version=self.model_version)
        self._save(session.model_copy(update={
            "result": result, "status": TriageStatus.CONFIRMED, "confirmed_as_of": as_of,
            "updated_at": self.clock()}))
        return result, day

    def cancel(self, session_id: str) -> TriageSession:
        """Close without saving anything. Red flags stay on record."""
        return self.cancel_raw(None, session_id, None)

    def cancel_raw(self, astronaut_id: str | None, session_id: str, raw: Any) -> TriageSession:
        """Cancel. A body is not needed; if it carries a red flag, the session is escalated
        instead of cancelled (an urgent message is never closed away)."""
        flags = self.screen(raw)  # the gate, before anything else
        with self._lock(session_id):
            session, fallback = self._session_for_write(astronaut_id, session_id, raw, flags)
            if fallback is not None:
                return self._get(fallback.session_id)
            if flags:
                reports = self._reports(session.astronaut_id, session.as_of, None, raw, flags)
                self._turn(session, reports=reports, flags=flags,
                           problems=["cancel: not cancelled because the message has a red flag"])
                return self._get(session_id)
            return self._close(session, TriageStatus.CANCELLED)

    def session(self, session_id: str) -> TriageSession:
        with self._lock(session_id):
            return self._get(session_id)

    def sessions(self, astronaut_id: str, start: datetime | None = None,
                 end: datetime | None = None) -> list[TriageSession]:
        """One astronaut's sessions started (real time) in [start, end], newest first."""
        listed = []
        for stored in self.store.sessions(astronaut_id, start=start, end=end):
            with self._lock(stored.session_id):  # expiry is a write
                listed.append(self._get(stored.session_id))
        return listed

    def red_flag_at(self, astronaut_id: str, within: timedelta = timedelta(hours=24)) -> datetime | None:
        """Mission time (``as_of``) of the latest session with a red flag started in the last ``within``."""
        since = self.clock() - within
        times = [s.as_of for s in self.store.sessions(astronaut_id, start=since)
                 if s.result is not None and s.result.red_flags]
        return max(times, default=None)

    # ---- one turn -------------------------------------------------------------------------

    def _turn(self, session: TriageSession, *, reports: Sequence[SymptomReport] = (),
              answer: TriageAnswer | None = None, question: TriageQuestion | None = None,
              done: bool = False, flags: Sequence[str] = (), problems: Sequence[str] = ()) -> TriageResult:
        """One turn. The caller holds the session's lock."""
        aid, as_of, sid = session.astronaut_id, session.as_of, session.session_id
        previous = session.result
        errors: list[str] = list(problems)
        findings = list(previous.findings) if previous else []
        red_flags = list(previous.red_flags) if previous else []
        all_reports, answers = list(session.reports), list(session.answers)

        def flag(rule_ids: Iterable[str]) -> None:
            red_flags.extend(r for r in rule_ids if r not in red_flags)

        # 1. fixed red-flag rules, before any model (flags already found by the caller first)
        flag(flags)
        for report in reports:
            all_reports.append(report)
            flag(hit.rule_id for hit in self.red_flags.check_text(report.text))
        if answer is not None:
            answers.append(answer)
            flag(hit.rule_id for hit in self.red_flags.check_answer(question, answer.value))

        # 2. extractor on the new text only, then what the answer says
        ctx = self.pipeline.context(aid, as_of)
        for report in reports:
            new = self._step("extractor", errors, lambda r=report: list(self.extractor.extract(r, ctx)), [],
                             sid)
            findings = _merge_findings(findings, new)
        if answer is not None and answer.value is not None:
            if question.is_symptom_question:
                findings = _set_severity(findings, question.signal, int(answer.value))
            elif question.feature == "one_side" and answer.value is True and question.signal is not None:
                findings = [f.model_copy(update={"side": "one_side"})
                            if f.signal is question.signal and f.side is None else f for f in findings]

        # 3. preview (not saved), then 4. the reasoner
        preview = self._step("preview", errors, lambda: self.pipeline.assess(aid, as_of, save=False), None,
                             sid)
        evidence = TriageEvidence(
            findings=tuple(findings), answers=tuple(answers), asked=tuple(a.question_id for a in answers),
            preview=preview.assessment if preview else None, anomalies=preview.anomalies if preview else ())
        ranking = self._rank(evidence, ctx, errors, sid)
        done = session.done or done
        next_question = None
        if not red_flags and not done:
            next_question = self._step(
                "next_question", errors, lambda: self.reasoner.next_question(evidence, ranking, ctx), None,
                sid)
            if next_question is not None and next_question.question_id in evidence.asked:
                errors.append(f"next_question: asked '{next_question.question_id}' twice; ignored")
                next_question = None

        if red_flags:
            status = TriageStatus.ESCALATED
        elif next_question is not None:
            status = TriageStatus.ASKING
        else:
            status = TriageStatus.READY
        procedures = () if status is TriageStatus.ASKING else self._procedures(red_flags, ranking, preview)
        result = TriageResult(
            session_id=session.session_id, astronaut_id=aid, as_of=as_of, status=status,
            findings=tuple(findings), ranking=ranking, next_question=next_question,
            red_flags=tuple(red_flags), procedures=procedures, errors=tuple(errors),
            model_version=self.model_version)
        saved = self._save(session.model_copy(update={
            "reports": tuple(all_reports), "answers": tuple(answers), "result": result, "status": status,
            "updated_at": self.clock(), "done": done}))
        return saved.result

    def _step(self, name: str, errors: list[str], call: Callable[[], Any], fallback: Any,
              session_id: str) -> Any:
        try:
            return call()
        except Exception as exc:  # a failing module must not stop the chat
            # Sanitised: no message, traceback or input, since those can quote the astronaut's words.
            log.warning("triage step %s failed: %s (session %s)", name, type(exc).__name__, session_id)
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            return fallback

    def _save(self, session: TriageSession) -> TriageSession:
        """Save, merging red flags and reports with what is stored: they only ever grow."""
        stored = self.store.session(session.session_id)
        if stored is not None:
            known = {r.report_id for r in stored.reports}
            reports = stored.reports + tuple(r for r in session.reports if r.report_id not in known)
            update: dict[str, Any] = {"reports": reports}
            stored_flags = stored.result.red_flags if stored.result else ()
            result = session.result
            if result is not None and set(stored_flags) - set(result.red_flags):
                flags = tuple(dict.fromkeys(stored_flags + result.red_flags))
                flag_cards = [self.library.card(self.red_flags.rule(r).card_id) for r in flags]
                status = TriageStatus.ESCALATED if session.is_open else session.status
                update["result"] = result.model_copy(update={
                    "red_flags": flags, "status": status, "next_question": None,
                    "procedures": tuple(merge_procedures(flag_cards, list(result.procedures), [],
                                                         AlertLevel.RED))})
                update["status"] = status
            session = session.model_copy(update=update)
        self.store.save_session(session)
        return session

    def _rank(self, evidence: TriageEvidence, ctx: AssessmentContext,
              errors: list[str], session_id: str) -> tuple[PatternScore, ...]:
        def run() -> tuple[PatternScore, ...]:
            scores = tuple(s.model_copy(update={"label": self.library.label(s.pattern)})
                           for s in self.reasoner.rank(evidence, ctx))
            total = sum(s.probability for s in scores)
            if scores and abs(total - 1.0) > 1e-6:
                raise ValueError(f"ranking probabilities sum to {total:.6f}, not 1")
            return scores
        return self._step("rank", errors, run, (), session_id)

    def _procedures(self, red_flags: Sequence[str], ranking: Sequence[PatternScore],
                    day: DayResult | None) -> tuple[ActionCard, ...]:
        flag_cards = [self.library.card(self.red_flags.rule(r).card_id) for r in red_flags]
        pattern_cards = self.library.pattern_cards(ranking[0].pattern) if ranking else []
        day_cards = list(day.actions) if day is not None else []
        level = day.assessment.level if day is not None and day.assessment is not None else AlertLevel.GREEN
        return tuple(merge_procedures(flag_cards, pattern_cards, day_cards, level))


    # ---- session state --------------------------------------------------------------------

    def _get(self, session_id: str) -> TriageSession:
        session = self.store.session(session_id)
        if session is None:
            raise SessionNotFound(f"unknown triage session '{session_id}'")
        return self._expire(session)

    def _open(self, session_id: str) -> TriageSession:
        session = self._get(session_id)
        if not session.is_open:
            raise SessionClosed(f"session '{session_id}' is {session.status.value}")
        return session

    def _expire(self, session: TriageSession) -> TriageSession:
        if session.is_open and self.clock() - session.updated_at > self.timeout:
            return self._close(session, TriageStatus.EXPIRED, touch=False)
        return session

    def _close(self, session: TriageSession, status: TriageStatus, *, touch: bool = True) -> TriageSession:
        result = session.result
        if result is not None:
            result = result.model_copy(update={"status": status, "next_question": None})
        closed = session.model_copy(update={
            "status": status, "result": result,
            "updated_at": self.clock() if touch else session.updated_at})
        return self._save(closed)
