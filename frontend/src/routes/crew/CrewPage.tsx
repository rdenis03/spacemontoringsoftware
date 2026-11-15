/**
 * M14 crew and medical officer view: every astronaut's latest level and
 * score, worst first, with a 14-day score line, the top reason, the last
 * check-in and who the action cards escalate to; "View shared status"
 * opens the detail.
 *
 * Privacy: everything here comes from the shared view
 * (GET /status?view=shared), so reasons from categories an astronaut keeps
 * private arrive as a neutral label. Score and level are always visible.
 *
 * Data: GET /api/overview, then per astronaut /assessments, /status?view=shared
 * and the symptom readings (only their time, for "last check-in").
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { DayResult, RiskAssessment } from "../../api/types";
import { Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { LevelTag } from "../../components/LevelTag";
import { LoadError, Loading } from "../../components/StateMessage";
import { formatNumber, humanize, missionDay } from "../../lib/format";
import { levelBands, levelColor, levelCopy, levelInk, levelRank, levelTint } from "../../lib/levels";
import { useAsync } from "../../lib/useAsync";
import { useRegistry } from "../../state/registry-context";
import "../dashboard/Dashboard.css";
import "./Crew.css";

interface CrewEntry {
  id: string;
  callsign: string;
  role: string;
  missionStart: string;
  level: string | null;
  score: number | null;
  history: RiskAssessment[];
  status: DayResult | null;
  lastCheckin: string | null;
}

export default function CrewPage({ freshness }: { freshness: string }) {
  const { crew, registry } = useRegistry();
  const symptomSignals = registry.signals.filter((s) => s.category === "symptom").map((s) => s.signal);
  const [selected, setSelected] = useState<string | null>(null);

  const data = useAsync(
    async (abort) => {
      const overview = await api.overview(abort);
      return Promise.all(
        crew.map(async (m): Promise<CrewEntry> => {
          const row = overview.find((r) => r.astronaut_id === m.astronaut_id);
          const [history, status, checkins] = await Promise.all([
            api.assessments(m.astronaut_id, abort),
            api.status(m.astronaut_id, abort, "shared").catch(() => null),
            api.observations(m.astronaut_id, symptomSignals, abort),
          ]);
          const last = checkins.reduce<string | null>((acc, o) => (!acc || o.timestamp > acc ? o.timestamp : acc), null);
          return {
            id: m.astronaut_id,
            callsign: m.callsign,
            role: m.role ?? "",
            missionStart: m.mission_start,
            level: row?.level ?? null,
            score: row?.score ?? null,
            history: [...history].sort((a, b) => a.assessed_at.localeCompare(b.assessed_at)),
            status,
            lastCheckin: last,
          };
        }),
      );
    },
    [freshness, crew.length],
  );

  if (data.error) return <LoadError error={data.error} retry={data.reload} what="crew overview" />;
  if (!data.data) return <Loading what="crew overview" />;

  const order = registry.alert_level_order;
  const entries = [...data.data].sort(
    (a, b) => levelRank(b.level ?? "green", order) - levelRank(a.level ?? "green", order) || (b.score ?? 0) - (a.score ?? 0),
  );
  const day = entries[0]?.status?.mission_day;
  const open = entries.find((e) => e.id === selected);

  return (
    <div className="crew enter">
      <div className="crew__head">
        <header className="screen-head">
          <h1 className="large-title">Crew</h1>
          <p className="screen-head__lead">
            {entries.length} astronauts{day ? ` · mission day ${day}` : ""}. Worst first; private reasons stay private.
          </p>
        </header>
        <dl className="tally card">
          {order.map((level) => (
            <div key={level}>
              <dt className="visually-hidden">{levelCopy(level).word}</dt>
              <dd className="figure tally__n">{entries.filter((e) => e.level === level).length}</dd>
              <LevelTag level={level} />
            </div>
          ))}
        </dl>
      </div>

      <ul className="crew__grid">
        {entries.map((e) => (
          <CrewCard
            key={e.id}
            entry={e}
            open={e.id === selected}
            onToggle={() => setSelected((cur) => (cur === e.id ? null : e.id))}
          />
        ))}
      </ul>

      {open && <SharedDetail entry={open} onClose={() => setSelected(null)} />}
    </div>
  );
}

/** A reason without a signal or an event was redacted by the consent gate. */
const isPrivate = (c: { signal?: string | null; event_id?: string | null }) => !c.signal && !c.event_id;
const PRIVATE_TEXT = "Private reason";

