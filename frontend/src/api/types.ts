/**
 * Friendly names for the API types.
 *
 * Everything here comes from `schema.ts`, which is generated from the
 * backend's OpenAPI document (`npm run types`). Do not hand-write model
 * shapes; regenerate after every backend change.
 *
 * The one exception is the signal registry: `GET /api/signals` is declared
 * as a plain dict in the backend, so OpenAPI has no shape for it. Its shape
 * is defined by `orbit/schema/export.py::registry_document` and mirrored in
 * `schemas/signals.json`.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type DayResult = Schemas["DayResult"];
export type RiskAssessment = Schemas["RiskAssessment"];
export type Contributor = Schemas["Contributor"];
export type ActionCard = Schemas["ActionCard"];
export type Anomaly = Schemas["Anomaly"];
export type Baseline = Schemas["Baseline"];
export type Observation = Schemas["Observation"];
export type ContextEvent = Schemas["ContextEvent"];
export type CrewMember = Schemas["CrewMember"];
export type CheckIn = Schemas["CheckIn"];
export type ValidationError = Schemas["ValidationError"];
export type OverviewRow = Schemas["OverviewRow"];
export type EarthPacket = Schemas["EarthPacket"];
export type OutboxItem = Schemas["OutboxItem"];
export type ConsentUpdate = Schemas["ConsentUpdate"];

/** `GET /api/health` is declared as a plain dict; this mirrors what it returns. */
export interface Health {
  status: string;
  mission: string;
  schema_version: string;
  modules: Record<string, string>;
  counts: Record<string, number>;
  comms: { one_way_delay_minutes: number };
}

/** Mirrors `registry_document()` in orbit/schema/export.py. */
export interface SignalSpec {
  signal: string;
  label: string;
  category: string;
  kind: "continuous" | "ordinal" | string;
  unit: string;
  unit_label: string;
  plausible_min: number;
  plausible_max: number;
  concern: "up" | "down" | "both" | string;
  cadence: string;
  description: string;
  scale_labels: string[] | null;
  allowed_sources: string[];
}

export interface AlertLevelThreshold {
  level: string;
  min_score: number;
}

export interface SignalRegistry {
  schema_version: string;
  categories: string[];
  default_shared_categories: string[];
  alert_levels: AlertLevelThreshold[];
  alert_level_order: string[];
  signals: SignalSpec[];
}
