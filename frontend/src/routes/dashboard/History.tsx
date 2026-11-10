import { useMemo, useState } from "react";
import {
  CartesianGrid,
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
import { LevelDot } from "../../components/LevelShape";
import { LevelTag } from "../../components/LevelTag";
import { LoadError, Loading } from "../../components/StateMessage";
import { dayTickLabel, dayTicks, ms } from "../../lib/chart";
import { formatMissionTime, formatNumber, missionDay } from "../../lib/format";
import { levelBands, levelCopy, levelRank } from "../../lib/levels";
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
    return <p className="card secondary">No assessments yet. They appear once the daily pipeline has run.</p>;
  }
  return <HistoryView astronautId={astronautId} assessments={data.data.assessments} symptoms={data.data.symptoms} />;
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
  const { registry, member } = useRegistry();
  const tokens = useTokens();
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
  const yTicks = [...bands.map((b) => b.from), 100];

  const latest = assessments[assessments.length - 1];
  const firstAlert = assessments.find((a) => levelRank(a.level ?? "green", order) > 0);
  const latestLevel = latest.level ?? "green";
  const summary =
    `Latest score ${formatNumber(latest.score, 0)} (${levelCopy(latestLevel).word}) on day ${dayOf(latest.assessed_at) ?? "—"}.` +
    (firstAlert ? ` First above ${levelCopy(order[0]).word} on day ${dayOf(firstAlert.assessed_at) ?? "—"}.` : "");

  return (
    <div className="history">
      <section className="trend card" aria-labelledby="history-title">
        <h2 id="history-title" className="trend__title">
          {summary}
        </h2>
        <p className="secondary">Score 0–100 per daily assessment · {assessments.length} days</p>

        <figure className="trend__figure" role="img" aria-label={`Line chart of the daily score over time. ${summary}`}>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={rows} margin={{ top: 16, right: 8, bottom: 8, left: 8 }}>
              {bands.map((b) => (
                <ReferenceArea
                  key={b.level}
                  y1={b.from}
                  y2={b.to}
                  fill={tokens.level[b.level] ?? tokens.secondary}
                  fillOpacity={0.13}
                  stroke="none"
                  label={{ value: levelCopy(b.level).word, position: "insideLeft", fill: tokens.secondary, fontSize: 13 }}
                />
              ))}
              <CartesianGrid stroke={tokens.separator} strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={[tMin, tMax]}
                ticks={dayTicks(tMin, tMax)}
                tickFormatter={dayLabel}
                stroke={tokens.secondary}
                tick={{ fill: tokens.secondary, fontSize: 13 }}
              />
              <YAxis
                orientation="right"
                domain={[0, 100]}
                ticks={yTicks}
                stroke={tokens.secondary}
                tick={{ fill: tokens.secondary, fontSize: 13 }}
                width={40}
              />
              <ReferenceLine x={ms(current.assessed_at)} stroke={tokens.content} strokeDasharray="4 3" />
              <Line
                dataKey="score"
                type="linear"
                isAnimationActive={false}
                stroke={tokens.content}
                strokeWidth={2}
                dot={(props: { cx?: number; cy?: number; payload?: { level: string; t: number } }) => (
                  <LevelDot key={props.payload?.t} cx={props.cx} cy={props.cy} color={tokens.level[props.payload?.level ?? ""]} level={props.payload?.level} stroke={tokens.raised} />
                )}
                activeDot={false}
              />
              <Tooltip
                cursor={{ stroke: tokens.secondary, strokeWidth: 1 }}
                content={({ active, payload }) => {
                  const row = payload?.[0]?.payload as { t: number; score: number; level: string } | undefined;
                  if (!active || !row) return null;
                  return (
                    <div className="chart-tooltip">
                      <p className="data">
                        {missionStart ? `Day ${missionDay(row.t, missionStart)} · ` : ""}
                        {formatMissionTime(new Date(row.t).toISOString())}
                      </p>
                      <p>
                        <span className="data">{formatNumber(row.score, 0)}</span> <LevelTag level={row.level} />
                      </p>
                    </div>
                  );
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </figure>

        <details className="data-table">
          <summary>Show scores as a table</summary>
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
                  <td className="data">{dayOf(a.assessed_at) ?? "—"}</td>
                  <td className="data">{formatMissionTime(a.assessed_at)}</td>
                  <td className="data">{formatNumber(a.score, 0)}</td>
                  <td>
                    <LevelTag level={a.level ?? "green"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      <EarlyWarning assessments={assessments} symptoms={symptoms} order={order} dayOf={dayOf} />

      <section className="replay card" aria-labelledby="replay-heading">
        <h2 id="replay-heading" className="section-label">
          Mission replay
        </h2>
        <label className="replay__slider">
          <span className="field__label">
            Day <span className="data">{dayOf(current.assessed_at) ?? "—"}</span>
          </span>
          <input
            type="range"
            min={0}
            max={assessments.length - 1}
            step={1}
            value={selected}
            onChange={(e) => setSelected(Number(e.target.value))}
            aria-valuetext={`Day ${dayOf(current.assessed_at) ?? ""}, score ${formatNumber(current.score, 0)}, ${levelCopy(current.level ?? "green").word}`}
          />
        </label>
        <div className="replay__day" aria-live="polite">
          <p>
            <LevelTag level={current.level ?? "green"} /> · score <span className="data">{formatNumber(current.score, 0)}</span> ·{" "}
            <span className="secondary data">{formatMissionTime(current.assessed_at)}</span>
          </p>
          {(current.contributors ?? []).length === 0 ? (
            <p className="secondary">No reasons raised the score on this day.</p>
          ) : (
            <ol className="replay__reasons">
              {(current.contributors ?? []).slice(0, 3).map((c, i) => (
                <li key={`${c.label}-${i}`}>
                  {c.label} <span className="secondary data">· {formatNumber(c.points, 1)} pts</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>
    </div>
  );
}

/**
 * How early ORBIT warned: the first day above the lowest level compared with
 * the first day a symptom was reported. Stated with actual days, whatever the result.
 */
function EarlyWarning({
  assessments,
  symptoms,
  order,
  dayOf,
}: {
  assessments: RiskAssessment[];
  symptoms: Observation[];
  order: string[];
  dayOf: (iso: string) => number | undefined;
}) {
  const firstAlert = assessments.find((a) => levelRank(a.level ?? "green", order) > 0);
  const firstSymptom = [...symptoms].filter((o) => o.value > 0).sort((a, b) => ms(a.timestamp) - ms(b.timestamp))[0];
  if (!firstAlert) return null;

  const alertDay = dayOf(firstAlert.assessed_at);
  const alertWord = levelCopy(firstAlert.level ?? "green").word;
  let text: string;
  if (!firstSymptom) {
    text = `ORBIT moved to ${alertWord} on day ${alertDay}. No symptoms have been reported so far.`;
  } else {
    const symptomDay = dayOf(firstSymptom.timestamp);
    const lead = alertDay !== undefined && symptomDay !== undefined ? symptomDay - alertDay : undefined;
    if (lead === undefined) text = `ORBIT moved to ${alertWord} on ${formatMissionTime(firstAlert.assessed_at)}.`;
    else if (lead > 0)
      text = `ORBIT moved to ${alertWord} on day ${alertDay}, ${lead} day${lead === 1 ? "" : "s"} before the first symptom was reported (day ${symptomDay}).`;
    else if (lead === 0) text = `ORBIT moved to ${alertWord} on day ${alertDay}, the same day the first symptom was reported.`;
    else text = `ORBIT moved to ${alertWord} on day ${alertDay}, ${-lead} day${lead === -1 ? "" : "s"} after the first symptom was reported (day ${symptomDay}).`;
  }
  return (
    <p className="early-warning card" role="note">
      {text}
    </p>
  );
}
