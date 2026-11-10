import type { AlertLevelThreshold } from "../api/types";

/**
 * Alert levels. The thresholds always come from `GET /api/signals`
 * (`alert_levels`); only the words shown to the astronaut live here.
 * The wording describes what to do, never a diagnosis.
 */
export const LEVEL_COPY: Record<string, { word: string; meaning: string }> = {
  green: { word: "Green", meaning: "Within your normal" },
  yellow: { word: "Yellow", meaning: "Keep an eye on it" },
  orange: { word: "Orange", meaning: "Act on it today" },
  red: { word: "Red", meaning: "Get help now" },
};

export function levelCopy(level: string) {
  return LEVEL_COPY[level] ?? { word: level.charAt(0).toUpperCase() + level.slice(1), meaning: "" };
}

/** Same rule as the backend: the highest level whose minimum the score reaches. */
export function levelForScore(score: number, thresholds: AlertLevelThreshold[]): string {
  const ordered = [...thresholds].sort((a, b) => a.min_score - b.min_score);
  let level = ordered[0]?.level ?? "green";
  for (const t of ordered) if (score >= t.min_score) level = t.level;
  return level;
}

export function levelRank(level: string, order: string[]): number {
  return order.indexOf(level);
}

/** Mark colour for a level (icon fills, chart points, bands). Level colours mean state and nothing else. */
export function levelColor(level: string): string {
  return `var(--level-${level}, var(--color-neutral-500))`;
}

/** Text colour for a level (words next to a mark). */
export function levelInk(level: string): string {
  return `var(--level-${level}-ink, var(--color-neutral-700))`;
}

/** A level colour mixed into transparency, for zone and band fills. */
export function levelTint(level: string, percent: number): string {
  return `color-mix(in srgb, ${levelColor(level)} ${percent}%, transparent)`;
}

/** Score bands for charts: [from, to) per level, ending at 100. */
export function levelBands(thresholds: AlertLevelThreshold[]) {
  const ordered = [...thresholds].sort((a, b) => a.min_score - b.min_score);
  return ordered.map((t, i) => ({ level: t.level, from: t.min_score, to: ordered[i + 1]?.min_score ?? 100 }));
}
