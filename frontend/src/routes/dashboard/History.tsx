/**
 * History: the daily score on the level bands, how early ORBIT warned
 * compared with the first reported symptom, and a mission replay slider.
 */
import { useMemo, useState } from "react";
import {
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../../api/client";
import type { Observation, RiskAssessment } from "../../api/types";
import { Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { LevelDot } from "../../components/LevelShape";
import { LevelTag } from "../../components/LevelTag";
import { LoadError, Loading } from "../../components/StateMessage";
import { dayTickLabel, dayTicks, ms } from "../../lib/chart";
import { formatMissionTime, formatNumber, missionDay } from "../../lib/format";
import { levelBands, levelCopy, levelInk, levelRank } from "../../lib/levels";
import { useAsync } from "../../lib/useAsync";
import { useTokens } from "../../lib/useTokens";
import { useRegistry } from "../../state/registry-context";

interface Props {
  astronautId: string;
  freshness: string;
}

export default function History({ astronautId, freshness }: Props) {
  const { registry } = useRegistry();
  const symptomSignals = registry.signals.filter((s) => s.category === "symptom").map((s) => s.signal);

  const data = useAsync(
    async (abort) => {
      const [assessments, symptoms] = await Promise.all([
        api.assessments(astronautId, abort),
        api.observations(astronautId, symptomSignals, abort),
      ]);
      return { assessments: [...assessments].sort((a, b) => ms(a.assessed_at) - ms(b.assessed_at)), symptoms };
    },
    [astronautId, freshness],
    { enabled: Boolean(astronautId) },
  );

  if (data.error) return <LoadError error={data.error} retry={data.reload} what="assessment history" />;
  if (!data.data) return <Loading what="assessment history" />;
  if (data.data.assessments.length === 0) {
    return <p className="secondary">No assessments yet. They appear once the daily pipeline has run.</p>;
  }
  return <HistoryView key={astronautId} astronautId={astronautId} assessments={data.data.assessments} symptoms={data.data.symptoms} />;
}

function HistoryView({
  astronautId,
  assessments,
  symptoms,
}: {
  astronautId: string;
  assessments: RiskAssessment[];
  symptoms: Observation[];
}) {
  const { registry, member, spec } = useRegistry();
  const tokens = useTokens();
  const [showTable, setShowTable] = useState(false);
  const missionStart = member(astronautId)?.mission_start;
  const order = registry.alert_level_order;
  const bands = levelBands(registry.alert_levels);
  const [selected, setSelected] = useState(assessments.length - 1);
  const current = assessments[Math.min(selected, assessments.length - 1)];

  const rows = useMemo(
    () => assessments.map((a) => ({ t: ms(a.assessed_at), score: a.score, level: a.level ?? "green" })),
    [assessments],
  );
  const tMin = rows[0].t;
  const tMax = rows[rows.length - 1].t;
  const dayOf = (iso: string | number) => (missionStart ? missionDay(iso, missionStart) : undefined);
  const dayLabel = dayTickLabel(missionStart);

  const latest = assessments[assessments.length - 1];
  const firstAlert = assessments.find((a) => levelRank(a.level ?? "green", order) > 0);
  const latestLevel = latest.level ?? "green";
  const summary =
    `Latest score ${formatNumber(latest.score, 0)} (${levelCopy(latestLevel).word}) on day ${dayOf(latest.assessed_at) ?? "—"}.` +
    (firstAlert ? ` First above ${levelCopy(order[0]).word} on day ${dayOf(firstAlert.assessed_at) ?? "—"}.` : "");

  const firstSymptom = [...symptoms].filter((o) => o.value > 0).sort((a, b) => ms(a.timestamp) - ms(b.timestamp))[0];
  const currentLevel = current.level ?? "green";

  return (
    <div className="history">
      <Frame className="trend" aria-labelledby="history-title">
        <span className="kicker">Score 0–100 per daily assessment · {assessments.length} days</span>
        <h2 id="history-title" className="trend__summary trend__summary--wide">
          {summary}
        </h2>

        <figure className="trend__figure" role="img" aria-label={`Line chart of the daily score over time. ${summary}`}>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={rows} margin={{ top: 12, right: 4, bottom: 4, left: 4 }}>
              {bands.map((b) => (
                <ReferenceArea
                  key={b.level}
                  y1={b.from}
                  y2={b.to}
                  fill={tokens.level[b.level] ?? tokens.text3}
                  fillOpacity={0.09}
                  stroke="none"
                  label={{ value: levelCopy(b.level).word, position: "insideTopLeft", fill: tokens.ink[b.level] ?? tokens.text2, fontSize: 12 }}
                />
              ))}
              {bands.map((b) => (
                <ReferenceLine key={`l-${b.level}`} y={b.from} stroke={tokens.separator} strokeOpacity={0.6} />
              ))}
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={[tMin, tMax]}
                ticks={dayTicks(tMin, tMax, 7)}
                tickFormatter={dayLabel}
                stroke={tokens.separator}
                tickLine={false}
                tick={{ fill: tokens.text2, fontSize: 12 }}
              />
              <YAxis
                orientation="right"
                domain={[0, 100]}
                ticks={bands.map((b) => b.from)}
                axisLine={false}
                tickLine={false}
                tick={{ fill: tokens.text2, fontSize: 12 }}
                width={36}
              />
              <ReferenceLine x={ms(current.assessed_at)} stroke={tokens.accent} strokeDasharray="4 4" strokeWidth={1} />
              <Line
                dataKey="score"
                type="linear"
                isAnimationActive={false}
                stroke={tokens.accent}
                strokeWidth={1.75}
                dot={(props: { cx?: number; cy?: number; payload?: { level: string; t: number; score: number } }) => (
                  <LevelDot
                    key={props.payload?.t}
                    cx={props.cx}
                    cy={props.cy}
                    color={tokens.level[props.payload?.level ?? ""]}
                    level={props.payload?.level}
                    label={props.payload ? `${levelCopy(props.payload.level).word}, score ${formatNumber(props.payload.score, 0)}` : undefined}
                    stroke={tokens.card}
                    r={props.payload?.t === ms(current.assessed_at) ? 6 : 3.5}
                  />
                )}
                activeDot={false}
              />
              <Tooltip
                cursor={{ stroke: tokens.separator, strokeWidth: 1 }}
                content={({ active, payload }) => {
                  const row = payload?.[0]?.payload as { t: number; score: number; level: string } | undefined;
                  if (!active || !row) return null;
                  return (
                    <div className="chart-tooltip">
                      <p className="kicker">
                        {missionStart ? `Day ${missionDay(row.t, missionStart)} · ` : ""}
                        {formatMissionTime(new Date(row.t).toISOString())}
                      </p>
                      <p className="chart-tooltip__value">
                        {formatNumber(row.score, 0)} <LevelTag level={row.level} />
                      </p>
                    </div>
                  );
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </figure>

        <ul className="legend" aria-label="Legend">
          <li>
            <span className="legend__line" /> Daily score
          </li>
          {bands.map((b) => (
            <li key={b.level}>
              <LevelIcon level={b.level} size={11} /> {levelCopy(b.level).word} ({b.from}–{b.to})
            </li>
          ))}
          <li className="legend__note">A point's colour is that day's alert level.</li>
        </ul>

        <div className="trend__table">
          <button type="button" className="btn btn-ghost" aria-expanded={showTable} onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Hide scores table" : "Show scores as a table"}
          </button>
          {showTable && (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Day</th>
                    <th scope="col">Assessed</th>
                    <th scope="col">Score</th>
                    <th scope="col">Level</th>
                  </tr>
                </thead>
                <tbody>
                  {[...assessments].reverse().map((a) => (
                    <tr key={a.assessment_id ?? a.assessed_at}>
                      <td>{dayOf(a.assessed_at) ?? "—"}</td>
                      <td>{formatMissionTime(a.assessed_at)}</td>
                      <td>{formatNumber(a.score, 0)}</td>
                      <td>
                        <LevelTag level={a.level ?? "green"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Frame>

      <div className="history__pair">
        <Frame className="panel" aria-labelledby="ew-heading">
          <h2 id="ew-heading" className="headline">
            Early warning
          </h2>
          {firstAlert && (
            <div className="ew">
              <div className="ew__side">
                <span className="kicker">ORBIT alert</span>
                <span className="figure ew__day">Day {dayOf(firstAlert.assessed_at) ?? "—"}</span>
                <LevelTag level={firstAlert.level ?? "yellow"} label={`Moved to ${levelCopy(firstAlert.level ?? "yellow").word}`} />
              </div>
              <svg className="ew__arrow" width="40" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M5 12h14" />
                <path d="m12 5 7 7-7 7" />
              </svg>
              <div className="ew__side">
                <span className="kicker">First symptom</span>
                <span className="figure ew__day">{firstSymptom ? `Day ${dayOf(firstSymptom.timestamp) ?? "—"}` : "—"}</span>
                <span className="secondary">{firstSymptom ? (spec(firstSymptom.signal)?.label ?? firstSymptom.signal) : "None reported"}</span>
              </div>
            </div>
          )}
          <p className="ew__text">{earlyWarningText(firstAlert, firstSymptom, dayOf)}</p>
        </Frame>

        <Frame className="panel" aria-labelledby="replay-heading">
          <div className="section-head">
            <h2 id="replay-heading" className="headline">
              Mission replay
            </h2>
            <span className="secondary data">{formatMissionTime(current.assessed_at)}</span>
          </div>
          <input
            className="replay__range"
            type="range"
            min={0}
            max={assessments.length - 1}
            step={1}
            value={selected}
            onChange={(e) => setSelected(Number(e.target.value))}
            aria-label="Mission day"
            aria-valuetext={`Day ${dayOf(current.assessed_at) ?? ""}, score ${formatNumber(current.score, 0)}, ${levelCopy(currentLevel).word}`}
          />
          <div className="replay__ends data">
            <span>Day {dayOf(assessments[0].assessed_at) ?? "—"}</span>
            <span>Day {dayOf(latest.assessed_at) ?? "—"}</span>
          </div>
          <div className="replay__day" aria-live="polite">
            <span className="figure replay__dayno">Day {dayOf(current.assessed_at) ?? "—"}</span>
            <span className="replay__level" style={{ color: levelInk(currentLevel) }}>
              <LevelIcon level={currentLevel} size={14} />
              {levelCopy(currentLevel).word}
            </span>
            <span className="figure replay__score">
              {formatNumber(current.score, 0)}
              <span className="secondary"> / 100</span>
            </span>
          </div>
          {(current.contributors ?? []).length === 0 ? (
            <p className="secondary">No reasons raised the score on this day.</p>
          ) : (
            <ol className="numbered">
              {(current.contributors ?? []).slice(0, 3).map((c, i) => (
                <li key={`${c.label}-${i}`}>
                  <span className="numbered__n data">{String(i + 1).padStart(2, "0")}</span>
                  <span>{c.label}</span>
                  <span className="secondary data">{formatNumber(c.points, 1)} pts</span>
                </li>
              ))}
            </ol>
          )}
          <ReplayCards astronautId={astronautId} asOf={current.assessed_at} />
        </Frame>
      </div>
    </div>
  );
}

/** The action cards ORBIT gave on the replayed day (GET /day, B13). */
function ReplayCards({ astronautId, asOf }: { astronautId: string; asOf: string }) {
  const day = useAsync((signal) => api.day(astronautId, asOf, signal), [astronautId, asOf]);
  const cards = day.data?.actions ?? [];
  if (day.error || (day.data && cards.length === 0)) return null;
  return (
    <div className="replay__cards">
      <span className="kicker">Action cards that day</span>
      {!day.data ? (
        <p className="secondary">Loading…</p>
      ) : (
        <ul>
          {cards.map((card) => (
            <li key={card.card_id}>
              <span>{card.title}</span>
              <LevelTag level={card.level} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Stated with actual days, whatever the result. */
function earlyWarningText(
  firstAlert: RiskAssessment | undefined,
  firstSymptom: Observation | undefined,
  dayOf: (iso: string) => number | undefined,
): string {
  if (!firstAlert) return "ORBIT has stayed Green for the whole mission so far.";
  const alertDay = dayOf(firstAlert.assessed_at);
  const word = levelCopy(firstAlert.level ?? "yellow").word;
  if (!firstSymptom) return `ORBIT moved to ${word} on day ${alertDay}. No symptoms have been reported so far.`;
  const symptomDay = dayOf(firstSymptom.timestamp);
  if (alertDay === undefined || symptomDay === undefined) return `ORBIT moved to ${word} on ${formatMissionTime(firstAlert.assessed_at)}.`;
  const lead = symptomDay - alertDay;
  if (lead > 0) return `ORBIT moved to ${word} on day ${alertDay}, ${lead} day${lead === 1 ? "" : "s"} before the first symptom was reported (day ${symptomDay}).`;
  if (lead === 0) return `ORBIT moved to ${word} on day ${alertDay}, the same day the first symptom was reported.`;
  return `ORBIT moved to ${word} on day ${alertDay}, ${-lead} day${lead === -1 ? "" : "s"} after the first symptom was reported (day ${symptomDay}).`;
}
