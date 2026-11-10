/**
 * M14 crew view (grid): every astronaut's latest level and score, worst
 * first, with a 14-day score line, the top reason, the last check-in and
 * who the action cards escalate to.
 *
 * Data: GET /api/overview, then per astronaut /assessments, /status and the
 * symptom readings (for the last check-in time). The privacy-filtered
 * detail view (`/status?view=shared`) is still to come from the backend;
 * "Open dashboard" opens the full dashboard in this demo.
 */
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { DayResult, RiskAssessment } from "../../api/types";
import { Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { shapePath } from "../../lib/shapes";
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

  const data = useAsync(
    async (abort) => {
      const overview = await api.overview(abort);
      return Promise.all(
        crew.map(async (m): Promise<CrewEntry> => {
          const row = overview.find((r) => r.astronaut_id === m.astronaut_id);
          const [history, status, checkins] = await Promise.all([
            api.assessments(m.astronaut_id, abort),
            api.status(m.astronaut_id, abort).catch(() => null),
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

  return (
    <div className="crew enter">
      <div className="crew__head">
        <div className="crew__title">
          <span className="identity__meta">
            {entries.length} astronauts{day ? ` · mission day ${day}` : ""}
          </span>
          <h1 className="identity__name">Crew</h1>
        </div>
        <dl className="tally">
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
          <CrewCard key={e.id} entry={e} />
        ))}
      </ul>
    </div>
  );
}

function CrewCard({ entry }: { entry: CrewEntry }) {
  const { registry } = useRegistry();
  const level = entry.level ?? "none";
  const recent = entry.history.slice(-14);
  const top = entry.status?.assessment?.contributors?.[0]?.label ?? "Nothing raised the score";
  const escalations = [
    ...new Set((entry.status?.actions ?? []).map((c) => c.escalate_to ?? "self").filter((t) => t !== "self")),
  ].map((t) => humanize(t));
  const dayOf = (iso: string) => missionDay(iso, entry.missionStart);

  return (
    <Frame as="li" className="crew-card" aria-label={`${entry.callsign}, ${levelCopy(level).word}, score ${entry.score ?? "unknown"}`}>
      <header className="crew-card__head">
        <span className="crew-card__initial" aria-hidden="true">
          {entry.callsign.charAt(0)}
        </span>
        <div className="crew-card__who">
          <span className="crew-card__name">{entry.callsign}</span>
          <span className="secondary">
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
          <span className="secondary">/100</span>
        </span>
      </div>

      <ScoreLine points={recent} thresholds={registry.alert_levels} />
      {recent.length > 0 && (
        <div className="crew-card__axis">
          <span>Day {dayOf(recent[0].assessed_at)}</span>
          <span>{recent.length}-day score</span>
          <span>Day {dayOf(recent[recent.length - 1].assessed_at)}</span>
        </div>
      )}

      <dl className="crew-card__facts">
        <div>
          <dt>Top reason</dt>
          <dd>{top}</dd>
        </div>
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

      <Link className="btn btn-secondary crew-card__open" to={{ pathname: "/", search: `?astronaut=${encodeURIComponent(entry.id)}` }}>
        Open dashboard
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <path d="M5 12h14" />
          <path d="m12 5 7 7-7 7" />
        </svg>
      </Link>
    </Frame>
  );
}

/** 14-day score on the level bands; the last point in its level's shape. Decorative. */
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
        <rect key={b.level} x="0" width={W} y={Y(b.to)} height={Y(b.from) - Y(b.to)} style={{ fill: levelTint(b.level, 12) }} />
      ))}
      <path
        d={points.map((a, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(a.score).toFixed(1)}`).join("")}
        fill="none"
        style={{ stroke: "var(--color-text)" }}
        strokeWidth={1.5}
      />
      <path
        d={shapePath(lastLevel, X(points.length - 1), Y(last.score), 4)}
        style={{ fill: levelColor(lastLevel), stroke: "var(--color-bg)" }}
        strokeWidth={1}
      />
    </svg>
  );
}
