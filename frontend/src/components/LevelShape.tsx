/**
 * Recharts dot renderer: a circle in the level's colour. Chart points have no
 * room for the level's word, so each carries it as a tooltip and accessible
 * name (`label`); the chart's legend says what the colours mean. `level` null
 * draws a small neutral dot (no personal normal).
 */
export function LevelDot({
  cx,
  cy,
  color,
  level,
  label,
  stroke,
  neutral,
  r = 4.5,
}: {
  cx?: number;
  cy?: number;
  color?: string;
  level?: string | null;
  label?: string;
  stroke: string;
  neutral?: string;
  r?: number;
}) {
  if (cx === undefined || cy === undefined) return null;
  if (!level) return <circle cx={cx} cy={cy} r={3} fill={neutral ?? stroke} />;
  return (
    <circle cx={cx} cy={cy} r={r} fill={color} stroke={stroke} strokeWidth={1.5} role="img" aria-label={label}>
      {label && <title>{label}</title>}
    </circle>
  );
}
