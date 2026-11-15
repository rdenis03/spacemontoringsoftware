/**
 * Trends: every sensor in a list on the left (state, latest value, a
 * sparkline over the personal normal), and the chosen sensor over time on
 * coloured zones in a sticky frame on the right.
 */
import { useMemo, useState } from "react";
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
import { Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { LevelDot } from "../../components/LevelShape";
import { SeverityDots } from "../../components/SeverityDots";
import { Sparkline } from "../../components/Sparkline";
import { LoadError, Loading } from "../../components/StateMessage";
import { dayTickLabel, dayTicks, ms, paddedDomain } from "../../lib/chart";
import {
  categoryName,
  eventName,
  formatMissionTime,
  formatNumber,
  formatValue,
  missionDay,
  withUnit,
} from "../../lib/format";
import { levelInk } from "../../lib/levels";
import { useAsync } from "../../lib/useAsync";
import { useTokens } from "../../lib/useTokens";
import { severitySteps } from "../../lib/severity";
import { NO_NORMAL, ZONE_COPY, ZONE_STEPS, ZONES, type Zone, zoneForReading, zoneRanges } from "../../lib/zones";
import { useRegistry } from "../../state/registry-context";

interface Props {
  astronautId: string;
  status: DayResult | undefined;
  freshness: string;
}

/** How far back the sensor list looks for each signal's latest reading (weekly lab tests included). */
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
  const missionStart = member(astronautId)?.mission_start;

  const setSignal = (next: string) => {
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("signal", next);
        return p;
      },
      { replace: true },
    );
    // On narrow screens the chart sits below the list: bring it into view.
    if (window.matchMedia("(max-width: 900px)").matches) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      document.getElementById("trend-detail")?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    }
  };

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
      <aside className="sensor-list" aria-labelledby="sensors-heading">
        <div className="sensor-list__head">
          <h2 id="sensors-heading" className="section-label">
            All sensors
          </h2>
          <ZoneKey />
        </div>
        {overview.error ? (
          <LoadError error={overview.error} retry={overview.reload} what="sensor readings" />
        ) : !overview.data ? (
          <Loading what="sensors" />
        ) : (
          <SensorGroups
            readings={overview.data}
            baselines={status?.baselines ?? []}
            selected={signal}
            onSelect={setSignal}
            missionStart={missionStart}
          />
        )}
      </aside>

      <div id="trend-detail" className="trends__detail">
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
            missionStart={missionStart}
          />
        )}
      </div>
    </div>
  );
}

/* ---- every sensor, grouped ------------------------------------------------------------------ */

