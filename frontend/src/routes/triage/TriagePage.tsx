/**
 * M15 chat: the home screen. The astronaut says how they feel, answers a few
 * questions, and gets a report they can correct before saving.
 *
 * POST /triage starts a chat; each open question is answered with
 * POST /answer ({question_id, value}); text typed after the start goes as
 * {text}. When the chat is ready (or escalated), ORBIT's last message is the
 * report: symptoms (editable), the other answers (read-only: the API only
 * takes an answer to the open question), the patterns ORBIT sees (never a
 * diagnosis, never a percentage) and what to do. Nothing becomes a check-in
 * until "Save to my check-in" (POST /confirm), which re-assesses; its `day`
 * is the new result, shown in the same card with the score before → after.
 *
 * - The session lives in the URL (`?session=<id>`), so a reload resumes it.
 *   The transcript is kept per tab in sessionStorage; without it, a reload
 *   rebuilds it from the stored session (question text is not stored by the API).
 * - "Before" is read once, when the chat starts: the latest saved assessment
 *   at or before the chat's `as_of`. Never after confirm, when the new one exists.
 * - Symptom edits are corrections sent with confirm. The API cannot drop a
 *   finding: "I don't have this" saves severity 0, and complaints outside the
 *   8 signals cannot be removed.
 * - A red flag (status "escalated") replaces the conversation with the red
 *   banner and the report, and asks no more questions; saving stays possible.
 * - A failed request keeps the words and answers and offers a retry.
 */
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api, errorMessages, isNetworkError } from "../../api/client";
import type {
  ActionCard,
  DayResult,
  PatternScore,
  SignalSpec,
  SymptomFinding,
  TriageQuestion,
  TriageResult,
  TriageSession,
  TriageStatus,
} from "../../api/types";
import { LevelIcon } from "../../components/LevelIcon";
import { MissionTimePicker } from "../../components/MissionTimePicker";
import { ScaleQuestion } from "../../components/ScaleQuestion";
import { SeverityDots } from "../../components/SeverityDots";
import { Loading, PartialNote } from "../../components/StateMessage";
import { formatMissionTime, formatNumber, humanize, missionDayToIso } from "../../lib/format";
import { levelCopy, levelInk } from "../../lib/levels";
import { severitySteps } from "../../lib/severity";
import type { AsyncState } from "../../lib/useAsync";
import { useRegistry } from "../../state/registry-context";
import { ActionsPanel } from "../dashboard/Today";
import "../dashboard/Dashboard.css";
import "../checkin/Checkin.css";
import "./Triage.css";

const TEXT_MAX = 1000;
/** The character counter appears only near the limit. */
const COUNT_FROM = 900;
const DEFAULT_TIME = "10:30"; // after the 10:00 daily assessment, like the quick form
/** Pattern words: never a percentage. Below POSSIBLE a pattern is not shown. */
const LIKELY = 0.6;
const POSSIBLE = 0.2;
const OPEN: readonly TriageStatus[] = ["asking", "ready", "escalated"];
/** Red-flag cards are the ones whose id starts with "rf-" (SPEC M15). */
const isRedFlagCard = (card: ActionCard) => card.card_id.startsWith("rf-");

type Before = { state: "loading" } | { state: "known"; score: number | null; at: string | null } | { state: "unavailable" };
type Action = "start" | "text" | "answer" | "confirm" | "cancel";
interface Failure {
  action: Action;
  error: unknown;
  retry: () => void;
}

/** One bubble in the conversation. The open question is not a turn: it is drawn from the result. */
interface Turn {
  who: "me" | "orbit";
  text: string;
}

/** One answered question, for "Your answers" in the report. `feature`: not a symptom question. */
interface AnswerRow {
  questionId: string;
  question: string;
  answer: string;
  feature: boolean;
}

interface Transcript {
  turns: Turn[];
  answers: AnswerRow[];
}

const EMPTY: Transcript = { turns: [], answers: [] };

// ---- the transcript, per tab (a per-viewer convenience; the session itself is on the server) ----

const storageKey = (sessionId: string) => `orbit.chat.${sessionId}`;

function loadTranscript(sessionId: string): Transcript | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Transcript;
    return Array.isArray(parsed.turns) && Array.isArray(parsed.answers) ? parsed : null;
  } catch {
    return null;
  }
}

function saveTranscript(sessionId: string, transcript: Transcript) {
  try {
    window.sessionStorage.setItem(storageKey(sessionId), JSON.stringify(transcript));
  } catch {
    // storage blocked or full: the chat still works, a reload rebuilds it from the session
  }
}

