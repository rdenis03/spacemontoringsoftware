import { shapePath } from "../lib/shapes";

/**
 * Recharts dot renderer in the level's shape (see lib/shapes.ts), so chart
 * points read without colour. `level` null draws a small neutral dot (no
 * personal normal).
 */
export function LevelDot({
  cx,
  cy,
  color,
  level,
  stroke,
  neutral,
  r = 4.5,
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
  if (!level) return <circle cx={cx} cy={cy} r={3} fill={neutral ?? stroke} />;
  return <path d={shapePath(level, cx, cy, r)} fill={color} stroke={stroke} strokeWidth={1.5} />;
}
