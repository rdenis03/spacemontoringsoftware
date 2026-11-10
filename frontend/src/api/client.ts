/**
 * The only place the app talks to the backend. Every call goes to the ORBIT
 * HTTP API; the frontend never reads the database.
 */
import type {
  Baseline,
  CheckIn,
  ContextEvent,
  CrewMember,
  DayResult,
  Observation,
  OverviewRow,
  RiskAssessment,
  SignalRegistry,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** True when the API could not be reached at all (server down, wrong URL). */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

/**
 * Plain-language messages from an API error. FastAPI sends either a string,
 * a list of strings (our 422s) or a list of {loc, msg} validation errors.
 */
export function errorMessages(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [error instanceof Error ? error.message : String(error)];
  const { detail } = error;
  if (typeof detail === "string") return [detail];
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) {
        const loc = Array.isArray((item as { loc?: unknown }).loc)
          ? ((item as { loc: (string | number)[] }).loc.filter((p) => p !== "body").join(" › "))
          : "";
        return loc ? `${loc}: ${(item as { msg: string }).msg}` : (item as { msg: string }).msg;
      }
      return JSON.stringify(item);
    });
  }
  return [error.message];
}

type Query = Record<string, string | string[] | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(API_BASE + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) url.searchParams.append(key, item);
  }
  return url.toString();
}

async function request<T>(path: string, init: RequestInit & { query?: Query } = {}): Promise<T> {
  const { query, ...fetchInit } = init;
  const response = await fetch(buildUrl(path, query), {
    ...fetchInit,
    headers: { Accept: "application/json", ...(fetchInit.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      // body was not JSON; keep the status text
    }
    const message = typeof detail === "string" ? detail : response.statusText || `HTTP ${response.status}`;
    throw new ApiError(response.status, message, detail);
  }
  return (await response.json()) as T;
}

const crewPath = (id: string) => `/api/crew/${encodeURIComponent(id)}`;

export const api = {
  signals: (signal?: AbortSignal) => request<SignalRegistry>("/api/signals", { signal }),

  crew: (signal?: AbortSignal) => request<CrewMember[]>("/api/crew", { signal }),

  /** Latest level and score per astronaut (crew view). */
  overview: (signal?: AbortSignal) => request<OverviewRow[]>("/api/overview", { signal }),

  status: (id: string, signal?: AbortSignal) => request<DayResult>(`${crewPath(id)}/status`, { signal }),

  /** Readings; an empty `signals` list means every signal. */
  observations: (id: string, signals: string[], signal?: AbortSignal, start?: string) =>
    request<Observation[]>(`${crewPath(id)}/observations`, { signal, query: { signal: signals, start } }),

  baselines: (id: string, signalName: string, signal?: AbortSignal) =>
    request<Baseline[]>(`${crewPath(id)}/baselines`, { signal, query: { signal: signalName } }),

  assessments: (id: string, signal?: AbortSignal) =>
    request<RiskAssessment[]>(`${crewPath(id)}/assessments`, { signal }),

  /** Saves the daily check-in and re-assesses at once; 422 lists what is wrong. */
  checkin: (id: string, body: CheckIn, signal?: AbortSignal) =>
    request<DayResult>(`${crewPath(id)}/checkin`, { method: "POST", body: JSON.stringify(body), signal }),

  events: (astronautId: string, signal?: AbortSignal) =>
    request<ContextEvent[]>("/api/events", { signal, query: { astronaut_id: astronautId } }),
};
