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
import { LevelIcon } from "../../components/LevelIcon";
import { LevelDot } from "../../components/LevelShape";
import { LoadError, Loading } from "../../components/StateMessage";
import { dayTickLabel, dayTicks, ms, paddedDomain } from "../../lib/chart";
import { formatMissionTime, formatNumber, formatValue, humanize, missionDay, signedNumber, withUnit } from "../../lib/format";
import { levelColor } from "../../lib/levels";
import { useAsync } from "../../lib/useAsync";
import { useTokens } from "../../lib/useTokens";
import { NO_NORMAL, ZONE_COPY, ZONE_STEPS, ZONES, type Zone, zoneForReading, zoneRanges } from "../../lib/zones";
import { useRegistry } from "../../state/registry-context";

interface Props {
  astronautId: string;
  status: DayResult | undefined;
  freshness: string;
}

/** How far back the sensor overview looks for each signal's latest reading (weekly lab tests included). */
const OVERVIEW_DAYS = 8;

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

  const overviewStart = status ? new Date(ms(status.as_of) - OVERVIEW_DAYS * 86_400_000).toISOString() : undefined;
  const overview = useAsync((abort) => api.observations(astronautId, [], abort, overviewStart), [astronautId, freshness], {
    enabled: Boolean(astronautId),
  });

  const detail = useAsync(
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
      {overview.error ? (
        <LoadError error={overview.error} retry={overview.reload} what="sensor readings" />
      ) : !overview.data ? (
        <Loading what="sensors" />
      ) : (
        <SensorGrid
          readings={overview.data}
          baselines={status?.baselines ?? []}
          selected={signal}
          onSelect={setSignal}
          missionStart={member(astronautId)?.mission_start}
        />
      )}

      {detail.error ? (
        <LoadError error={detail.error} retry={detail.reload} what="readings" />
      ) : !detail.data || !s ? (
        <Loading what="readings" />
      ) : (
        <TrendChart
          spec={s}
          observations={detail.data.observations}
          baselines={detail.data.baselines}
          events={detail.data.events}
          anomalies={(status?.anomalies ?? []).filter((a) => a.signal === signal)}
          missionStart={member(astronautId)?.mission_start}
        />
      )}
    </div>
  );
}

/* ---- every sensor at a glance ------------------------------------------------ */

