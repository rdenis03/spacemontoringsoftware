import { missionDay } from "./format";

const DAY_MS = 86_400_000;

/**
 * X-axis ticks at UTC midnights, thinned to at most `maxTicks`, labelled by
 * mission day. Familiar, evenly spaced values (charts.md › Axes).
 */
export function dayTicks(min: number, max: number, maxTicks = 8): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
  const first = Math.ceil(min / DAY_MS) * DAY_MS;
  const days: number[] = [];
  for (let t = first; t <= max; t += DAY_MS) days.push(t);
  const step = Math.max(1, Math.ceil(days.length / maxTicks));
  return days.filter((_, i) => i % step === 0);
}

export function dayTickLabel(missionStart: string | undefined) {
  return (t: number) => (missionStart ? `Day ${missionDay(t, missionStart)}` : new Date(t).toISOString().slice(5, 10));
}

/** Padded numeric domain so marks never touch the plot edges. */
export function paddedDomain(values: number[], pad = 0.12): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return [0, 1];
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (lo === hi) {
    const nudge = Math.abs(lo) * 0.05 || 1;
    lo -= nudge;
    hi += nudge;
  }
  const span = hi - lo;
  return [lo - span * pad, hi + span * pad];
}

export const ms = (iso: string) => new Date(iso).getTime();