/** Without a stored transcript: the words first, then each answer (the API keeps no question text). */
function rebuildTranscript(session: TriageSession): Transcript {
  const turns: Turn[] = session.reports.map((r) => ({ who: "me", text: r.text }));
  const answers: AnswerRow[] = [];
  for (const a of session.answers) {
    // The API stores yes/no answers as true/false.
    const answer =
      a.value === null || a.value === undefined
        ? "Skipped"
        : typeof a.value === "boolean"
          ? a.value
            ? "Yes"
            : "No"
          : capitalize(String(a.value));
    const question = humanize(a.question_id);
    turns.push({ who: "orbit", text: question }, { who: "me", text: answer });
    // Symptom answers are numbers (0-3); feature answers are words (yes, no, a choice).
    if (typeof a.value !== "number") answers.push({ questionId: a.question_id, question, answer, feature: true });
  }
  return { turns, answers };
}

export default function TriagePage({ astronautId, status }: { astronautId: string; status: AsyncState<DayResult> }) {
  const { member } = useRegistry();
  const astronaut = member(astronautId);
  const [params] = useSearchParams();
  return (
    <div className="chat enter">
      {/* key: another astronaut gets a fresh chat */}
      <Chat
        key={astronautId}
        astronautId={astronautId}
        missionStart={astronaut?.mission_start}
        status={status}
        sessionId={params.get("session")}
      />
    </div>
  );
}

