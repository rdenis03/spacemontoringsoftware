import type { SignalSpec } from "../api/types";
import { formatNumber, formatValue, withUnit } from "../lib/format";
import { levelColor } from "../lib/levels";
import { zoneForReading } from "../lib/zones";
import "./NormalBand.css";

interface Props {
  value: number;
  center: number;
  spread: number;
  spec: SignalSpec | undefined;
}

/**
 * ORBIT's signature element: your personal normal as a band, and where
 * today's reading sits against it. The same band appears, larger, in Trends.
 */
export function NormalBand({ value, center, spread, spec }: Props) {
  const low = center - spread;
  const high = center + spread;
  const reach = Math.max(spread * 3, Math.abs(value - center) * 1.25, 1e-9);
  const min = center - reach;
  const max = center + reach;
  const x = (v: number) => ((v - min) / (max - min)) * 100;

  const range = spec
    ? `${withUnit(formatNumber(low), spec)} to ${withUnit(formatNumber(high), spec)}`
    : `${formatNumber(low)} to ${formatNumber(high)}`;
  const label = `${spec?.label ?? "Reading"} ${formatValue(value, spec)}; your normal is ${range}`;
  // The dot takes the sensor's state colour (same zones as Trends).
  const zone = spec ? zoneForReading(value, spec, { center, spread }) : null;

  return (
    <svg className="normal-band" viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label={label}>
      <line x1="0" x2="100" y1="12" y2="12" className="normal-band__track" vectorEffect="non-scaling-stroke" />
      <rect x={x(low)} width={x(high) - x(low)} y="5" height="14" rx="2" className="normal-band__band" />
      <line x1={x(low)} x2={x(low)} y1="5" y2="19" className="normal-band__edge" vectorEffect="non-scaling-stroke" />
      <line x1={x(high)} x2={x(high)} y1="5" y2="19" className="normal-band__edge" vectorEffect="non-scaling-stroke" />
      <line x1={x(center)} x2={x(center)} y1="8" y2="16" className="normal-band__center" vectorEffect="non-scaling-stroke" />
      <ellipse
        cx={x(value)}
        cy="12"
        rx="2.4"
        ry="6"
        className="normal-band__dot"
        style={zone ? { fill: levelColor(zone) } : undefined}
      />
    </svg>
  );
}
