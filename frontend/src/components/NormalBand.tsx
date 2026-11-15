import type { SignalSpec } from "../api/types";
import { formatNumber, formatValue, withUnit } from "../lib/format";
import { NO_NORMAL, ZONE_COPY, zoneForReading } from "../lib/zones";
import { LevelIcon } from "./LevelIcon";
import "./NormalBand.css";

interface Props {
  value: number;
  center: number;
  spread: number;
  spec: SignalSpec | undefined;
}

/**
 * ORBIT's signature element: your personal normal as a band (center ±
 * spread) and today's reading as a circle in its state's colour (its word is the
 * marker's tooltip and accessible name).
 */
export function NormalBand({ value, center, spread, spec }: Props) {
  const reach = Math.max(spread * 3, Math.abs(value - center) * 1.25, 1e-9);
  const min = center - reach;
  const x = (v: number) => `${((v - min) / (2 * reach)) * 100}%`;
  const zone = spec ? zoneForReading(value, spec, { center, spread }) : null;

  const range = spec
    ? `${withUnit(formatNumber(center - spread), spec)} to ${withUnit(formatNumber(center + spread), spec)}`
    : `${formatNumber(center - spread)} to ${formatNumber(center + spread)}`;
  const label = `${spec?.label ?? "Reading"} ${formatValue(value, spec)}; your normal is ${range}`;

  return (
    <div className="normal-band" role="img" aria-label={label}>
      <span className="normal-band__track" />
      <span className="normal-band__band" style={{ left: x(center - spread), width: `${(spread / reach) * 50}%` }} />
      <span className="normal-band__center" style={{ left: x(center) }} />
      <span className="normal-band__dot" style={{ left: x(value) }}>
        <LevelIcon level={zone ?? "none"} size={14} label={zone ? ZONE_COPY[zone].long : NO_NORMAL} />
      </span>
    </div>
  );
}
