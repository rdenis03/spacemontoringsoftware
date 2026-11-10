import { API_BASE, ApiError, isNetworkError } from "../api/client";
import "./StateMessage.css";

/** Loading, empty and error states, shown in place of the content they replace. */
export function Loading({ what }: { what: string }) {
  return (
    <p className="state-message" role="status">
      Loading {what}…
    </p>
  );
}

export function LoadError({ error, retry, what }: { error: unknown; retry?: () => void; what: string }) {
  let title = `Couldn't load ${what}.`;
  let hint = error instanceof Error ? error.message : String(error);
  if (isNetworkError(error)) {
    title = "Can't reach the ORBIT API.";
    hint = `Nothing answered at ${API_BASE}. Start the backend with "python -m orbit serve" and try again.`;
  } else if (error instanceof ApiError && error.status === 404) {
    title = `No ${what} yet.`;
  }
  return (
    <div className="state-message state-message--error" role="alert">
      <p className="state-message__title">{title}</p>
      <p className="secondary">{hint}</p>
      {retry && (
        <button type="button" className="button" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}

/**
 * Quiet note when part of the analysis failed. The rest of the result is
 * still valid, so this informs rather than alarms.
 */
export function PartialNote({ errors }: { errors: readonly string[] }) {
  if (errors.length === 0) return null;
  return (
    <details className="partial-note">
      <summary>Part of the analysis is unavailable right now. This status uses everything else.</summary>
      <ul>
        {errors.map((e) => (
          <li key={e} className="data">
            {e}
          </li>
        ))}
      </ul>
    </details>
  );
}