function Chat({
  astronautId,
  missionStart,
  status,
  sessionId,
}: {
  astronautId: string;
  missionStart: string | undefined;
  status: AsyncState<DayResult>;
  sessionId: string | null;
}) {
  const [, setParams] = useSearchParams();
  const [result, setResult] = useState<TriageResult | null>(null);
  const [closed, setClosed] = useState<TriageSession | null>(null); // cancelled, expired, or confirmed in an earlier visit
  const [confirmed, setConfirmed] = useState<{ day: DayResult; before: number | null } | null>(null);
  const [transcript, setTranscript] = useState<Transcript>(EMPTY);
  const [text, setText] = useState("");
  const [day, setDay] = useState<number | null>(null); // null: follow the latest assessment
  const [time, setTime] = useState(DEFAULT_TIME);
  const [before, setBefore] = useState<Before>({ state: "loading" });
  const [corrections, setCorrections] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<Action | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [notSaved, setNotSaved] = useState<readonly string[] | null>(null);
  const [restore, setRestore] = useState<{ id: string; error: unknown } | null>(null);
  const [restoreTick, setRestoreTick] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);

  const missionDayValue = day ?? status.data?.mission_day ?? 1;
  // Without a mission start the server stamps the chat itself.
  const timestamp = missionStart ? missionDayToIso(missionDayValue, time, missionStart) : null;
  const sid = result?.session_id ?? closed?.session_id ?? null;

  // Keep the transcript with the session, so a reload in this tab shows the same conversation.
  useEffect(() => {
    if (sid && transcript.turns.length > 0) saveTranscript(sid, transcript);
  }, [sid, transcript]);

  // Each new message scrolls into view.
  const lastKey = `${transcript.turns.length}:${result?.status}:${result?.next_question?.question_id}:${confirmed ? 1 : 0}`;
  useEffect(() => {
    if (transcript.turns.length === 0) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    endRef.current?.scrollIntoView({ block: "end", behavior: reduce ? "auto" : "smooth" });
  }, [lastKey, transcript.turns.length]);

  /** The score before this chat: the latest saved assessment at or before its as_of. Read before any confirm. */
  const readBefore = (asOf: string) => {
    setBefore({ state: "loading" });
    api.assessments(astronautId, undefined, asOf).then(
      (list) => {
        const latest = list.reduce<(typeof list)[number] | undefined>(
          (best, a) => (!best || Date.parse(a.assessed_at) > Date.parse(best.assessed_at) ? a : best),
          undefined,
        );
        setBefore({ state: "known", score: latest?.score ?? null, at: latest?.assessed_at ?? null });
      },
      () => setBefore({ state: "unavailable" }),
    );
  };

  /** Show a stored session: open ones continue, closed ones say what happened. */
  const adopt = (session: TriageSession) => {
    setTranscript(loadTranscript(session.session_id) ?? rebuildTranscript(session));
    setCorrections({});
    if (OPEN.includes(session.status) && session.result) {
      setClosed(null);
      setResult(session.result);
      readBefore(session.as_of);
      return;
    }
    setResult(session.result ?? null);
    setClosed(session);
    if (session.status === "confirmed") {
      // Saved in an earlier visit: show the saved run. No "before" (it would be read after confirm).
      api.day(astronautId, session.confirmed_as_of ?? session.as_of).then(
        (saved) => setConfirmed({ day: saved, before: null }),
        () => undefined, // the closed message still says it was saved
      );
    }
  };

  // Resume the chat named in the URL (reload, shared link, back button).
  const adoptRef = useRef(adopt);
  useEffect(() => {
    adoptRef.current = adopt;
  });
  const needsRestore = sessionId !== null && result?.session_id !== sessionId && closed?.session_id !== sessionId;
  useEffect(() => {
    if (!needsRestore || sessionId === null) return;
    const controller = new AbortController();
    api.triageSession(astronautId, sessionId, controller.signal).then(
      (session) => adoptRef.current(session),
      (error: unknown) => {
        if (!controller.signal.aborted) setRestore({ id: sessionId, error });
      },
    );
    return () => controller.abort();
  }, [astronautId, sessionId, needsRestore, restoreTick]);

  const setSession = (id: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("session", id);
        else next.delete("session");
        return next;
      },
      { replace: id === null },
    );

  /** Run one request; on failure keep everything on screen and offer a retry. */
  const run = async (action: Action, call: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    setFailure(null);
    setNotSaved(null);
    try {
      await call();
    } catch (error) {
      setFailure({ action, error, retry: () => void run(action, call) });
      // 409: the chat closed (expired, or saved/cancelled elsewhere). Show its real state.
      if (error instanceof ApiError && error.status === 409 && result) {
        api.triageSession(astronautId, result.session_id).then(adopt, () => undefined);
      }
    } finally {
      setBusy(null);
    }
  };

  const newChat = () => {
    setResult(null);
    setClosed(null);
    setConfirmed(null);
    setTranscript(EMPTY);
    setCorrections({});
    setFailure(null);
    setNotSaved(null);
    setRestore(null);
    setBefore({ state: "loading" });
    setSession(null);
  };

  const open = result !== null && OPEN.includes(result.status) && !closed;

  /** The composer: the first message starts the chat, later ones go as {text}. */
  const send = (event?: FormEvent) => {
    event?.preventDefault();
    const words = text.trim();
    if (!words) return;
    if (!result) {
      void run("start", async () => {
        const started = await api.triageStart(astronautId, { text: words, timestamp });
        setResult(started);
        setClosed(null);
        setConfirmed(null);
        setTranscript({ turns: [{ who: "me", text: words }], answers: [] });
        setCorrections({});
        setText("");
        readBefore(started.as_of);
        setSession(started.session_id);
      });
      return;
    }
    if (!open) return;
    void run("text", async () => {
      setResult(await api.triageAnswer(astronautId, result.session_id, { text: words }));
      setTranscript((prev) => ({ ...prev, turns: [...prev.turns, { who: "me", text: words }] }));
      setText("");
    });
  };

  // ---- loading and restore states ----
  if (sessionId && restore?.id === sessionId) {
    return (
      <RestoreError
        error={restore.error}
        onRetry={() => {
          setRestore(null);
          setRestoreTick((n) => n + 1);
        }}
        onNew={newChat}
      />
    );
  }
  if (sessionId && !result && !closed) return <Loading what="your chat" />;

  const escalated = result !== null && (result.status === "escalated" || result.red_flags.length > 0);
  const question = open && result?.status === "asking" ? (result.next_question ?? null) : null;
  const showReport = result !== null && (confirmed !== null || (open && result.status !== "asking"));
  const redCards = result?.procedures.filter(isRedFlagCard) ?? [];
  const started = result !== null || closed !== null;
  // The pinned composer, while the chat is open (not after a red flag). Before the start it sits in the empty state.
  const composer = started && !confirmed && open && !escalated;

  const answer = (q: TriageQuestion, value: string | number | null, label: string) =>
    void run("answer", async () => {
      const next = await api.triageAnswer(astronautId, result!.session_id, { question_id: q.question_id, value });
      setResult(next);
      setTranscript((prev) => ({
        turns: [...prev.turns, { who: "orbit", text: q.text }, { who: "me", text: label }],
        answers: [...prev.answers, { questionId: q.question_id, question: q.text, answer: label, feature: q.feature != null }],
      }));
    });
  const finish = () =>
    void run("answer", async () => {
      setResult(await api.triageAnswer(astronautId, result!.session_id, { done: true }));
      setTranscript((prev) => ({ ...prev, turns: [...prev.turns, { who: "me", text: "That’s all" }] }));
    });
  const confirm = () =>
    void run("confirm", async () => {
      const body = Object.keys(corrections).length > 0 ? { corrections } : {};
      const saved = await api.triageConfirm(astronautId, result!.session_id, body);
      setResult(saved.result);
      if (!saved.day) {
        // A red flag in the request escalated the chat instead of saving it.
        setNotSaved(saved.result.errors.length > 0 ? saved.result.errors : ["ORBIT found a red flag and did not save."]);
        return;
      }
      setConfirmed({ day: saved.day, before: before.state === "known" ? before.score : null });
      // The top bar shows the latest result: take the new one only if it is the latest.
      if (status.data && Date.parse(saved.day.as_of) >= Date.parse(status.data.as_of)) status.replace(saved.day);
    });
  const discard = () =>
    void run("cancel", async () => {
      adopt(await api.triageCancel(astronautId, result!.session_id));
    });

  // What screen readers hear when ORBIT says something new.
  const announce = confirmed
    ? "Saved to your check-in."
    : escalated
      ? "" // the red banner is an alert of its own
      : question
        ? question.text
        : showReport
          ? "Your report is ready. Check it, then save."
          : "";

  return (
    <>
      <p className="visually-hidden" aria-live="polite" aria-atomic="true">
        {announce}
      </p>

      {!started ? (
        <EmptyState
          missionDay={missionDayValue}
          time={time}
          timestamp={timestamp}
          onDay={setDay}
          onTime={setTime}
          astronautId={astronautId}
        >
          {failure && <ChatError failure={failure} />}
          <Composer value={text} onChange={setText} onSend={send} busy={busy === "start"} disabled={busy !== null} first />
        </EmptyState>
      ) : (
        <h1 className="visually-hidden">Chat with ORBIT</h1>
      )}

      {escalated && !confirmed && <RedFlagBanner cards={redCards} />}

      {started && !(escalated && !confirmed) && (
        <ol className="thread" aria-label="Conversation">
          {(result ?? closed) && (
            <li className="thread__stamp caption data">{formatMissionTime((result ?? closed)!.as_of)}</li>
          )}
          {transcript.turns.map((t, i) => (
            <li key={i} className={`bubble bubble--${t.who}`}>
              <span className="visually-hidden">{t.who === "me" ? "You: " : "ORBIT: "}</span>
              {t.text}
            </li>
          ))}
          {question && (
            <li className="thread__ask">
              <QuestionBubble key={question.question_id} question={question} busy={busy !== null} onAnswer={answer} onDone={finish} />
            </li>
          )}
          {failure && (failure.action === "answer" || failure.action === "text" || failure.action === "start") && (
            <li className="thread__error">
              <ChatError failure={failure} />
            </li>
          )}
        </ol>
      )}

      {showReport && result && (
        <div className="thread__report">
          {confirmed ? (
            <SavedReport day={confirmed.day} before={confirmed.before} onNew={newChat} />
          ) : (
            <Report
              result={result}
              escalated={escalated}
              answers={transcript.answers}
              corrections={corrections}
              setCorrections={setCorrections}
              before={before}
              busy={busy}
              failure={failure?.action === "confirm" || failure?.action === "cancel" ? failure : null}
              notSaved={notSaved}
              onConfirm={confirm}
              onDiscard={discard}
            />
          )}
        </div>
      )}

      {closed && !confirmed && <ClosedChat session={closed} failure={failure} onNew={newChat} />}

      <div ref={endRef} />

      {composer && (
        <Composer value={text} onChange={setText} onSend={send} busy={busy === "text"} disabled={busy !== null} first={false} pinned />
      )}
    </>
  );
}

