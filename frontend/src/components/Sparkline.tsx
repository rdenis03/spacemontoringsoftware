import { levelColor } from "../lib/levels";

interface Props {
  points: { t: number; v: number }[];
  /** The personal normal (center ± spread), drawn as a band behind the line. */
  band?: { low: number; high: number };
  /** Fixed value range (ordinal scales); otherwise fitted to points and band. */
  domain?: [number, number];
  /** State of the last point: drawn as a circle in that level's colour. */
  lastLevel?: string | null;
  width?: number;
  height?: number;
  stroke?: string;
}

/**
 * A small trend line with the personal normal behind it, the last point a
 * circle in its state's colour. Decorative: the row it sits in states value and state
 * in words.
 */
export function Sparkline({
  points,
  band,
  domain,
  lastLevel,
  width = 84,
  height = 26,
  stroke = "var(--accent)",
}: Props) {
  if (points.length === 0) return <svg width={width} height={height} aria-hidden="true" />;

  let [lo, hi] = domain ?? [
    Math.min(...points.map((p) => p.v), band ? band.low - (band.high - band.low) * 0.1 : Infinity),
    Math.max(...points.map((p) => p.v), band ? band.high + (band.high - band.low) * 0.1 : -Infinity),
  ];
  if (hi === lo) {
    hi += 1;
    lo -= 1;
  }
  const padX = 4;
  const padY = 4;
  const n = points.length;
  const X = (i: number) => padX + (n === 1 ? 0.5 : i / (n - 1)) * (width - padX * 2);
  const Y = (v: number) => height - padY - ((v - lo) / (hi - lo)) * (height - padY * 2);
  const path = points.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(p.v).toFixed(1)}`).join("");
  const last = points[n - 1];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" style={{ flexShrink: 0 }}>
      {band && (
        <rect
          x="0"
          width={width}
          y={Math.max(0, Y(band.high))}
          height={Math.max(0, Math.min(height, Y(band.low)) - Math.max(0, Y(band.high)))}
          style={{ fill: "var(--accent-tint)" }}
        />
      )}
      <path d={path} fill="none" style={{ stroke }} strokeWidth={1.5} />
      <circle cx={X(n - 1)} cy={Y(last.v)} r={3.2} style={{ fill: lastLevel ? levelColor(lastLevel) : "var(--text-2)" }} />
    </svg>
  );
}
