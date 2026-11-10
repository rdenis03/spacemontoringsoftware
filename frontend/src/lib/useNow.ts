import { useEffect, useState } from "react";

/**
 * Wall-clock time, refreshed every `intervalMs`. Only for the comms
 * countdown, which simulates a real transmission delay; everything about
 * health uses mission time from the data.
 */
export function useNow(intervalMs = 1000, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, enabled]);
  return now;
}
