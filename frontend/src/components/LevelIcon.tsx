import { levelColor } from "../lib/levels";

/**
 * Level mark: a circle in the level's colour; "none" (no personal normal) is
 * a hollow ring. A level always has its word next to it, so the mark is
 * decorative by default. Where there is no room for the word, pass `label`:
 * the mark then carries it as its accessible name and tooltip.
 */
export function LevelIcon({ level, size = 20, label }: { level: string; size?: number; label?: string }) {
  const known = level !== "none";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      style={{ flexShrink: 0 }}
      focusable="false"
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {label && <title>{label}</title>}
      {known ? (
        <circle cx="12" cy="12" r="10" style={{ fill: levelColor(level) }} />
      ) : (
        <circle cx="12" cy="12" r="8.5" style={{ fill: "none", stroke: "var(--text-2)", strokeWidth: 2.5 }} />
      )}
    </svg>
  );
}
