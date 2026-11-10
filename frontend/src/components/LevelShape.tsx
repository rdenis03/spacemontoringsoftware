/**
 * Level-shaped chart dot, so a mark reads without colour. Same shapes as
 * LevelIcon: green circle, yellow diamond, orange triangle, red octagon.
 * `level` null draws a small neutral dot (no personal normal yet).
 */
export function LevelDot({
  cx,
  cy,
  color,
  level,
  stroke,
  neutral,
  r = 6,
}: {
  cx?: number;
  cy?: number;
  color?: string;
  level?: string | null;
  stroke: string;
  neutral?: string;
  r?: number;
}) {
  if (cx === undefined || cy === undefined) return null;
  let d: string;
  switch (level) {
    case "yellow":
      d = `M${cx} ${cy - r} L${cx + r} ${cy} L${cx} ${cy + r} L${cx - r} ${cy}Z`;
      break;
    case "orange":
      d = `M${cx} ${cy - r} L${cx + r} ${cy + r * 0.8} L${cx - r} ${cy + r * 0.8}Z`;
      break;
    case "red": {
      const a = r * 0.42;
      d = `M${cx - a} ${cy - r} L${cx + a} ${cy - r} L${cx + r} ${cy - a} L${cx + r} ${cy + a} L${cx + a} ${cy + r} L${cx - a} ${cy + r} L${cx - r} ${cy + a} L${cx - r} ${cy - a}Z`;
      break;
    }
    case "green":
      return <circle cx={cx} cy={cy} r={r - 1} fill={color} stroke={stroke} strokeWidth={1.5} />;
    default:
      return <circle cx={cx} cy={cy} r={3} fill={neutral ?? stroke} />;
  }
  return <path d={d} fill={color} stroke={stroke} strokeWidth={1.5} />;
}