// ---- pieces ------------------------------------------------------------------------

function EmptyState({
  missionDay,
  time,
  timestamp,
  onDay,
  onTime,
  astronautId,
  children,
}: {
  missionDay: number;
  time: string;
  timestamp: string | null;
  onDay: (day: number) => void;
  onTime: (time: string) => void;
  astronautId: string;
  children: ReactNode;
}) {
  return (
    <div className="chat-empty">
      <span className="chat-empty__mark" aria-hidden="true">
        <svg width="40" height="40" viewBox="0 0 32 32">
          <circle cx="16" cy="16" r="4.5" className="brand__core" />
          <ellipse cx="16" cy="16" rx="13" ry="6" className="brand__orbit" transform="rotate(-25 16 16)" />
        </svg>
      </span>
      <h1 className="large-title chat-empty__title">How are you feeling today?</h1>
      {timestamp ? (
        <MissionTimePicker day={missionDay} time={time} onDay={onDay} onTime={onTime} defaultTime={DEFAULT_TIME} />
      ) : (
        <p className="caption">The chat will be stamped with the current time.</p>
      )}
      <div className="chat-empty__compose">{children}</div>
      <p className="chat-empty__hint caption">
        Say it in your own words. Nothing is saved until you check the report.{" "}
        <Link to={{ pathname: "/checkin", search: `?astronaut=${encodeURIComponent(astronautId)}` }}>Use the quick form instead</Link>
      </p>
    </div>
  );
}