function SensorGroups({
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

  const series = useMemo(() => {
    const map = new Map<string, Observation[]>();
    for (const o of readings) {
      const list = map.get(o.signal) ?? [];
      list.push(o);
      map.set(o.signal, list);
    }
    for (const list of map.values()) list.sort((a, b) => ms(a.timestamp) - ms(b.timestamp));
    return map;
  }, [readings]);
  const baselineFor = new Map<string, Baseline>(baselines.map((b) => [b.signal, b]));

  return (
    <>
      {registry.categories.map((category) => {
        const signals = registry.signals.filter((x) => x.category === category);
        if (signals.length === 0) return null;
        return (
          <div key={category} className="sensor-group">
            <h3 className="group__title">{categoryName(category)}</h3>
            <ul className="group">
              {signals.map((spec) => {
                const points = series.get(spec.signal) ?? [];
                const reading = points[points.length - 1];
                const baseline = baselineFor.get(spec.signal);
                const ordinal = spec.kind === "ordinal";
                const zone = reading ? zoneForReading(reading.value, spec, baseline) : null;
                // Ordinal: the scale word is the state, with neutral severity dots.
                const state = !reading
                  ? "No recent reading"
                  : ordinal
                    ? capitalize(formatValue(reading.value, spec))
                    : zone
                      ? ZONE_COPY[zone].short
                      : NO_NORMAL;
                const when = reading && missionStart ? `day ${missionDay(reading.timestamp, missionStart)}` : "";
                return (
                  <li key={spec.signal}>
                    <button
                      type="button"
                      className="sensor-row"
                      aria-pressed={spec.signal === selected}
                      onClick={() => onSelect(spec.signal)}
                      aria-label={`${spec.label}: ${reading ? formatValue(reading.value, spec) : "no recent reading"}, ${state}${when ? `, ${when}` : ""}. Show trend.`}
                    >
                      {ordinal && reading ? (
                        <span className="sensor-row__dots">
                          <SeverityDots steps={severitySteps(reading.value, spec)} size={6} />
                        </span>
                      ) : (
                        <LevelIcon level={zone ?? "none"} size={12} />
                      )}
                      <span className="sensor-row__text">
                        <span className="sensor-row__label">{spec.label}</span>
                        <span className="sensor-row__line">
                          <span className="sensor-row__value data">{reading ? formatValue(reading.value, spec) : "—"}</span>
                          <span className="sensor-row__state" style={{ color: zone ? levelInk(zone) : "var(--text-2)" }}>
                            {state}
                          </span>
                        </span>
                      </span>
                      <Sparkline
                        points={points.map((o) => ({ t: ms(o.timestamp), v: o.value }))}
                        band={
                          baseline && !ordinal
                            ? { low: baseline.center - baseline.spread, high: baseline.center + baseline.spread }
                            : undefined
                        }
                        domain={ordinal ? [spec.plausible_min, spec.plausible_max] : undefined}
                        lastLevel={zone}
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </>
  );
}

/** Legend for the sensor states, shared by the list and the chart. */
function ZoneKey() {
  return (
    <ul className="zone-key" aria-label="Sensor states">
      {ZONES.map((zone) => (
        <li key={zone}>
          <LevelIcon level={zone} size={11} />
          {ZONE_COPY[zone].short}
        </li>
      ))}
      <li>
        <LevelIcon level="none" size={11} />
        {NO_NORMAL}
      </li>
    </ul>
  );
}

/* ---- one sensor over time, on coloured zones ------------------------------------------------ */

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
  const [showTable, setShowTable] = useState(false);
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
      values.push(c + sp * (upFar ? ZONE_STEPS[2] + 0.6 : 1.6), c - sp * (downFar ? ZONE_STEPS[2] + 0.6 : 1.6));
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
    return (
      <Frame className="trend">
        <span className="kicker">{spec.label}</span>
        <h2 className="trend__summary">No readings for {spec.label.toLowerCase()} yet.</h2>
      </Frame>
    );
  }

  const tMin = rows[0].t;
  const tMax = rows[rows.length - 1].t;
  const ticks = dayTicks(tMin, tMax, 7);
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
  const kicker = `${spec.label}${ordinal ? "" : ` · ${spec.unit_label}`} · ${observations.length} readings`;

  return (
    <Frame className="trend" aria-labelledby="trend-title">
      <span className="kicker">{kicker}</span>
      <h2 id="trend-title" className="trend__summary">
        {summary}
      </h2>
      <p className="trend__desc">{spec.description}</p>

      <figure className="trend__figure" role="img" aria-label={`Line chart of ${spec.label} over time${ordinal ? "" : " on coloured zones"}. ${summary}`}>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={rows} margin={{ top: 20, right: 4, bottom: 4, left: 4 }}>
            {zoneKeys.map((z) => (
              <Area
                key={z.key}
                dataKey={z.key}
                type="stepAfter"
                connectNulls
                isAnimationActive={false}
                fill={tokens.level[z.zone]}
                fillOpacity={0.1}
                stroke="none"
                activeDot={false}
                tooltipType="none"
              />
            ))}
            <CartesianGrid stroke={tokens.separator} strokeOpacity={0.6} vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[tMin, tMax]}
              ticks={ticks}
              tickFormatter={dayLabel}
              stroke={tokens.separator}
              tickLine={false}
              tick={{ fill: tokens.text2, fontSize: 12 }}
            />
            <YAxis
              orientation="right"
              domain={yDomain}
              ticks={yTicks}
              tickFormatter={yLabel}
              axisLine={false}
              tickLine={false}
              tick={{ fill: tokens.text2, fontSize: 12 }}
              width={ordinal ? 84 : 52}
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
                  fill={tokens.text3}
                  fillOpacity={0.12}
                  stroke="none"
                  label={{ value: eventName(e.event_type), position: "insideBottomLeft", fill: tokens.text2, fontSize: 12 }}
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
                stroke={tokens.text3}
                strokeDasharray="4 4"
                strokeWidth={1}
                tooltipType="none"
              />
            )}
            <Line
              dataKey="value"
              type={ordinal ? "stepAfter" : "linear"}
              connectNulls
              isAnimationActive={false}
              stroke={tokens.accent}
              strokeWidth={1.75}
              dot={(props: { cx?: number; cy?: number; payload?: Row }) => {
                const row = props.payload;
                const zone = row?.value !== undefined ? zoneOf(row.t, row.value) : null;
                if (ordinal && row?.value !== undefined && props.cx !== undefined && props.cy !== undefined) {
                  const word = capitalize(formatValue(row.value, spec));
                  return (
                    <circle
                      key={`${row.t}`}
                      cx={props.cx}
                      cy={props.cy}
                      r={observations.length > 20 ? 3.5 : 4.5}
                      fill={tokens.text2}
                      stroke={tokens.card}
                      strokeWidth={1.5}
                      role="img"
                      aria-label={word}
                    >
                      <title>{word}</title>
                    </circle>
                  );
                }
                return (
                  <LevelDot
                    key={`${row?.t}`}
                    cx={props.cx}
                    cy={props.cy}
                    level={row?.value !== undefined ? zone : null}
                    label={zone ? ZONE_COPY[zone].long : undefined}
                    color={zone ? tokens.level[zone] : undefined}
                    stroke={tokens.card}
                    neutral={tokens.text2}
                    r={observations.length > 20 ? 3.5 : 5}
                  />
                );
              }}
              activeDot={{ r: 5, fill: tokens.accent, stroke: tokens.card }}
              name={spec.label}
            />
            {anomalies.map((a) => (
              <ReferenceDot
                key={a.detected_at}
                x={ms(a.detected_at)}
                y={a.value}
                r={12}
                fill="none"
                stroke={tokens.text}
                strokeWidth={1.5}
                label={{ value: "Flagged today", position: "top", fill: tokens.text, fontSize: 12 }}
              />
            ))}
            <Tooltip
              content={<TrendTooltip spec={spec} missionStart={missionStart} zoneOf={zoneOf} baselines={sortedBaselines} />}
              cursor={{ stroke: tokens.separator, strokeWidth: 1 }}
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
        {ordinal
          ? (spec.scale_labels ?? []).map((word, i) => (
              <li key={word}>
                <SeverityDots steps={severitySteps(spec.plausible_min + i, spec)} size={6} /> {capitalize(word)}
              </li>
            ))
          : latestBaseline
            ? ZONES.map((zone, i) => (
                <li key={zone}>
                  <LevelIcon level={zone} size={11} /> {ZONE_COPY[zone].short}{" "}
                  {i === 0 ? `(< ${ZONE_STEPS[0]}×)` : i === 3 ? `(≥ ${ZONE_STEPS[2]}×)` : `(${ZONE_STEPS[i - 1]}–${ZONE_STEPS[i]}×)`}
                </li>
              ))
            : (
                <li>
                  <LevelIcon level="none" size={11} /> {NO_NORMAL}
                </li>
              )}
        <li>
          <span className="legend__event" /> Event
        </li>
        {anomalies.length > 0 && (
          <li>
            <span className="legend__ring" /> Flagged today
          </li>
        )}
        <li className="legend__note">
          {ordinal
            ? "Dots count the steps from none; level colours are kept for alert levels."
            : "A point's colour is how far that reading is from your normal."}
        </li>
      </ul>
      {!ordinal && latestBaseline && (
        <p className="trend__note">
          Zones are measured in your usual day-to-day variation, and only in the direction that matters for this signal (
          {spec.concern === "up" ? "higher" : spec.concern === "down" ? "lower" : "higher or lower"}).
        </p>
      )}

      <div className="trend__table">
        <button type="button" className="btn btn-ghost" aria-expanded={showTable} onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Hide readings table" : "Show readings as a table"}
        </button>
        {showTable && (
          <div className="table-scroll">
            <ReadingsTable spec={spec} observations={observations} baselines={sortedBaselines} missionStart={missionStart} />
          </div>
        )}
      </div>
    </Frame>
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
  if (!base) return `Latest: ${value} on ${when}. No personal normal for this signal yet.`;
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
      <p className="kicker">
        {missionStart ? `Day ${missionDay(t, missionStart)} · ` : ""}
        {formatMissionTime(new Date(t).toISOString())}
      </p>
      <p className="chart-tooltip__value">{formatValue(row.value, spec)}</p>
      {spec.kind === "ordinal" ? (
        <p className="chart-tooltip__zone">
          <SeverityDots steps={severitySteps(row.value, spec)} size={6} /> {capitalize(formatValue(row.value, spec))}
        </p>
      ) : (
        <p className="chart-tooltip__zone" style={{ color: zone ? levelInk(zone) : undefined }}>
          <LevelIcon level={zone ?? "none"} size={10} /> {zone ? ZONE_COPY[zone].long : NO_NORMAL}
        </p>
      )}
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
              <td>{missionStart ? missionDay(o.timestamp, missionStart) : "—"}</td>
              <td>{formatMissionTime(o.timestamp)}</td>
              <td>{formatValue(o.value, spec)}</td>
              <td>
                {spec.kind === "ordinal" ? (
                  <span className="table-zone">
                    <SeverityDots steps={severitySteps(o.value, spec)} size={6} /> {capitalize(formatValue(o.value, spec))}
                  </span>
                ) : (
                  <span className="table-zone" style={{ color: zone ? levelInk(zone) : undefined }}>
                    <LevelIcon level={zone ?? "none"} size={10} /> {zone ? ZONE_COPY[zone].short : NO_NORMAL}
                  </span>
                )}
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

function capitalize(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}
