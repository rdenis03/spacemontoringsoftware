import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  /** True only while there is nothing to show yet. */
  loading: boolean;
  reload: () => void;
  /** Show this data now, without a request (a write that already returned the new value). */
  replace: (data: T) => void;
}

interface Options {
  /** Refetch on this interval (ms). Also refetches when the tab becomes visible. */
  pollMs?: number;
  /** Skip the request (for example while an id is not known yet). */
  enabled?: boolean;
}

interface Stored<T> {
  key: string;
  data: T | undefined;
  error: unknown;
}

/**
 * Loads data and keeps it fresh. Earlier data stays on screen while a
 * refresh runs, so polling never makes the page flash. When the inputs
 * change (another astronaut, another signal), old data is hidden at once.
 *
 * `deps` must be serialisable values (ids, names, timestamps).
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  { pollMs, enabled = true }: Options = {},
): AsyncState<T> {
  const key = JSON.stringify(deps);
  const [stored, setStored] = useState<Stored<T>>({ key, data: undefined, error: null });
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  const reload = useCallback(() => setTick((n) => n + 1), []);
  const replace = useCallback((data: T) => setStored({ key, data, error: null }), [key]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    loadRef.current(controller.signal).then(
      (data) => setStored({ key, data, error: null }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setStored((prev) => ({ key, data: prev.key === key ? prev.data : undefined, error }));
      },
    );
    return () => controller.abort();
  }, [key, tick, enabled]);

  useEffect(() => {
    if (!pollMs || !enabled) return;
    const id = window.setInterval(reload, pollMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [pollMs, enabled, reload]);

  const current = stored.key === key ? stored : { data: undefined, error: null };
  return {
    data: current.data,
    error: current.error,
    loading: enabled && current.data === undefined && current.error === null,
    reload,
    replace,
  };
}
