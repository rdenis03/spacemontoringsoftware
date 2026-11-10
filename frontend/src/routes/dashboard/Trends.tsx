import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../../api/client";
import type { Anomaly, Baseline, ContextEvent, DayResult, Observation, SignalSpec } from "../../api/types";
import { LoadError, Loading } from "../../components/StateMessage";
import { dayTickLabel, dayTicks, ms, paddedDomain } from "../../lib/chart";
import { formatMissionTime, formatNumber, formatValue, humanize, missionDay, withUnit } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";
import { useTokens } from "../../lib/useTokens";
import { useRegistry } from "../../state/registry";

interface Props {
  astronautId: string;
  status: DayResult | undefined;
  freshness: string;
}

interface Row {
  t: number;
  value?: number;
  band?: [number, number];
  center?: number;
}

export default function Trends({ astronautId, status, freshness }: Props) {
  const { registry, spec, member } = useRegistry();
  const [params, setParams] = useSearchParams();

  const fallback =
    status?.anomalies?.[0]?.signal ??
    status?.assessment?.contributors?.find((c) => c.signal)?.signal ??
    registry.signals.find((s) => s.category === "vital")?.signal ??
    registry.signals[0]?.signal;
  const signal = spec(params.get("signal")) ? params.get("signal")! : (fallback ?? "");
  const s = spec(signal);

  const setSignal = (next: string) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("signal", next);
        return p;
      },
      { replace: true },
    );

  const data = useAsync(
    async (abort) => {
      const [observations, baselines, events] = await Promise.all([
        api.observations(astronautId, [signal], abort),
        api.baselines(astronautId, signal, abort),
        api.events(astronautId, abort),
      ]);
      return { observations, baselines, events };
    },
    [astronautId, signal, freshness],
    { enabled: Boolean(astronautId && signal) },
  );

  return (
    <div className="trends">
      <div className="trends__controls">
        <label className="field">
          <span className="field__label">Signal</span>
          <select className="select" value={signal} onChange={(e) => setSignal(e.target.value)}>
            {registry.categories.map((category) => (
              <optgroup key={category} label={humanize(category)}>
                {registry.signals
                  .filter((x) => x.category === category)
                  .map((x) => (
                    <option key={x.signal} value={x.signal}>
                      {x.label}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </label>
        {s && <p className="secondary trends__description">{s.description}</p>}
      </div>

      {data.error ? (
        <LoadError error={data.error} retry={data.reload} what="readings" />
      ) : !data.data || !s ? (
        <Loading what="readings" />
      ) : (
        <TrendChart
          spec={s}
          observations={data.data.observations}
          baselines={data.data.baselines}
          events={data.data.events}
          anomalies={(status?.anomalies ?? []).filter((a) => a.signal === signal)}
          missionStart={member(astronautId)?.mission_start}
        />
      )}
    </div>
  );
}

function TrendChart({
  spec,
  observations,
  baselines,
  events,
  anomalies,
  missionStart,
}: {
  spec: SignalSpec;
  observations: Observation[];
  baselines: Baseline[];
  events: ContextEvent[];
  anomalies: Anomaly[];
  missionStart: string | undefined;
}) {
  const tokens = useTokens();
  const ordinal = spec.kind === "ordinal";

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [
      ...observations.map((o) => ({ t: ms(o.timestamp), value: o.value })),
      ...baselines.map((b) => ({
        t: ms(b.as_of),
        band: [b.center - b.spread, b.center + b.spread] as [number, number],
        center: b.center,
      })),
    ];
    return out.sort((a, b) => a.t - b.t);
  }, [observations, baselines]);

  if (observations.length === 0) {
    return <p className="card secondary">No readings for {spec.label.toLowerCase()} yet.</p>;
  }

  const tMin = rows[0].t;
  const tMax = rows[rows.length - 1].t;
  const ticks = dayTicks(tMin, tMax);
  const dayLabel = dayTickLabel(missionStart);
  const yDomain: [number, number] = ordinal
    ? [spec.plausible_min, spec.plausible_max]
    : paddedDomain(rows.flatMap((r) => [r.value ?? NaN, ...(r.band ?? [])]));
  const yTicks = ordinal
    ? Array.from({ length: spec.plausible_max - spec.plausible_min + 1 }, (_, i) => spec.plausible_min + i)
    : undefined;
  const yLabel = (v: number) => (ordinal ? formatValue(v, spec) : formatNumber(v));

  const visibleEvents = events.filter((e) => {
    const start = ms(e.start);
    const end = e.end ? ms(e.end) : start + 3 * 3_600_000;
    return end >= tMin && start <= tMax;
  });

  const summary = summarize(spec, observations, baselines, missionStart);

  return (
    <section className="trend card" aria-labelledby="trend-title">
      <h2 id="trend-title" className="trend__title">
        {summary}
      </h2>
      <p className="secondary">
        {spec.label}
        {ordinal ? "" : `, ${spec.unit_label}`} · {observations.length} readings
      </p>

      <figure className="trend__figure" role="img" aria-label={`Line chart of ${spec.label} over time. ${summary}`}>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={rows} margin={{ top: 24, right: 8, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={tokens.separator} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[tMin, tMax]}
              ticks={ticks}
              tickFormatter={dayLabel}
              stroke={tokens.secondary}
              tick={{ fill: tokens.secondary, fontSize: 13 }}
            />
            <YAxis
              orientation="right"
              domain={yDomain}
              ticks={yTicks}
              tickFormatter={yLabel}
              stroke={tokens.secondary}
              tick={{ fill: tokens.secondary, fontSize: 13 }}
              width={ordinal ? 84 : 56}
              allowDecimals={!ordinal}
            />
            {visibleEvents.map((e) => {
              const start = ms(e.start);
              const end = e.end ? ms(e.end) : start + 3 * 3_600_000;
              return (
                <ReferenceArea
                  key={e.event_id ?? e.start}
                  x1={Math.max(start, tMin)}
                  x2={Math.min(end, tMax)}
                  fill={tokens.secondary}
                  fillOpacity={0.14}
                  stroke={tokens.secondary}
                  strokeOpacity={0.4}
                  label={{ value: humanize(e.event_type), position: "insideTopLeft", fill: tokens.secondary, fontSize: 13 }}
                />
              );
            })}
            <Area
              dataKey="band"
              type="stepAfter"
              connectNulls
              isAnimationActive={false}
              fill={tokens.band}
              fillOpacity={1}
              stroke={tokens.bandEdge}
              strokeWidth={1}
              name="Your normal"
            />
            <Line
              dataKey="center"
              type="stepAfter"
              connectNulls
              isAnimationActive={false}
              dot={false}
              stroke={tokens.bandEdge}
              strokeDasharray="3 3"
              strokeWidth={1}
              name="Normal center"
            />
            <Line
              dataKey="value"
              type={ordinal ? "stepAfter" : "linear"}
              connectNulls
              isAnimationActive={false}
              stroke={tokens.content}
              strokeWidth={2}
              dot={{ r: 3, fill: tokens.content, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              name={spec.label}
            />
            {anomalies.map((a) => (
              <ReferenceDot
                key={a.detected_at}
                x={ms(a.detected_at)}
                y={a.value}
                r={9}
                fill="none"
                stroke={tokens.content}
                strokeWidth={2}
                label={{ value: "Outside your normal", position: "top", fill: tokens.content, fontSize: 13 }}
              />
            ))}
            <Tooltip
              content={<TrendTooltip spec={spec} missionStart={missionStart} />}
              cursor={{ stroke: tokens.secondary, strokeWidth: 1 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </figure>

      <ul className="legend" aria-label="Legend">
        <li>
          <span className="legend__line" /> Your readings
        </li>
        <li>
          <span className="legend__band" /> Your normal (center ± spread)
        </li>
        {visibleEvents.length > 0 && (
          <li>
            <span className="legend__event" /> Event
          </li>
        )}
        {anomalies.length > 0 && (
          <li>
            <span className="legend__ring" /> Outside your normal today
          </li>
        )}
      </ul>

      <details className="data-table">
        <summary>Show readings as a table</summary>
        <ReadingsTable spec={spec} observations={observations} baselines={baselines} missionStart={missionStart} />
      </details>
    </section>
  );
}

/** Latest baseline computed at or before a moment. */
function baselineAt(baselines: Baseline[], t: number): Baseline | undefined {
  let found: Baseline | undefined;
  for (const b of baselines) if (ms(b.as_of) <= t) found = b;
  return found ?? baselines[0];
}

/** Chart headline with actual values, no subjective words (charts.md › Descriptive content). */
function summarize(spec: SignalSpec, observations: Observation[], baselines: Baseline[], missionStart?: string): string {
  const latest = observations[observations.length - 1];
  const when = missionStart ? `day ${missionDay(latest.timestamp, missionStart)}` : formatMissionTime(latest.timestamp);
  const value = formatValue(latest.value, spec);
  const base = baselineAt(baselines, ms(latest.timestamp));
  if (!base) return `Latest: ${value} on ${when}. Not enough history yet for your personal normal.`;
  if (spec.kind === "ordinal") return `Latest: ${value} on ${when}.`;
  const low = base.center - base.spread;
  const high = base.center + base.spread;
  if (latest.value >= low && latest.value <= high) {
    return `Latest: ${value} on ${when}, within your normal range (${formatNumber(low)}–${withUnit(formatNumber(high), spec)}).`;
  }
  const diff = latest.value - base.center;
  const direction = diff > 0 ? "above" : "below";
  return `Latest: ${value} on ${when}, ${withUnit(formatNumber(Math.abs(diff)), spec)} ${direction} your normal of ${formatValue(base.center, spec)}.`;
}

function TrendTooltip({
  active,
  payload,
  label,
  spec,
  missionStart,
}: {
  active?: boolean;
  payload?: readonly { payload?: Row }[];
  label?: number | string;
  spec: SignalSpec;
  missionStart?: string;
}) {
  if (!active || !payload?.length || label === undefined) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const t = Number(label);
  return (
    <div className="chart-tooltip">
      <p className="data">
        {missionStart ? `Day ${missionDay(t, missionStart)} · ` : ""}
        {formatMissionTime(new Date(t).toISOString())}
      </p>
      {row.value !== undefined && <p>{formatValue(row.value, spec)}</p>}
      {row.band && (
        <p className="secondary">
          Normal {formatNumber(row.band[0])}–{withUnit(formatNumber(row.band[1]), spec)}
        </p>
      )}
    </div>
  );
}

function ReadingsTable({
  spec,
  observations,
  baselines,
  missionStart,
}: {
  spec: SignalSpec;
  observations: Observation[];
  baselines: Baseline[];
  missionStart?: string;
}) {
  const recent = observations.slice(-30).reverse();
  return (
    <table className="table">
      <thead>
        <tr>
          <th scope="col">Day</th>
          <th scope="col">Time</th>
          <th scope="col">Reading</th>
          <th scope="col">Your normal</th>
        </tr>
      </thead>
      <tbody>
        {recent.map((o) => {
          const base = baselineAt(baselines, ms(o.timestamp));
          return (
            <tr key={o.observation_id ?? o.timestamp}>
              <td className="data">{missionStart ? missionDay(o.timestamp, missionStart) : "—"}</td>
              <td className="data">{formatMissionTime(o.timestamp)}</td>
              <td>{formatValue(o.value, spec)}</td>
              <td className="secondary">
                {base && spec.kind !== "ordinal"
                  ? `${formatNumber(base.center - base.spread)}–${withUnit(formatNumber(base.center + base.spread), spec)}`
                  : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
