/**
 * The only place the app talks to the backend. Every call goes to the ORBIT
 * HTTP API; the frontend never reads the database.
 */
import type {
  Baseline,
  ContextEvent,
  CrewMember,
  DayResult,
  Observation,
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

type Query = Record<string, string | string[] | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(API_BASE + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) url.searchParams.append(key, item);
  }
  return url.toString();
}

async function request<T>(path: string, init?: RequestInit & { query?: Query }): Promise<T> {
  const response = await fetch(buildUrl(path, init?.query), {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
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

  status: (id: string, signal?: AbortSignal) => request<DayResult>(`${crewPath(id)}/status`, { signal }),

  /** Readings; an empty `signals` list means every signal. */
  observations: (id: string, signals: string[], signal?: AbortSignal, start?: string) =>
    request<Observation[]>(`${crewPath(id)}/observations`, { signal, query: { signal: signals, start } }),

  baselines: (id: string, signalName: string, signal?: AbortSignal) =>
    request<Baseline[]>(`${crewPath(id)}/baselines`, { signal, query: { signal: signalName } }),

  assessments: (id: string, signal?: AbortSignal) =>
    request<RiskAssessment[]>(`${crewPath(id)}/assessments`, { signal }),

  events: (astronautId: string, signal?: AbortSignal) =>
    request<ContextEvent[]>("/api/events", { signal, query: { astronaut_id: astronautId } }),
};
