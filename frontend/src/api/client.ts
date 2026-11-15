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
  EarthPacket,
  Health,
  Observation,
  OutboxItem,
  OverviewRow,
  RiskAssessment,
  SignalRegistry,
  TriageConfirmBody,
  TriageConfirmed,
  TriageReplyBody,
  TriageResult,
  TriageSession,
  TriageStartBody,
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
const triagePath = (id: string, sessionId: string) => `${crewPath(id)}/triage/${encodeURIComponent(sessionId)}`;

export const api = {
  signals: (signal?: AbortSignal) => request<SignalRegistry>("/api/signals", { signal }),

  crew: (signal?: AbortSignal) => request<CrewMember[]>("/api/crew", { signal }),

  /** Latest level and score per astronaut (crew view). */
  overview: (signal?: AbortSignal) => request<OverviewRow[]>("/api/overview", { signal }),

  health: (signal?: AbortSignal) => request<Health>("/api/health", { signal }),

  /** Latest result; `view: "shared"` is the crew's view with private reasons hidden (M14). */
  status: (id: string, signal?: AbortSignal, view?: "shared") =>
    request<DayResult>(`${crewPath(id)}/status`, { signal, query: { view } }),

  /** A past assessment's full result (B13); `asOf` must be an `assessed_at` from /assessments. */
  day: (id: string, asOf: string, signal?: AbortSignal, view?: "shared") =>
    request<DayResult>(`${crewPath(id)}/day`, { signal, query: { as_of: asOf, view } }),

  /** What would be sent to Earth for a period, after the consent filter (M13). */
  earthPacket: (id: string, start: string, end: string, signal?: AbortSignal) =>
    request<EarthPacket>(`${crewPath(id)}/earth-packet`, { signal, query: { start, end } }),

  /** Package a period and queue it for Earth; `delayMinutes` overrides [comms] in orbit.toml. */
  sendPacket: (id: string, start: string, end: string, delayMinutes?: number) =>
    request<OutboxItem>(`${crewPath(id)}/earth-packet/send`, {
      method: "POST",
      query: { start, end, delay_minutes: delayMinutes === undefined ? undefined : String(delayMinutes) },
    }),

  outbox: (astronautId?: string, signal?: AbortSignal) =>
    request<OutboxItem[]>("/api/outbox", { signal, query: { astronaut_id: astronautId } }),

  /** Set the categories shared with Earth. */
  consent: (id: string, categories: string[]) =>
    request<CrewMember>(`${crewPath(id)}/consent`, {
      method: "PUT",
      body: JSON.stringify({ share_with_earth: categories } satisfies { share_with_earth: string[] }),
    }),

  /** Readings; an empty `signals` list means every signal. */
  observations: (id: string, signals: string[], signal?: AbortSignal, start?: string) =>
    request<Observation[]>(`${crewPath(id)}/observations`, { signal, query: { signal: signals, start } }),

  baselines: (id: string, signalName: string, signal?: AbortSignal) =>
    request<Baseline[]>(`${crewPath(id)}/baselines`, { signal, query: { signal: signalName } }),

  /** Score history, oldest first; `end` keeps only assessments at or before that moment. */
  assessments: (id: string, signal?: AbortSignal, end?: string) =>
    request<RiskAssessment[]>(`${crewPath(id)}/assessments`, { signal, query: { end } }),

  /** Saves the daily check-in and re-assesses at once; 422 lists what is wrong. */
  checkin: (id: string, body: CheckIn, signal?: AbortSignal) =>
    request<DayResult>(`${crewPath(id)}/checkin`, { method: "POST", body: JSON.stringify(body), signal }),

  events: (astronautId: string, signal?: AbortSignal) =>
    request<ContextEvent[]>("/api/events", { signal, query: { astronaut_id: astronautId } }),

  // ---- symptom triage, the chat check-in (M15): the astronaut's own view only ----

  /** Start a chat with the first message. Saves nothing as a check-in until confirm. */
  triageStart: (id: string, body: TriageStartBody) =>
    request<TriageResult>(`${crewPath(id)}/triage`, { method: "POST", body: JSON.stringify(body) }),

  /** Answer the open question (`value: null` skips it), add `text`, or say `done: true`. */
  triageAnswer: (id: string, sessionId: string, body: TriageReplyBody) =>
    request<TriageResult>(`${triagePath(id, sessionId)}/answer`, { method: "POST", body: JSON.stringify(body) }),

  /** Save the findings as a check-in and re-assess. `day` is null when a red flag escalated instead. */
  triageConfirm: (id: string, sessionId: string, body: TriageConfirmBody = {}) =>
    request<TriageConfirmed>(`${triagePath(id, sessionId)}/confirm`, { method: "POST", body: JSON.stringify(body) }),

  /** Close the chat without saving anything. */
  triageCancel: (id: string, sessionId: string) =>
    request<TriageSession>(`${triagePath(id, sessionId)}/cancel`, { method: "POST" }),

  triageSession: (id: string, sessionId: string, signal?: AbortSignal) =>
    request<TriageSession>(triagePath(id, sessionId), { signal }),

  /** This astronaut's chats, newest first (`start`/`end` on when they started, real time). */
  triageSessions: (id: string, signal?: AbortSignal, start?: string, end?: string) =>
    request<TriageSession[]>(`${crewPath(id)}/triage`, { signal, query: { start, end } }),
};