/** Pinned to the bottom. Enter sends, Shift+Enter adds a line. The counter shows only near the limit. */
function Composer({
  value,
  onChange,
  onSend,
  busy,
  disabled,
  first,
  pinned = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: (event?: FormEvent) => void;
  busy: boolean;
  disabled: boolean;
  first: boolean;
  /** Pinned to the bottom of the screen once the chat has started. */
  pinned?: boolean;
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!disabled) onSend();
    }
  };
  const near = value.length >= COUNT_FROM;
  return (
    <form className={`composer${pinned ? " composer--pinned" : ""}`} onSubmit={onSend}>
      <div className="composer__box">
        <label className="visually-hidden" htmlFor="composer-text">
          {first ? "How you feel" : "Add something"}
        </label>
        <textarea
          id="composer-text"
          className="composer__text"
          rows={1}
          value={value}
          maxLength={TEXT_MAX}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={first ? "For example: tingly patch on my ribs since last night, and pretty tired" : "Add something…"}
          aria-describedby={near ? "composer-count" : undefined}
        />
        <button type="submit" className="composer__send" disabled={disabled || !value.trim()}>
          <span>{busy ? "Sending…" : "Send"}</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 19V5M6 11l6-6 6 6" />
          </svg>
        </button>
      </div>
      {near && (
        <span id="composer-count" className="composer__count caption data" aria-live="polite">
          {value.length} / {TEXT_MAX}
        </span>
      )}
    </form>
  );
}

/** ORBIT's open question as a bubble, with large answer buttons under it. */
function QuestionBubble({
  question,
  busy,
  onAnswer,
  onDone,
}: {
  question: TriageQuestion;
  busy: boolean;
  onAnswer: (q: TriageQuestion, value: string | number | null, label: string) => void;
  onDone: () => void;
}) {
  const { spec } = useRegistry();
  const [reading, setReading] = useState("");
  const s = question.signal ? spec(question.signal) : undefined;

  let answers: { label: string; value: string | number; steps?: number }[] = [];
  if (question.answer_type === "yes_no") {
    answers = [
      { label: "Yes", value: "yes" },
      { label: "No", value: "no" },
    ];
  } else if (question.answer_type === "scale_0_3") {
    // A symptom question uses the signal's scale words from /api/signals.
    const words = s?.scale_labels ?? question.choices;
    answers = words.map((w, i) => ({
      label: capitalize(w),
      value: i,
      steps: s ? severitySteps(s.plausible_min + i, s) : i,
    }));
  } else if (question.answer_type === "choice") {
    answers = question.choices.map((c) => ({ label: capitalize(c), value: c }));
  }

  return (
    <div className="ask" role="group" aria-labelledby={`q-${question.question_id}`}>
      <p id={`q-${question.question_id}`} className="bubble bubble--orbit">
        <span className="visually-hidden">ORBIT: </span>
        {question.text}
      </p>
      {question.answer_type === "reading" ? (
        <form
          className="ask__reading"
          onSubmit={(e) => {
            e.preventDefault();
            if (reading.trim()) onAnswer(question, Number(reading), reading.trim());
          }}
        >
          <input className="input data" type="number" inputMode="decimal" value={reading} onChange={(e) => setReading(e.target.value)} aria-label="Reading" />
          <button type="submit" className="btn btn-secondary" disabled={busy || !reading.trim()}>
            Send
          </button>
        </form>
      ) : (
        <div className="ask__answers">
          {answers.map((a) => (
            <button key={String(a.value)} type="button" className="answer-btn" disabled={busy} onClick={() => onAnswer(question, a.value, a.label)}>
              {a.steps !== undefined && <SeverityDots steps={a.steps} size={7} />}
              {a.label}
            </button>
          ))}
        </div>
      )}
      <div className="ask__foot">
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => onAnswer(question, null, "Skipped")}>
          Skip
        </button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={onDone}>
          That’s all
        </button>
      </div>
    </div>
  );
}

