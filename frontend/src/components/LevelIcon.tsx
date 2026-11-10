import { levelColor } from "../lib/levels";

/** Shape paths (24×24): a distinct shape per level, so it reads without colour. */
const LEVEL_PATHS: Record<string, string> = {
  green: "M12 2a10 10 0 1 1 0 20a10 10 0 1 1 0-20Z",
  yellow: "M12 2 22 12 12 22 2 12Z",
  orange: "M12 2.5 22.5 21h-21Z",
  red: "M3 3h18v18H3Z",
  none: "M12 3.5a8.5 8.5 0 1 1 0 17a8.5 8.5 0 1 1 0-17Z",
};

/**
 * Level mark: green circle, yellow diamond, orange triangle, red square;
 * "none" (no personal normal) is a hollow ring. Decorative — the word next
 * to it is what screen readers announce.
 */
export function LevelIcon({ level, size = 20 }: { level: string; size?: number }) {
  const known = level in LEVEL_PATHS && level !== "none";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ flexShrink: 0 }} aria-hidden="true" focusable="false">
      <path
        d={LEVEL_PATHS[known ? level : "none"]}
        style={
          known
            ? { fill: levelColor(level) }
            : { fill: "none", stroke: "var(--color-neutral-500)", strokeWidth: 2.5 }
        }
      />
    </svg>
  );
}
