/**
 * M11 daily check-in: under a minute, with its effect shown at once.
 *
 * Symptoms start at "none" so only changes need a tap; mood and stress are
 * optional and start unanswered (a preset would put words in the
 * astronaut's mouth). Labels, descriptions and scale words come from
 * GET /api/signals. POST /checkin saves the answers and re-assesses; the
 * response is a DayResult shown right here, with the score before and
 * after. If the request fails the form keeps every answer and offers a
 * retry; a 422 lists what is wrong.
 */
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, errorMessages, isNetworkError } from "../../api/client";
import type { CheckIn, DayResult, SignalSpec } from "../../api/types";
import { Corners, Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { PartialNote } from "../../components/StateMessage";
import { formatMissionTime, formatNumber, missionDayToIso } from "../../lib/format";
import { levelCopy, levelInk, levelTint } from "../../lib/levels";
import type { AsyncState } from "../../lib/useAsync";
import { zoneForReading } from "../../lib/zones";
import { useRegistry } from "../../state/registry-context";
import { ActionsPanel } from "../dashboard/Today";
import "../dashboard/Dashboard.css";
import "./Checkin.css";

const NOTE_MAX = 500;
const DEFAULT_TIME = "10:30"; // after the 10:00 daily assessment, so the answers change today's result

type Answers = Record<string, number | null>;

export default function CheckinPage({ astronautId, status }: { astronautId: string; status: AsyncState<DayResult> }) {
  const { registry, member } = useRegistry();
  const astronaut = member(astronautId);
  const symptoms = registry.signals.filter((s) => s.category === "symptom");
  const wellbeing = registry.signals.filter((s) => s.category === "wellbeing");

  return (
    <div className="checkin enter">
      <div className="checkin__head">
        <span className="identity__meta">
          {astronaut?.callsign ?? astronautId} · {astronautId}
        </span>
        <h1 className="identity__name">Daily check-in</h1>
        <p className="checkin__lead">Tap only what changed. Everything starts at “none”.</p>
      </div>
      {/* key: a new astronaut gets a fresh form */}
      <CheckinForm
        key={astronautId}
        astronautId={astronautId}
        symptoms={symptoms}
        wellbeing={wellbeing}
        missionStart={astronaut?.mission_start}
        status={status}
      />
    </div>
  );
}

function CheckinForm({
  astronautId,
  symptoms,
  wellbeing,
  missionStart,
  status,
}: {
  astronautId: string;
  symptoms: SignalSpec[];
  wellbeing: SignalSpec[];
  missionStart: string | undefined;
  status: AsyncState<DayResult>;
}) {
  const [answers, setAnswers] = useState<Answers>(() =>
    Object.fromEntries([
      ...symptoms.map((s) => [s.signal, s.plausible_min] as const),
      ...wellbeing.map((s) => [s.signal, null] as const),
    ]),
  );
  const [note, setNote] = useState("");
  const [day, setDay] = useState<number | null>(null); // null: follow the latest assessment
  const [time, setTime] = useState(DEFAULT_TIME);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<{ saved: DayResult; before: number | null; stamp: string } | null>(null);

  const missionDayValue = day ?? status.data?.mission_day ?? 1;
  // Without a mission start the server stamps the check-in itself.
  const timestamp = missionStart ? missionDayToIso(missionDayValue, time, missionStart) : null;
  const reported = symptoms.filter((s) => (answers[s.signal] ?? s.plausible_min) > s.plausible_min);

  const set = (signal: string, value: number | null) => setAnswers((prev) => ({ ...prev, [signal]: value }));

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (sending) return;
    const body: CheckIn = {
      timestamp,
      symptoms: Object.fromEntries(symptoms.map((s) => [s.signal, answers[s.signal] ?? s.plausible_min])),
      mood: answers["mood"] ?? null,
      stress: answers["stress"] ?? null,
      note: note.trim() || null,
    };
    const before = status.data?.assessment?.score ?? null;
    setSending(true);
    setError(null);
    try {
      const saved = await api.checkin(astronautId, body);
      setResult({ saved, before, stamp: timestamp ? formatMissionTime(timestamp) : formatMissionTime(saved.as_of) });
      status.reload(); // header, dashboard and history pick up the new result
      window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    } catch (err) {
      setError(err); // answers stay as they are, ready for a retry
    } finally {
      setSending(false);
    }
  };

  if (result) {
    return <CheckinResult result={result.saved} before={result.before} stamp={result.stamp} onEdit={() => setResult(null)} />;
  }

  return (
    <form className="checkin__layout" onSubmit={submit} noValidate>
      <div className="checkin__questions">
        <Frame as="fieldset" className="checkin__group">
          <legend className="section-label">Symptoms</legend>
          {symptoms.map((s) => (
            <ScaleQuestion key={s.signal} spec={s} value={answers[s.signal] ?? s.plausible_min} onChange={(v) => set(s.signal, v)} />
          ))}
        </Frame>

        <Frame as="fieldset" className="checkin__group">
          <legend className="section-label">
            How you feel <span className="checkin__optional">optional</span>
          </legend>
          {wellbeing.map((s) => (
            <ScaleQuestion key={s.signal} spec={s} value={answers[s.signal]} onChange={(v) => set(s.signal, v)} optional />
          ))}
          <label className="field checkin__note">
            <span className="field__label">Note for the medical officer (optional)</span>
            <textarea
              className="input"
              value={note}
              maxLength={NOTE_MAX}
              rows={3}
              onChange={(e) => setNote(e.target.value)}
              placeholder="For example: itchy patch on my left side"
            />
            <span className="checkin__count data" aria-live="polite">
              {note.length} / {NOTE_MAX}
            </span>
          </label>
        </Frame>
      </div>

      <Frame as="aside" className="review" aria-labelledby="review-heading">
        <span id="review-heading" className="kicker">
          Review &amp; save
        </span>
        <div className="review__count" aria-live="polite">
          <span className="figure review__figure">{String(reported.length).padStart(2, "0")}</span>
          <span className="secondary">
            {reported.length === 0
              ? "No symptoms reported."
              : `symptom${reported.length === 1 ? "" : "s"} reported: ${reported.map((s) => s.label.toLowerCase()).join(", ")}.`}
          </span>
        </div>
        <div className="review__when">
          <label className="field">
            <span className="field__label">Mission day</span>
            <input
              className="input data"
              type="number"
              min={1}
              value={missionDayValue}
              onChange={(e) => setDay(Math.max(1, Number(e.target.value) || 1))}
            />
          </label>
          <label className="field">
            <span className="field__label">Time (UTC)</span>
            <input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value || DEFAULT_TIME)} />
          </label>
        </div>
        <p className="review__stamp">
          {timestamp ? (
            <>
              Stamped with mission time: <span className="data">{formatMissionTime(timestamp)}</span>. The demo mission runs in 2027.
            </>
          ) : (
            "The check-in will be stamped with the current time."
          )}
        </p>
        {error !== null && <SubmitError error={error} onRetry={() => void submit()} />}
        <button type="submit" className="btn btn-primary blueprint review__save" disabled={sending}>
          <Corners />
          {sending ? "Saving check-in…" : "Save check-in"}
        </button>
      </Frame>
    </form>
  );
}

