import type { SignalSpec } from "../api/types";

/** Steps from the good end of an ordinal scale: 0 for none (or the best mood), then 1, 2, 3. */
export function severitySteps(value: number, spec: Pick<SignalSpec, "plausible_min" | "plausible_max" | "concern">): number {
  return spec.concern === "down" ? spec.plausible_max - value : value - spec.plausible_min;
}