/** A red flag replaces the conversation: one full-width banner with its card. */
function RedFlagBanner({ cards }: { cards: readonly ActionCard[] }) {
  const first = cards[0];
  const level = first?.level ?? "red";
  const tell = [...new Set(cards.map((c) => c.escalate_to ?? "self").filter((t) => t !== "self"))];
  return (
    <section className="redflag" role="alert" aria-labelledby="redflag-title">
      <div className="redflag__head">
        <LevelIcon level={level} size={28} />
        <div className="redflag__words">
          <span className="redflag__level" style={{ color: levelInk(level) }}>
            {levelCopy(level).word} · {levelCopy(level).meaning}
          </span>
          <h2 id="redflag-title" className="title">
            {first?.title ?? "Get medical help now"}
          </h2>
        </div>
      </div>
      {cards.map((card) => (
        <ol key={card.card_id} className="redflag__steps">
          {(card.steps ?? []).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ))}
      {tell.length > 0 && (
        <p className="redflag__tell">
          Tell the <strong>{tell.map((t) => humanize(t).toLowerCase()).join(" and the ")}</strong> now.
        </p>
      )}
      <p className="secondary">ORBIT asks no more questions. You can still save your report below.</p>
    </section>
  );
}

/** ORBIT's last message: the one thing the astronaut reviews before saving. */
function Report({
  result,
  escalated,
  answers,
  corrections,
  setCorrections,
  before,
  busy,
  failure,
  notSaved,
  onConfirm,
  onDiscard,
}: {
  result: TriageResult;
  escalated: boolean;
  answers: readonly AnswerRow[];
  corrections: Record<string, number>;
  setCorrections: (update: (prev: Record<string, number>) => Record<string, number>) => void;
  before: Before;
  busy: Action | null;
  failure: Failure | null;
  notSaved: readonly string[] | null;
  onConfirm: () => void;
  onDiscard: () => void;
}) {
  const { spec } = useRegistry();
  const symptoms = result.findings.filter((f) => f.signal);
  const officer = result.findings.filter((f) => !f.signal);
  const other = answers.filter((a) => a.feature);
  const cards = result.procedures.filter((c) => !isRedFlagCard(c));

  const correct = (signal: string, value: number | null, saved: number | null) =>
    setCorrections((prev) => {
      const next = { ...prev };
      if (value === null || value === saved) delete next[signal];
      else next[signal] = value;
      return next;
    });

  return (
    <article className="report" aria-labelledby="report-title">
      <header className="report__head">
        <span className="kicker">ORBIT</span>
        <h2 id="report-title" className="title">
          Your report
        </h2>
        <p className="secondary">Check it and correct anything, then save it to your check-in.</p>
      </header>

      <section className="report__part" aria-labelledby="report-symptoms">
        <h3 id="report-symptoms" className="headline">
          Symptoms
        </h3>
        {symptoms.length === 0 && <p className="secondary">No symptoms. Saving still re-assesses.</p>}
        {symptoms.map((f) => {
          const signal = f.signal!;
          const s = spec(signal);
          const saved = savedValue(f);
          const edited = signal in corrections;
          const shown = edited ? corrections[signal] : saved;
          return (
            <SymptomRow
              key={signal}
              spec={s}
              label={s?.label ?? f.label}
              value={shown}
              edited={edited}
              onChange={(v) => correct(signal, v, saved)}
              onUndo={() => correct(signal, null, saved)}
            />
          );
        })}
        {officer.length > 0 && (
          <div className="report__officer">
            <h4 className="report__sub">For the medical officer</h4>
            <ul className="report__list">
              {officer.map((f, i) => (
                <li key={`${f.label}-${i}`}>
                  {f.label}
                  {f.body_site && <span className="secondary"> · {f.body_site}</span>}
                </li>
              ))}
            </ul>
            <p className="caption">Kept with this chat. Cancelling keeps it out of your check-in.</p>
          </div>
        )}
      </section>

      {other.length > 0 && (
        <section className="report__part" aria-labelledby="report-answers">
          <h3 id="report-answers" className="headline">
            Your answers
          </h3>
          <dl className="report__answers">
            {other.map((a) => (
              <div key={a.questionId}>
                <dt>{a.question}</dt>
                <dd>{a.answer}</dd>
              </div>
            ))}
          </dl>
          <p className="caption">ORBIT takes an answer only while its question is open, so these can’t be changed here. To change one, discard and start a new chat.</p>
        </section>
      )}

      {!escalated && <Patterns ranking={result.ranking} />}

      {cards.length > 0 && (
        <section className="report__part" aria-labelledby="report-todo">
          <h3 id="report-todo" className="headline">
            What to do
          </h3>
          <ul className="report__todo">
            {cards.map((card) => (
              <li key={card.card_id}>
                <details className="disclosure">
                  <summary>{card.title}</summary>
                  <ol className="report__steps">
                    {(card.steps ?? []).map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}

      {result.errors.length > 0 && <PartialNote errors={result.errors} />}

      <footer className="report__foot">
        <p className="caption">
          {before.state === "loading" && "Reading your score before this chat…"}
          {before.state === "unavailable" && "Your score before this chat couldn’t be read; the result will show the new score only."}
          {before.state === "known" &&
            (before.score === null || before.at === null ? (
              "No saved score before this chat."
            ) : (
              <>
                Your score before this chat: <span className="data">{formatNumber(before.score, 0)}</span> ({formatMissionTime(before.at)}).
              </>
            ))}
        </p>
        {notSaved && (
          <div className="checkin__error" role="alert">
            <p className="checkin__error-title">Not saved: ORBIT found a red flag.</p>
            <ul>
              {notSaved.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </div>
        )}
        {failure && <ChatError failure={failure} />}
        <div className="report__actions">
          <button type="button" className="btn btn-primary" disabled={busy !== null || before.state === "loading"} onClick={onConfirm}>
            {busy === "confirm" ? "Saving…" : "Save to my check-in"}
          </button>
          <button type="button" className="btn btn-ghost" disabled={busy !== null} onClick={onDiscard}>
            {busy === "cancel" ? "Discarding…" : "Discard"}
          </button>
        </div>
      </footer>
    </article>
  );
}

/** One finding: its severity as a segmented control, and "I don't have this" (saves 0). */
function SymptomRow({
  spec,
  label,
  value,
  edited,
  onChange,
  onUndo,
}: {
  spec: SignalSpec | undefined;
  label: string;
  value: number | null;
  edited: boolean;
  onChange: (value: number) => void;
  onUndo: () => void;
}) {
  const none = spec?.plausible_min ?? 0;
  return (
    <div className="symptom" data-edited={edited || undefined}>
      {spec ? (
        <ScaleQuestion spec={{ ...spec, label }} value={value} onChange={(v) => v !== null && onChange(v)} describe={false} />
      ) : (
        <p>{label}</p>
      )}
      <div className="symptom__foot">
        {value === null && <span className="caption">Saved as {scaleWord(spec, none + 1).toLowerCase()} unless you change it.</span>}
        {edited && <span className="caption symptom__edited">Changed. Applies when you save.</span>}
        <span className="symptom__actions">
          {value !== none && (
            <button type="button" className="btn btn-ghost symptom__btn" onClick={() => onChange(none)}>
              I don’t have this
            </button>
          )}
          {edited && (
            <button type="button" className="btn btn-ghost symptom__btn" onClick={onUndo}>
              Undo
            </button>
          )}
        </span>
      </div>
    </div>
  );
}

/** The top patterns in words: "likely" or "possible", with one line of reasons. Never a percentage. */
function Patterns({ ranking }: { ranking: readonly PatternScore[] }) {
  const shown = ranking.slice(0, 3).filter((p) => p.probability >= POSSIBLE);
  if (ranking.length === 0) return null;
  return (
    <section className="report__part" aria-labelledby="report-patterns">
      <h3 id="report-patterns" className="headline">
        What ORBIT sees <span className="report__not">(not a diagnosis)</span>
      </h3>
      {shown.length === 0 ? (
        <p className="secondary">No clear pattern yet.</p>
      ) : (
        <ul className="report__patterns">
          {shown.map((p) => (
            <li key={p.pattern}>
              <span className="report__pattern">
                <span className="report__word">{p.probability >= LIKELY ? "Likely" : "Possible"}</span> {p.label || humanize(p.pattern)}
              </span>
              {p.reasons.length > 0 && <span className="secondary report__reasons">{p.reasons.map((r) => r.label).join(" · ")}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** After saving, the report becomes the result: level, score before → after, the action cards. */
function SavedReport({ day, before, onNew }: { day: DayResult; before: number | null; onNew: () => void }) {
  const assessment = day.assessment;
  const level = assessment?.level ?? "green";
  return (
    <article className="report report--saved" aria-labelledby="saved-title">
      <header className="report__head">
        <span className="kicker">Saved to your check-in · {formatMissionTime(day.as_of)}</span>
        <h2 id="saved-title" className="visually-hidden">
          Your result
        </h2>
      </header>
      {assessment ? (
        <div className="saved-level">
          <LevelIcon level={level} size={40} />
          <div className="saved-level__words">
            <span className="saved-level__word" style={{ color: levelInk(level) }}>
              {levelCopy(level).word}
            </span>
            <span className="secondary">{levelCopy(level).meaning}</span>
          </div>
          <div className="saved-level__score">
            <span className="figure">
              {before !== null ? `${formatNumber(before, 0)} → ` : ""}
              {formatNumber(assessment.score, 0)}
            </span>
            <span className="caption">{before !== null ? "Score before → after" : "Score"}</span>
          </div>
        </div>
      ) : (
        <PartialNote errors={["No score could be computed for this check-in."]} />
      )}
      {(day.errors?.length ?? 0) > 0 && <PartialNote errors={day.errors ?? []} />}
      <ActionsPanel key={day.as_of} cards={day.actions ?? []} />
      <div className="report__actions">
        <button type="button" className="btn btn-primary" onClick={onNew}>
          Start a new chat
        </button>
        <Link className="btn btn-ghost" to={{ pathname: "/today", search: `?astronaut=${encodeURIComponent(day.astronaut_id)}` }}>
          Open Today
        </Link>
      </div>
    </article>
  );
}

const FAILED: Record<Action, string> = {
  start: "Your message wasn't sent.",
  text: "Your words weren't sent.",
  answer: "Your answer wasn't sent.",
  confirm: "The report wasn't saved.",
  cancel: "The chat wasn't discarded.",
};

/** A failed request: what went wrong (409 and 422 messages from the API) and a retry. */
function ChatError({ failure }: { failure: Failure }) {
  const network = isNetworkError(failure.error);
  const closed = failure.error instanceof ApiError && failure.error.status === 409;
  return (
    <div className="checkin__error" role="alert">
      <p className="checkin__error-title">
        {network ? "Couldn't reach ORBIT. Your words and answers are still here." : FAILED[failure.action]}
      </p>
      <ul>
        {(network ? ["Check that the backend is running, then try again."] : errorMessages(failure.error)).map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
      {!closed && (
        <button type="button" className="btn btn-secondary" onClick={failure.retry}>
          Try again
        </button>
      )}
    </div>
  );
}

const CLOSED_COPY: Partial<Record<TriageStatus, { title: string; body: string }>> = {
  cancelled: { title: "Chat discarded", body: "Nothing was saved to your check-in." },
  expired: { title: "This chat timed out", body: "It was open too long without a reply. Nothing was saved to your check-in." },
  confirmed: { title: "This chat was saved", body: "It was saved to your check-in and re-assessed." },
};

function ClosedChat({ session, failure, onNew }: { session: TriageSession; failure: Failure | null; onNew: () => void }) {
  const copy = CLOSED_COPY[session.status] ?? { title: `Chat ${session.status}`, body: "" };
  return (
    <div className="closed" role="status">
      <p className="bubble bubble--orbit">
        <strong>{copy.title}.</strong> {copy.body}
      </p>
      {failure && <ChatError failure={failure} />}
      <button type="button" className="btn btn-primary" onClick={onNew}>
        Start a new chat
      </button>
    </div>
  );
}

function RestoreError({ error, onRetry, onNew }: { error: unknown; onRetry: () => void; onNew: () => void }) {
  const missing = error instanceof ApiError && error.status === 404;
  return (
    <div className="closed" role="alert">
      <h1 className="title">{missing ? "This chat isn't here" : "Couldn't load your chat"}</h1>
      <p className="secondary">
        {missing
          ? "No chat with this link for this astronaut. It may belong to someone else, or the backend was restarted."
          : isNetworkError(error)
            ? "Check that the backend is running, then try again."
            : errorMessages(error).join(" ")}
      </p>
      <div className="closed__actions">
        <button type="button" className="btn btn-primary" onClick={onNew}>
          Start a new chat
        </button>
        {!missing && (
          <button type="button" className="btn btn-secondary" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

// ---- helpers -----------------------------------------------------------------------

/** What confirm would save for a finding without a correction: denied → 0, unrated → null (saved as 1). */
function savedValue(f: SymptomFinding): number | null {
  if (f.negated) return 0;
  return f.severity ?? null;
}

function scaleWord(spec: { scale_labels: string[] | null; plausible_min: number } | undefined, value: number): string {
  const word = spec?.scale_labels?.[value - spec.plausible_min];
  return word ? capitalize(word) : String(value);
}

function capitalize(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}