/** One question on a word scale: a joined row of radio buttons, each with its state shape. */
function ScaleQuestion({
  spec,
  value,
  onChange,
  optional = false,
}: {
  spec: SignalSpec;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  optional?: boolean;
}) {
  const name = useId();
  const words = spec.scale_labels ?? [];
  return (
    <div className="scale" role="radiogroup" aria-labelledby={`${name}-label`} aria-describedby={`${name}-desc`}>
      <div className="scale__text">
        <span id={`${name}-label`} className="scale__label">
          {spec.label}
        </span>
        <span id={`${name}-desc`} className="scale__desc">
          {spec.description}
        </span>
      </div>
      <div className="scale__controls">
        <div className="scale__options">
          {words.map((word, i) => {
            const optionValue = spec.plausible_min + i;
            const zone = zoneForReading(optionValue, spec, undefined) ?? "green";
            const checked = value === optionValue;
            return (
              <label
                key={word}
                className="scale__option"
                data-checked={checked || undefined}
                style={checked ? { background: levelTint(zone, 22), boxShadow: `inset 0 -2px 0 ${levelInk(zone)}` } : undefined}
              >
                <input type="radio" name={name} value={optionValue} checked={checked} onChange={() => onChange(optionValue)} />
                <LevelIcon level={zone} size={11} />
                <span>{word.charAt(0).toUpperCase() + word.slice(1)}</span>
              </label>
            );
          })}
        </div>
        {optional && value !== null && value !== undefined && (
          <button type="button" className="btn btn-ghost" onClick={() => onChange(null)}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

function SubmitError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const network = isNetworkError(error);
  return (
    <div className="checkin__error" role="alert">
      <p className="checkin__error-title">
        {network ? "Couldn't reach ORBIT. Your answers are still here." : "The check-in wasn't saved."}
      </p>
      <ul>
        {(network ? ["Check that the backend is running, then try again."] : errorMessages(error)).map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
      <button type="button" className="btn btn-secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

/** What the check-in changed: new level, score before → after, top three reasons, action cards. */
function CheckinResult({
  result,
  before,
  stamp,
  onEdit,
}: {
  result: DayResult;
  before: number | null;
  stamp: string;
  onEdit: () => void;
}) {
  const assessment = result.assessment;
  const level = assessment?.level ?? "green";
  const reasons = (assessment?.contributors ?? []).slice(0, 3);
  return (
    <div className="checkin__result">
      <div className="saved" role="status">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 6 9 17l-5-5" />
        </svg>
        <span className="saved__text">Check-in saved {stamp}. Here is your updated status.</span>
        <span className="saved__actions">
          <Link className="btn btn-primary" to={{ pathname: "/", search: `?astronaut=${encodeURIComponent(result.astronaut_id)}` }}>
            Open dashboard
          </Link>
          <button type="button" className="btn btn-secondary" onClick={onEdit}>
            Change answers
          </button>
        </span>
      </div>

      <div className="checkin__layout">
        <div className="checkin__questions">
          {assessment ? (
            <Frame className="after">
              <div className="after__level">
                <LevelIcon level={level} size={36} />
                <div className="after__words">
                  <span className="after__word" style={{ color: levelInk(level) }}>
                    {levelCopy(level).word}
                  </span>
                  <span className="after__meaning">{levelCopy(level).meaning}</span>
                </div>
              </div>
              <div className="after__score">
                <span className="kicker">Score</span>
                <span className="figure after__figure">
                  {before !== null ? `${formatNumber(before, 0)} → ` : ""}
                  {formatNumber(assessment.score, 0)}
                </span>
                <span className="secondary">{before !== null ? "Before → after this check-in" : "After this check-in"}</span>
              </div>
            </Frame>
          ) : (
            <PartialNote errors={["No score could be computed for this check-in."]} />
          )}
          <section className="top-reasons" aria-labelledby="top-reasons">
            <h2 id="top-reasons" className="section-label">
              Top reasons
            </h2>
            {reasons.length === 0 ? (
              <p className="secondary">Nothing raised your score.</p>
            ) : (
              <ol className="top-reasons__list">
                {reasons.map((c, i) => (
                  <li key={`${c.label}-${i}`}>
                    <span className="numbered__n data">{String(i + 1).padStart(2, "0")}</span>
                    <span className="top-reasons__label">{c.label}</span>
                    <span className="secondary data">{formatNumber(c.points, 1)} pts</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
          {(result.errors?.length ?? 0) > 0 && <PartialNote errors={result.errors ?? []} />}
        </div>
        <div className="checkin__side">
          <ActionsPanel key={result.as_of} cards={result.actions ?? []} />
        </div>
      </div>
    </div>
  );
}