function SensorGrid({
  readings,
  baselines,
  selected,
  onSelect,
  missionStart,
}: {
  readings: Observation[];
  baselines: readonly Baseline[];
  selected: string;
  onSelect: (signal: string) => void;
  missionStart?: string;
}) {
  const { registry } = useRegistry();

  const latest = useMemo(() => {
    const map = new Map<string, Observation>();
    for (const o of readings) {
      const prev = map.get(o.signal);
      if (!prev || ms(o.timestamp) > ms(prev.timestamp)) map.set(o.signal, o);
    }
    return map;
  }, [readings]);
  const baselineFor = new Map<string, Baseline>(baselines.map((b) => [b.signal, b]));

  return (
    <section className="sensors" aria-labelledby="sensors-heading">
      <div className="sensors__head">
        <h2 id="sensors-heading" className="section-label">
          All sensors
        </h2>
        <ZoneKey />
      </div>
      {registry.categories.map((category) => {
        const signals = registry.signals.filter((x) => x.category === category);
        if (signals.length === 0) return null;
        return (
          <div key={category} className="sensors__group">
            <h3 className="sensors__category">{humanize(category)}</h3>
            <ul className="sensors__grid">
              {signals.map((spec) => {
                const reading = latest.get(spec.signal);
                const baseline = baselineFor.get(spec.signal);
                const zone = reading ? zoneForReading(reading.value, spec, baseline) : null;
                const state = zone ? ZONE_COPY[zone].short : reading ? NO_NORMAL : "No recent reading";
                const delta =
                  reading && baseline && spec.kind !== "ordinal"
                    ? `${withUnit(signedNumber(reading.value - baseline.center), spec)} vs normal`
                    : null;
                const when = reading && missionStart ? `day ${missionDay(reading.timestamp, missionStart)}` : "";
                const isSelected = spec.signal === selected;
                return (
                  <li key={spec.signal}>
                    <button
                      type="button"
                      className="sensor"
                      aria-pressed={isSelected}
                      style={{ ["--sensor-zone" as string]: zone ? levelColor(zone) : "var(--separator)" }}
                      onClick={() => onSelect(spec.signal)}
                      aria-label={`${spec.label}: ${reading ? formatValue(reading.value, spec) : "no recent reading"}, ${state}${when ? `, ${when}` : ""}. Show trend.`}
                    >
                      <span className="sensor__top">
                        <LevelIcon level={zone ?? "none"} size={16} />
                        <span className="sensor__label">{spec.label}</span>
                      </span>
                      <span className="sensor__value data">{reading ? formatValue(reading.value, spec) : "—"}</span>
                      <span className="sensor__state">
                        {state}
                        {delta && <span className="data"> · {delta}</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

/** Legend for the four sensor states, shared by the grid and the chart. */
function ZoneKey() {
  return (
    <ul className="zone-key" aria-label="Sensor states">
      {ZONES.map((zone) => (
        <li key={zone}>
          <LevelIcon level={zone} size={14} />
          {ZONE_COPY[zone].short}
        </li>
      ))}
      <li>
        <LevelIcon level="none" size={14} />
        {NO_NORMAL}
      </li>
    </ul>
  );
}

/* ---- one sensor over time, on coloured zones ---------------------------------- */

interface Row {
  t: number;
  value?: number;
  center?: number;
  [zoneKey: string]: number | [number, number] | undefined;
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
  const ordinal = spec.kind === "ordinal" && Boolean(spec.scale_labels);
  const sortedBaselines = useMemo(() => [...baselines].sort((a, b) => ms(a.as_of) - ms(b.as_of)), [baselines]);
  const latestBaseline = sortedBaselines[sortedBaselines.length - 1];

  // Y range: fixed for ordinal scales; for continuous signals it covers the
  // readings and the zones around the current normal, so every band shows.
  const yDomain: [number, number] = useMemo(() => {
    if (ordinal) return [spec.plausible_min - 0.5, spec.plausible_max + 0.5];
    const values = observations.map((o) => o.value);
    if (latestBaseline) {
      const { center: c, spread: sp } = latestBaseline;
      const upFar = spec.concern === "up" || spec.concern === "both";
      const downFar = spec.concern === "down" || spec.concern === "both";
      values.push(c + sp * (upFar ? ZONE_STEPS[2] + 0.5 : 1.5), c - sp * (downFar ? ZONE_STEPS[2] + 0.5 : 1.5));
    }
    return paddedDomain(values, 0.05);
  }, [ordinal, spec, observations, latestBaseline]);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = observations.map((o) => ({ t: ms(o.timestamp), value: o.value }));
    if (!ordinal) {
      for (const b of sortedBaselines) {
        if (b.spread <= 0) continue;
        const row: Row = { t: ms(b.as_of), center: b.center };
        for (const z of zoneRanges(b.center, b.spread, spec.concern, yDomain)) row[z.key] = z.range;
        out.push(row);
      }
    }
    return out.sort((a, b) => a.t - b.t);
  }, [observations, sortedBaselines, ordinal, spec.concern, yDomain]);

  if (observations.length === 0) {
    return <p className="card secondary">No readings for {spec.label.toLowerCase()} yet.</p>;
  }

  const tMin = rows[0].t;
  const tMax = rows[rows.length - 1].t;
  const ticks = dayTicks(tMin, tMax);
  const dayLabel = dayTickLabel(missionStart);
  const yTicks = ordinal
    ? Array.from({ length: spec.plausible_max - spec.plausible_min + 1 }, (_, i) => spec.plausible_min + i)
    : undefined;
  const yLabel = (v: number) => (ordinal ? formatValue(v, spec) : formatNumber(v));
  const zoneKeys = latestBaseline && !ordinal ? zoneRanges(0, 1, spec.concern, [0, 0]) : [];

  const visibleEvents = events.filter((e) => {
    const start = ms(e.start);
    const end = e.end ? ms(e.end) : start + 3 * 3_600_000;
    return end >= tMin && start <= tMax;
  });

  const summary = summarize(spec, observations, sortedBaselines, missionStart);
  const zoneOf = (t: number, value: number) => zoneForReading(value, spec, baselineAt(sortedBaselines, t));

  return (
    <section className="trend card" aria-labelledby="trend-title">
      <h2 id="trend-title" className="trend__title">
        {summary}
      </h2>
      <p className="secondary">
        {spec.label}
        {ordinal ? "" : `, ${spec.unit_label}`} · {observations.length} readings · {spec.description}
      </p>

      <figure className="trend__figure" role="img" aria-label={`Line chart of ${spec.label} over time on coloured zones. ${summary}`}>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={rows} margin={{ top: 24, right: 8, bottom: 8, left: 8 }}>
            {/* Ordinal scales: one horizontal band per scale value, like History. */}
            {ordinal &&
              yTicks!.map((v) => {
                const zone = zoneForReading(v, spec, undefined) ?? "green";
                return (
                  <ReferenceArea
                    key={v}
                    y1={v - 0.5}
                    y2={v + 0.5}
                    fill={tokens.level[zone]}
                    fillOpacity={0.13}
                    stroke="none"
                    ifOverflow="hidden"
                  />
                );
              })}
            {/* Continuous signals: zones follow the personal normal day by day. */}
            {zoneKeys.map((z) => (
              <Area
                key={z.key}
                dataKey={z.key}
                type="stepAfter"
                connectNulls
                isAnimationActive={false}
                fill={tokens.level[z.zone]}
                fillOpacity={z.zone === "green" ? 0.16 : 0.13}
                stroke="none"
                activeDot={false}
                tooltipType="none"
              />
            ))}
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
              allowDataOverflow
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
                  fillOpacity={0.18}
                  stroke={tokens.secondary}
                  strokeOpacity={0.5}
                  label={{ value: humanize(e.event_type), position: "insideTopLeft", fill: tokens.content, fontSize: 13 }}
                />
              );
            })}
            {!ordinal && (
              <Line
                dataKey="center"
                type="stepAfter"
                connectNulls
                isAnimationActive={false}
                dot={false}
                activeDot={false}
                stroke={tokens.bandEdge}
                strokeDasharray="3 3"
                strokeWidth={1}
                tooltipType="none"
              />
            )}
            <Line
              dataKey="value"
              type={ordinal ? "stepAfter" : "linear"}
              connectNulls
              isAnimationActive={false}
              stroke={tokens.content}
              strokeWidth={2}
              dot={(props: { cx?: number; cy?: number; payload?: Row }) => {
                const row = props.payload;
                const zone = row?.value !== undefined ? zoneOf(row.t, row.value) : null;
                return (
                  <LevelDot
                    key={`${row?.t}`}
                    cx={props.cx}
                    cy={props.cy}
                    level={zone}
                    color={zone ? tokens.level[zone] : undefined}
                    stroke={tokens.raised}
                    neutral={tokens.content}
                    r={5}
                  />
                );
              }}
              activeDot={{ r: 6 }}
              name={spec.label}
            />
            {anomalies.map((a) => (
              <ReferenceDot
                key={a.detected_at}
                x={ms(a.detected_at)}
                y={a.value}
                r={11}
                fill="none"
                stroke={tokens.content}
                strokeWidth={2}
                label={{ value: "Flagged today", position: "top", fill: tokens.content, fontSize: 13 }}
              />
            ))}
            <Tooltip
              content={<TrendTooltip spec={spec} missionStart={missionStart} zoneOf={zoneOf} baselines={sortedBaselines} />}
              cursor={{ stroke: tokens.secondary, strokeWidth: 1 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </figure>

      <ul className="legend" aria-label="Legend">
        <li>
          <span className="legend__line" /> Your readings
        </li>
        {!ordinal && latestBaseline && (
          <li>
            <span className="legend__center" /> Center of your normal
          </li>
        )}
        {ordinal ? (
          (spec.scale_labels ?? []).map((word, i) => {
            const zone = zoneForReading(spec.plausible_min + i, spec, undefined) ?? "green";
            return (
              <li key={word}>
                <LevelIcon level={zone} size={14} /> {word}
              </li>
            );
          })
        ) : latestBaseline ? (
          ZONES.map((zone, i) => (
            <li key={zone}>
              <LevelIcon level={zone} size={14} /> {ZONE_COPY[zone].short}
              <span className="data">
                {i === 0 ? ` (< ${ZONE_STEPS[0]}×)` : i === 3 ? ` (≥ ${ZONE_STEPS[2]}×)` : ` (${ZONE_STEPS[i - 1]}–${ZONE_STEPS[i]}×)`}
              </span>
            </li>
          ))
        ) : (
          <li>
            <LevelIcon level="none" size={14} /> {NO_NORMAL}
          </li>
        )}
        {visibleEvents.length > 0 && (
          <li>
            <span className="legend__event" /> Event
          </li>
        )}
        {anomalies.length > 0 && (
          <li>
            <span className="legend__ring" /> Flagged today
          </li>
        )}
      </ul>
      {!ordinal && latestBaseline && (
        <p className="secondary">
          Zones are measured in your usual day-to-day variation, and only in the direction that matters for this
          signal ({spec.concern === "up" ? "higher" : spec.concern === "down" ? "lower" : "higher or lower"}).
        </p>
      )}

      <details className="data-table">
        <summary>Show readings as a table</summary>
        <ReadingsTable spec={spec} observations={observations} baselines={sortedBaselines} missionStart={missionStart} />
      </details>
    </section>
  );
}

/** Latest baseline computed at or before a moment (baselines sorted oldest first). */
function baselineAt(baselines: Baseline[], t: number): Baseline | undefined {
  let found: Baseline | undefined;
  for (const b of baselines) {
    if (ms(b.as_of) <= t) found = b;
    else break;
  }
  return found;
}

/** Chart headline with actual values, no subjective words (charts.md › Descriptive content). */
function summarize(spec: SignalSpec, observations: Observation[], baselines: Baseline[], missionStart?: string): string {
  const latest = observations[observations.length - 1];
  const when = missionStart ? `day ${missionDay(latest.timestamp, missionStart)}` : formatMissionTime(latest.timestamp);
  const value = formatValue(latest.value, spec);
  const base = baselineAt(baselines, ms(latest.timestamp)) ?? baselines[baselines.length - 1];
  if (spec.kind === "ordinal") return `Latest: ${value} on ${when}.`;
  if (!base) return `Latest: ${value} on ${when}. Not enough history yet for your personal normal.`;
  const zone = zoneForReading(latest.value, spec, base);
  const diff = latest.value - base.center;
  const direction = diff > 0 ? "above" : "below";
  const state = zone ? ZONE_COPY[zone].long.toLowerCase() : "";
  if (zone === "green") return `Latest: ${value} on ${when}, ${state} (${formatValue(base.center, spec)}).`;
  return `Latest: ${value} on ${when}, ${withUnit(formatNumber(Math.abs(diff)), spec)} ${direction} your normal of ${formatValue(base.center, spec)} — ${state}.`;
}

function TrendTooltip({
  active,
  payload,
  label,
  spec,
  missionStart,
  zoneOf,
  baselines,
}: {
  active?: boolean;
  payload?: readonly { payload?: Row }[];
  label?: number | string;
  spec: SignalSpec;
  missionStart?: string;
  zoneOf: (t: number, value: number) => Zone | null;
  baselines: Baseline[];
}) {
  if (!active || !payload?.length || label === undefined) return null;
  const row = payload[0]?.payload;
  if (!row || row.value === undefined) return null;
  const t = Number(label);
  const zone = zoneOf(t, row.value);
  const base = baselineAt(baselines, t);
  return (
    <div className="chart-tooltip">
      <p className="data">
        {missionStart ? `Day ${missionDay(t, missionStart)} · ` : ""}
        {formatMissionTime(new Date(t).toISOString())}
      </p>
      <p>{formatValue(row.value, spec)}</p>
      <p className="tooltip-zone">
        <LevelIcon level={zone ?? "none"} size={12} /> {zone ? ZONE_COPY[zone].long : NO_NORMAL}
      </p>
      {base && spec.kind !== "ordinal" && (
        <p className="secondary">
          Normal {formatNumber(base.center - base.spread)}–{withUnit(formatNumber(base.center + base.spread), spec)}
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
          <th scope="col">State</th>
          <th scope="col">Your normal</th>
        </tr>
      </thead>
      <tbody>
        {recent.map((o) => {
          const base = baselineAt(baselines, ms(o.timestamp));
          const zone = zoneForReading(o.value, spec, base);
          return (
            <tr key={o.observation_id ?? o.timestamp}>
              <td className="data">{missionStart ? missionDay(o.timestamp, missionStart) : "—"}</td>
              <td className="data">{formatMissionTime(o.timestamp)}</td>
              <td>{formatValue(o.value, spec)}</td>
              <td>
                <span className="table-zone">
                  <LevelIcon level={zone ?? "none"} size={12} /> {zone ? ZONE_COPY[zone].short : NO_NORMAL}
                </span>
              </td>
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
