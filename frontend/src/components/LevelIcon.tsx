import { levelColor } from "../lib/levels";

/**
 * A distinct shape per level, so the level reads without colour:
 * green circle, yellow diamond, orange triangle, red octagon.
 * Decorative: the level word next to it is what screen readers announce.
 */
export function LevelIcon({ level, size = 20 }: { level: string; size?: number }) {
  const fill = levelColor(level);
  let shape;
  switch (level) {
    case "yellow":
      shape = <path d="M12 2 22 12 12 22 2 12Z" />;
      break;
    case "orange":
      shape = <path d="M12 2.5 22.5 21h-21Z" />;
      break;
    case "red":
      shape = <path d="M8 2h8l6 6v8l-6 6H8l-6-6V8Z" />;
      break;
    default:
      shape = <circle cx="12" cy="12" r="10" />;
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ fill, flexShrink: 0 }} aria-hidden="true" focusable="false">
      {shape}
    </svg>
  );
}
