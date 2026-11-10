import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  /** True only while there is nothing to show yet. */
  loading: boolean;
  /** True during any request, including background refreshes. */
  refreshing: boolean;
  reload: () => void;
}

interface Options {
  /** Refetch on this interval (ms). Also refetches when the tab becomes visible. */
  pollMs?: number;
  /** Skip the request (for example while an id is not known yet). */
  enabled?: boolean;
}

/**
 * Loads data and keeps it fresh. Earlier data stays on screen while a
 * refresh runs, so polling never makes the page flash.
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  { pollMs, enabled = true }: Options = {},
): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(() => setTick((n) => n + 1), []);

  // New inputs (another astronaut, another signal): drop the old data.
  useEffect(() => {
    setData(undefined);
    setError(null);
  }, deps);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setRefreshing(true);
    loadRef
      .current(controller.signal)
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setRefreshing(false);
      });
    return () => controller.abort();
  }, [...deps, tick, enabled]);

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

  return { data, error, loading: data === undefined && error === null && enabled, refreshing, reload };
}
