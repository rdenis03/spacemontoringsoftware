/**
 * Per-sensor state: how far a reading is from the astronaut's own normal,
 * in the worrying direction only, shown with the same four coloured
 * circles as the alert levels, always with a word.
 *
 * Continuous signals: distance in units of the personal spread
 * (|value − center| / spread, roughly standard deviations):
 *   green  < 1.5   close to your normal (the detector does not flag it)
 *   yellow 1.5–2.5 slightly outside (the detector's drift range)
 *   orange 2.5–4   outside (from the detector's spike threshold)
 *   red    ≥ 4     far outside
 * The first two steps match the starter detector's defaults in orbit.toml
 * (drift_threshold 1.5, threshold 2.5), so a sensor's colour agrees with
 * what the analysis flags. Update them if the team retunes the detector;
 * they are not exposed by the API yet.
 * Ordinal signals (symptoms, mood, stress) get no zone: their scale is a
 * severity, drawn with neutral dots (SeverityDots), never level colours.
 *
 * These steps are a display choice for the demo, not clinical thresholds.
 */
import type { Baseline, SignalSpec } from "../api/types";

export type Zone = "green" | "yellow" | "orange" | "red";
export const ZONES: readonly Zone[] = ["green", "yellow", "orange", "red"];

/** Spreads from the center where yellow, orange and red begin. */
export const ZONE_STEPS = [1.5, 2.5, 4] as const;

export const ZONE_COPY: Record<Zone, { short: string; long: string }> = {
  green: { short: "Normal", long: "Close to your normal" },
  yellow: { short: "Slightly outside", long: "Slightly outside your normal" },
  orange: { short: "Outside", long: "Outside your normal" },
  red: { short: "Far outside", long: "Far outside your normal" },
};

/** Signals without a personal baseline (labs, context) or before enough history. */
export const NO_NORMAL = "No personal normal";

/** Signed distance from the center in spreads; positive means worrying. */
export function worryingDistance(value: number, center: number, spread: number, concern: string): number {
  const z = (value - center) / spread;
  if (concern === "up") return z;
  if (concern === "down") return -z;
  return Math.abs(z);
}

function zoneForDistance(distance: number): Zone {
  if (distance < ZONE_STEPS[0]) return "green";
  if (distance < ZONE_STEPS[1]) return "yellow";
  if (distance < ZONE_STEPS[2]) return "orange";
  return "red";
}

export function zoneForReading(
  value: number,
  spec: SignalSpec,
  baseline: Pick<Baseline, "center" | "spread"> | undefined,
): Zone | null {
  // Ordinal signals (symptoms, mood, stress) are severity, not a level: no zone, neutral dots instead.
  if (spec.kind === "ordinal") return null;
  if (!baseline || baseline.spread <= 0) return null;
  return zoneForDistance(worryingDistance(value, baseline.center, baseline.spread, spec.concern));
}

/**
 * Value ranges of each zone around one baseline, for drawing chart bands.
 * Only the worrying side gets yellow/orange/red; `outer` closes the red band.
 */
export function zoneRanges(
  center: number,
  spread: number,
  concern: string,
  outer: [number, number],
): { key: string; zone: Zone; range: [number, number] }[] {
  const [s1, s2, s3] = ZONE_STEPS.map((k) => k * spread);
  const out: { key: string; zone: Zone; range: [number, number] }[] = [
    { key: "z_green", zone: "green", range: [center - s1, center + s1] },
  ];
  if (concern === "up" || concern === "both") {
    out.push(
      { key: "z_yellow_up", zone: "yellow", range: [center + s1, center + s2] },
      { key: "z_orange_up", zone: "orange", range: [center + s2, center + s3] },
      { key: "z_red_up", zone: "red", range: [center + s3, Math.max(outer[1], center + s3)] },
    );
  }
  if (concern === "down" || concern === "both") {
    out.push(
      { key: "z_yellow_down", zone: "yellow", range: [center - s2, center - s1] },
      { key: "z_orange_down", zone: "orange", range: [center - s3, center - s2] },
      { key: "z_red_down", zone: "red", range: [Math.min(outer[0], center - s3), center - s3] },
    );
  }
  return out;
}
