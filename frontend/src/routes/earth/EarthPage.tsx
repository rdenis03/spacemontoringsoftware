/**
 * M13 Earth comms: the astronaut decides what leaves the spacecraft, sees
 * exactly what Earth would receive, and sends it through a queue with the
 * one-way communication delay (Moon or Mars).
 *
 * Data: PUT /consent, GET /earth-packet (preview), POST /earth-packet/send,
 * GET /outbox, GET /api/health (default delay). Score and level always
 * travel; reasons from private categories arrive as a neutral label.
 */
import { useMemo, useState } from "react";
import { api, errorMessages } from "../../api/client";
import type { DayResult, EarthPacket, OutboxItem } from "../../api/types";
import { Corners, Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { LevelTag } from "../../components/LevelTag";
import { LoadError, Loading } from "../../components/StateMessage";
import { categoryName, formatMissionTime, formatNumber, missionDay } from "../../lib/format";
import { levelCopy, levelInk, levelRank } from "../../lib/levels";
import type { AsyncState } from "../../lib/useAsync";
import { useAsync } from "../../lib/useAsync";
import { useNow } from "../../lib/useNow";
import { useRegistry } from "../../state/registry-context";
import "../dashboard/Dashboard.css";
import "./Earth.css";

/** Days of data in one report. */
const REPORT_DAYS = 7;
/** Moon: about 1.3 light-seconds one way. */
const MOON_MINUTES = 1.3 / 60;
const OUTBOX_POLL_MS = 10_000;

export default function EarthPage({ astronautId, status }: { astronautId: string; status: AsyncState<DayResult> }) {
  const { member } = useRegistry();
  const astronaut = member(astronautId);

  return (
    <div className="earth enter">
      <div className="checkin__head">
        <span className="identity__meta">
          {astronaut?.callsign ?? astronautId} · {astronautId}
        </span>
        <h1 className="identity__name">Earth comms</h1>
        <p className="checkin__lead">
          You decide what leaves the spacecraft. Your score and level always travel; private details stay onboard.
        </p>
      </div>
      {status.error ? (
        <LoadError error={status.error} retry={status.reload} what="assessment" />
      ) : !status.data || !astronaut ? (
        <Loading what="mission status" />
      ) : (
        <EarthComms key={astronautId} astronautId={astronautId} result={status.data} initialShared={astronaut.share_with_earth ?? []} />
      )}
    </div>
  );
}

function EarthComms({
  astronautId,
  result,
  initialShared,
}: {
  astronautId: string;
  result: DayResult;
  initialShared: readonly string[];
}) {
  const [shared, setShared] = useState<string[]>([...initialShared]);
  const [consentError, setConsentError] = useState<unknown>(null);
  const [savingConsent, setSavingConsent] = useState(false);

  // Report period: the last week of data, ending at the latest assessment.
  const end = result.as_of;
  const start = new Date(new Date(end).getTime() - REPORT_DAYS * 86_400_000).toISOString();

  const preview = useAsync((signal) => api.earthPacket(astronautId, start, end, signal), [astronautId, start, end, shared.join(",")]);
  const health = useAsync((signal) => api.health(signal), []);
  const outbox = useAsync((signal) => api.outbox(astronautId, signal), [astronautId], { pollMs: OUTBOX_POLL_MS });

  const setConsent = async (next: string[]) => {
    const previous = shared;
    setShared(next); // optimistic
    setSavingConsent(true);
    setConsentError(null);
    try {
      const saved = await api.consent(astronautId, next);
      setShared([...(saved.share_with_earth ?? next)]);
    } catch (err) {
      setShared(previous);
      setConsentError(err);
    } finally {
      setSavingConsent(false);
    }
  };

  return (
    <div className="earth__layout">
      <div className="earth__main">
        <ConsentPanel shared={shared} saving={savingConsent} error={consentError} onChange={setConsent} />
        {preview.error ? (
          <LoadError error={preview.error} retry={preview.reload} what="report preview" />
        ) : !preview.data ? (
          <Loading what="report preview" />
        ) : (
          <ReportPreview packet={preview.data} result={result} start={start} end={end} />
        )}
      </div>
      <SendPanel
        astronautId={astronautId}
        result={result}
        start={start}
        end={end}
        defaultDelay={health.data?.comms.one_way_delay_minutes}
        outbox={outbox}
      />
    </div>
  );
}

/* ---- consent --------------------------------------------------------------------------- */

function ConsentPanel({
  shared,
  saving,
  error,
  onChange,
}: {
  shared: string[];
  saving: boolean;
  error: unknown;
  onChange: (next: string[]) => void;
}) {
  const { registry } = useRegistry();
  const defaults = [...registry.default_shared_categories].sort();
  const isDefault = [...shared].sort().join() === defaults.join();

  return (
    <Frame as="fieldset" className="checkin__group consent" aria-describedby="consent-help">
      <legend className="section-label">Sharing with Earth</legend>
      <p id="consent-help" className="consent__help">
        Turn a category on to send its readings to the flight surgeon. Changes apply to reports sent from now on.
      </p>
      <ul className="consent__list">
        {registry.categories.map((category) => {
          const on = shared.includes(category);
          const signals = registry.signals.filter((s) => s.category === category);
          return (
            <li key={category} className="consent__row">
              <label className="switch">
                <input
                  type="checkbox"
                  role="switch"
                  checked={on}
                  disabled={saving}
                  onChange={() => onChange(on ? shared.filter((c) => c !== category) : [...shared, category])}
                />
                <span className="switch__track" aria-hidden="true" />
                <span className="consent__text">
                  <span className="consent__name">{categoryName(category)}</span>
                  <span className="consent__signals">
                    {signals.map((s) => s.label).join(", ")}
                  </span>
                </span>
              </label>
              <span className={`consent__state${on ? " consent__state--on" : ""}`}>{on ? "Shared" : "Onboard only"}</span>
            </li>
          );
        })}
      </ul>
      <div className="consent__foot">
        <span className="secondary" aria-live="polite">
          {saving ? "Saving…" : isDefault ? "Using the mission default." : "Custom sharing."}
        </span>
        {!isDefault && (
          <button type="button" className="btn btn-ghost" disabled={saving} onClick={() => onChange(defaults)}>
            Reset to mission default
          </button>
        )}
      </div>
      {error !== null && (
        <p className="checkin__error" role="alert">
          Couldn't save your choice: {errorMessages(error).join(" ")}
        </p>
      )}
    </Frame>
  );
}

/* ---- what Earth would receive ------------------------------------------------------------- */

function ReportPreview({ packet, result, start, end }: { packet: EarthPacket; result: DayResult; start: string; end: string }) {
  const { registry, member } = useRegistry();
  const missionStart = member(result.astronaut_id)?.mission_start;
  const latest = [...(packet.assessments ?? [])].sort((a, b) => a.assessed_at.localeCompare(b.assessed_at)).at(-1);
  const sent = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const o of packet.observations ?? []) {
      const cat = registry.signals.find((s) => s.signal === o.signal)?.category ?? "other";
      counts[cat] = (counts[cat] ?? 0) + 1;
    }
    return counts;
  }, [packet.observations, registry.signals]);
  const withheld = packet.withheld ?? {};
  const day = (iso: string) => (missionStart ? missionDay(iso, missionStart) : "—");
  const level = latest?.level ?? "green";

  return (
    <section className="preview" aria-labelledby="preview-heading">
      <div className="section-head">
        <h2 id="preview-heading" className="section-label">
          What Earth would receive
        </h2>
        <span className="secondary data">
          Day {day(start)}–{day(end)}
        </span>
      </div>

      {latest && (
        <Frame className="preview__status">
          <div className="preview__level">
            <LevelIcon level={level} size={28} />
            <div>
              <span className="kicker">Always sent</span>
              <p className="preview__word" style={{ color: levelInk(level) }}>
                {levelCopy(level).word} · {formatNumber(latest.score, 0)}
                <span className="secondary"> / 100</span>
              </p>
            </div>
          </div>
          <ol className="preview__reasons">
            {(latest.contributors ?? []).slice(0, 5).map((c, i) => {
              const isPrivate = !c.signal && !c.event_id;
              return (
                <li key={`${c.label}-${i}`} className={isPrivate ? "preview__private" : undefined}>
                  {isPrivate && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <rect x="5" y="11" width="14" height="10" />
                      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
                    </svg>
                  )}
                  <span>{isPrivate ? "Private reason (hidden by your consent)" : c.label}</span>
                  <span className="secondary data">{formatNumber(c.points, 1)} pts</span>
                </li>
              );
            })}
          </ol>
        </Frame>
      )}

      <table className="table preview__table">
        <caption className="visually-hidden">Readings per category for this report</caption>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Sent</th>
            <th scope="col">Kept onboard</th>
          </tr>
        </thead>
        <tbody>
          {registry.categories.map((cat) => (
            <tr key={cat}>
              <th scope="row">{categoryName(cat)}</th>
              <td>{sent[cat] ?? 0}</td>
              <td className={withheld[cat] ? "preview__kept" : "secondary"}>{withheld[cat] ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/* ---- send + outbox ---------------------------------------------------------------------- */

function SendPanel({
  astronautId,
  result,
  start,
  end,
  defaultDelay,
  outbox,
}: {
  astronautId: string;
  result: DayResult;
  start: string;
  end: string;
  defaultDelay: number | undefined;
  outbox: AsyncState<OutboxItem[]>;
}) {
  const { registry } = useRegistry();
  const [link, setLink] = useState<"mars" | "moon">("mars");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const level = result.assessment?.level ?? "green";
  const recommended = levelRank(level, registry.alert_level_order) >= levelRank("orange", registry.alert_level_order);
  const delay = link === "moon" ? MOON_MINUTES : defaultDelay;

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      await api.sendPacket(astronautId, start, end, link === "moon" ? MOON_MINUTES : undefined);
      outbox.reload();
    } catch (err) {
      setError(err);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="earth__side">
      <Frame as="section" className="review send" aria-labelledby="send-heading">
        <span id="send-heading" className="kicker">
          Send to Earth
        </span>
        {recommended && (
          <p className="send__advice" style={{ borderColor: levelInk(level) }}>
            <LevelTag level={level} /> Your status is {levelCopy(level).word}. Sending a report to the flight surgeon is recommended.
          </p>
        )}
        <div className="field">
          <span className="field__label" id="link-label">
            Communication link
          </span>
          <div className="scale__options" role="radiogroup" aria-labelledby="link-label">
            {(["moon", "mars"] as const).map((l) => (
              <label key={l} className="scale__option" data-checked={link === l || undefined}>
                <input type="radio" name="link" checked={link === l} onChange={() => setLink(l)} />
                {l === "moon" ? "Moon · 1.3 s" : `Mars · ${defaultDelay !== undefined ? formatDelay(defaultDelay) : "…"}`}
              </label>
            ))}
          </div>
        </div>
        <p className="review__stamp">
          Packages your last {REPORT_DAYS} days ({formatMissionTime(start)} to {formatMissionTime(end)}) after the consent filter.
          One-way delay: <span className="data">{delay !== undefined ? formatDelay(delay) : "…"}</span>.
        </p>
        {error !== null && (
          <p className="checkin__error" role="alert">
            The report wasn't queued: {errorMessages(error).join(" ")}
          </p>
        )}
        <button type="button" className="btn btn-primary blueprint review__save" disabled={sending} onClick={() => void send()}>
          <Corners />
          {sending ? "Queuing report…" : "Send report"}
        </button>
      </Frame>

      <section className="outbox" aria-labelledby="outbox-heading">
        <div className="section-head">
          <h2 id="outbox-heading" className="section-label">
            Outbox
          </h2>
          <span className="secondary">{outbox.data ? `${outbox.data.length} sent` : ""}</span>
        </div>
        {outbox.error ? (
          <LoadError error={outbox.error} retry={outbox.reload} what="outbox" />
        ) : !outbox.data ? (
          <Loading what="outbox" />
        ) : outbox.data.length === 0 ? (
          <p className="secondary">Nothing has been sent yet.</p>
        ) : (
          <ul className="outbox__list">
            {outbox.data.map((item) => (
              <OutboxRow key={item.packet_id} item={item} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function OutboxRow({ item }: { item: OutboxItem }) {
  const deliverAt = new Date(item.deliver_at).getTime();
  const createdAt = new Date(item.created_at).getTime();
  const now = useNow(1000, item.status === "queued");
  const left = Math.max(0, deliverAt - now);
  const delivered = item.status === "delivered" || left === 0;
  const progress = deliverAt > createdAt ? Math.min(1, (now - createdAt) / (deliverAt - createdAt)) : 1;
  const sent = Object.values(item.sent ?? {}).reduce((a, b) => a + b, 0);
  const kept = Object.values(item.withheld ?? {}).reduce((a, b) => a + b, 0);
  const latest = [...(item.packet.assessments ?? [])].sort((a, b) => a.assessed_at.localeCompare(b.assessed_at)).at(-1);

  return (
    <Frame as="li" className="outbox__item">
      <div className="outbox__top">
        <span className={`outbox__status${delivered ? " outbox__status--done" : ""}`}>
          {delivered ? (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                <path d="M20 6 9 17l-5-5" />
              </svg>
              Delivered
            </>
          ) : (
            <>Queued · arrives in {formatCountdown(left)}</>
          )}
        </span>
        <span className="secondary data">Sent {new Date(createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
      </div>
      {!delivered && (
        <div className="outbox__bar" role="progressbar" aria-label="Transmission progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
          <span style={{ width: `${progress * 100}%` }} />
        </div>
      )}
      <p className="outbox__meta">
        {latest && (
          <>
            <LevelTag level={latest.level ?? "green"} label={`${levelCopy(latest.level ?? "green").word} · ${formatNumber(latest.score, 0)}`} />{" "}
          </>
        )}
        <span className="data">
          {sent} readings sent · {kept} kept onboard · {formatDelay(item.delay_minutes)} delay
        </span>
      </p>
    </Frame>
  );
}

function formatDelay(minutes: number): string {
  if (minutes < 1) return `${formatNumber(minutes * 60, 1)} s`;
  return `${formatNumber(minutes, minutes < 10 ? 1 : 0)} min`;
}

function formatCountdown(ms: number): string {
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