function CrewCard({ entry, open, onToggle }: { entry: CrewEntry; open: boolean; onToggle: () => void }) {
  const { registry } = useRegistry();
  const level = entry.level ?? "none";
  const recent = entry.history.slice(-14);
  const first = entry.status?.assessment?.contributors?.[0];
  const top = first ? (isPrivate(first) ? PRIVATE_TEXT : first.label) : "Nothing raised the score";
  const escalations = [
    ...new Set((entry.status?.actions ?? []).map((c) => c.escalate_to ?? "self").filter((t) => t !== "self")),
  ].map((t) => humanize(t));
  const dayOf = (iso: string) => missionDay(iso, entry.missionStart);

  return (
    <Frame as="li" className="crew-card" aria-label={`${entry.callsign}, ${levelCopy(level).word}, score ${entry.score ?? "unknown"}`}>
      <header className="crew-card__head">
        <span className="avatar crew-card__initial" aria-hidden="true">
          {entry.callsign.charAt(0)}
        </span>
        <div className="crew-card__who">
          <span className="crew-card__name">{entry.callsign}</span>
          <span className="caption">
            {entry.role} · {entry.id}
          </span>
        </div>
      </header>

      <div className="crew-card__status">
        <div className="crew-card__level">
          <LevelIcon level={level} size={26} />
          <span className="crew-card__word" style={{ color: levelInk(level) }}>
            {entry.level ? levelCopy(level).word : "No result"}
          </span>
        </div>
        <span className="figure crew-card__score">
          {entry.score !== null ? formatNumber(entry.score, 0) : "—"}
          <span className="secondary"> / 100</span>
        </span>
      </div>

      <ScoreLine points={recent} thresholds={registry.alert_levels} />
      {recent.length > 0 && (
        <span className="caption crew-card__axis">
          {recent.length}-day score · day {dayOf(recent[0].assessed_at)} to {dayOf(recent[recent.length - 1].assessed_at)}
        </span>
      )}

      <p className="crew-card__top">
        <span className="caption">Top reason</span>
        <span>{top}</span>
      </p>

      <details className="disclosure disclosure--quiet">
        <summary>Show details</summary>
        <dl className="crew-card__facts">
          <div>
            <dt>Last check-in</dt>
            <dd className="data">
              {entry.lastCheckin ? `Day ${dayOf(entry.lastCheckin)} · ${new Date(entry.lastCheckin).toISOString().slice(11, 16)} UTC` : "—"}
            </dd>
          </div>
          <div>
            <dt>Escalation</dt>
            <dd>{escalations.length ? escalations.join(", ") : "None"}</dd>
          </div>
        </dl>
      </details>

      <div className="crew-card__actions">
        <button
          type="button"
          className="btn btn-secondary crew-card__open"
          aria-expanded={open}
          aria-controls="crew-detail"
          onClick={onToggle}
        >
          {open ? "Hide shared status" : "View shared status"}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d={open ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"} />
          </svg>
        </button>
        <Link className="btn btn-ghost" to={{ pathname: "/today", search: `?astronaut=${encodeURIComponent(entry.id)}` }}>
          Dashboard
        </Link>
      </div>
    </Frame>
  );
}

/** 14-day score on the level bands; the last point a circle in its level's colour. Decorative. */
function ScoreLine({ points, thresholds }: { points: RiskAssessment[]; thresholds: { level: string; min_score: number }[] }) {
  const W = 240;
  const H = 60;
  if (points.length === 0) return <svg viewBox={`0 0 ${W} ${H}`} className="crew-card__chart" aria-hidden="true" />;
  const X = (i: number) => 4 + (points.length === 1 ? 0.5 : i / (points.length - 1)) * (W - 12);
  const Y = (v: number) => 4 + ((100 - Math.min(100, v)) / 100) * (H - 8);
  const last = points[points.length - 1];
  const lastLevel = last.level ?? "green";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="crew-card__chart" aria-hidden="true">
      {levelBands(thresholds).map((b) => (
        <rect key={b.level} x="0" width={W} y={Y(b.to)} height={Y(b.from) - Y(b.to)} style={{ fill: levelTint(b.level, 10) }} />
      ))}
      <path
        d={points.map((a, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(a.score).toFixed(1)}`).join("")}
        fill="none"
        style={{ stroke: "var(--accent)" }}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      <circle
        cx={X(points.length - 1)}
        cy={Y(last.score)}
        r={4}
        style={{ fill: levelColor(lastLevel), stroke: "var(--card)" }}
        strokeWidth={1}
      />
    </svg>
  );
}

/** What crewmates and the medical officer see: private reasons stay hidden. */
function SharedDetail({ entry, onClose }: { entry: CrewEntry; onClose: () => void }) {
  const status = entry.status;
  const assessment = status?.assessment;
  const level = assessment?.level ?? "green";
  const reasons = assessment?.contributors ?? [];
  const hidden = reasons.filter(isPrivate).length;

  return (
    <Frame as="section" id="crew-detail" className="crew-detail" aria-labelledby="crew-detail-title">
      <div className="section-head">
        <div>
          <span className="caption">Shared status · {entry.id}</span>
          <h2 id="crew-detail-title" className="title">
            {entry.callsign}
          </h2>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Close
        </button>
      </div>
      {!assessment ? (
        <p className="secondary">No assessment yet.</p>
      ) : (
        <div className="crew-detail__body">
          <div className="crew-detail__status">
            <LevelIcon level={level} size={30} />
            <div>
              <p className="crew-detail__word" style={{ color: levelInk(level) }}>
                {levelCopy(level).word}
              </p>
              <p className="secondary">
                Score {formatNumber(assessment.score, 0)} / 100 · mission day {status?.mission_day}
              </p>
            </div>
          </div>
          <section aria-labelledby="crew-detail-reasons">
            <h3 id="crew-detail-reasons" className="headline">
              Reasons
            </h3>
            {reasons.length === 0 ? (
              <p className="secondary">Nothing raised the score.</p>
            ) : (
              <ol className="group crew-detail__reasons">
                {reasons.map((c, i) => (
                  <li key={`${c.label}-${i}`} className={isPrivate(c) ? "crew-detail__private" : undefined}>
                    <span className="numbered__n data">{i + 1}</span>
                    <span>{isPrivate(c) ? `${PRIVATE_TEXT} (not shared by ${entry.callsign})` : c.label}</span>
                    <span className="secondary data">{formatNumber(c.points, 1)} pts</span>
                  </li>
                ))}
              </ol>
            )}
            {hidden > 0 && (
              <p className="crew-detail__note">
                {hidden} reason{hidden === 1 ? " is" : "s are"} private. Their points still count in the score.
              </p>
            )}
          </section>
          <section aria-labelledby="crew-detail-cards">
            <h3 id="crew-detail-cards" className="headline">
              Action cards
            </h3>
            {(status?.actions ?? []).length === 0 ? (
              <p className="secondary">No action cards.</p>
            ) : (
              <ul className="group crew-detail__cards">
                {(status?.actions ?? []).map((card) => (
                  <li key={card.card_id}>
                    <span className="crew-detail__card-title">{card.title}</span>
                    <LevelTag level={card.level} />
                    <span className="crew-detail__esc">
                      {(card.escalate_to ?? "self") === "self" ? "Handled by the astronaut" : `Escalates to ${humanize(card.escalate_to!).toLowerCase()}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </Frame>
  );
}
