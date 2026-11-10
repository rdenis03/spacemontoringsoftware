import type { SignalSpec } from "../api/types";

const DAY_MS = 86_400_000;

/** Mission time, always UTC, from the data (never the wall clock). */
export function formatMissionTime(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(iso)) + " UTC";
}

export function formatDate(iso: string | number): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", timeZone: "UTC" }).format(new Date(iso));
}

/** Same rule as CrewMember.mission_day: 1 on launch day, counted in UTC days. */
export function missionDay(when: string | number, missionStart: string): number {
  const utcDay = (t: number) => Math.floor(t / DAY_MS);
  return utcDay(new Date(when).getTime()) - utcDay(new Date(missionStart).getTime()) + 1;
}

/** "crew_medical_officer" -> "Crew medical officer" */
export function humanize(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function decimals(value: number): number {
  const size = Math.abs(value);
  if (size >= 100) return 0;
  if (size >= 10) return 1;
  return 2;
}

export function formatNumber(value: number, places = decimals(value)): string {
  return value.toLocaleString("en-GB", { minimumFractionDigits: 0, maximumFractionDigits: places });
}

/** "34.6 °C", "97 %" or, for ordinal scales, the scale word ("mild"). */
export function formatValue(value: number, spec: SignalSpec | undefined): string {
  if (!spec) return formatNumber(value);
  if (spec.kind === "ordinal" && spec.scale_labels) {
    const word = spec.scale_labels[Math.round(value) - spec.plausible_min];
    if (word) return word;
  }
  return withUnit(formatNumber(value), spec);
}

export function withUnit(text: string, spec: SignalSpec): string {
  if (spec.kind === "ordinal") return text;
  return spec.unit_label === "%" ? `${text}%` : `${text} ${spec.unit_label}`;
}

export function signedNumber(value: number): string {
  const text = formatNumber(Math.abs(value));
  return value < 0 ? `−${text}` : `+${text}`;
}
