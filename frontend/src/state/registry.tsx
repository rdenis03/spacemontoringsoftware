import { useMemo, type ReactNode } from "react";
import type { CrewMember, SignalRegistry } from "../api/types";
import { RegistryContext, type RegistryValue } from "./registry-context";

/** Provides the signal registry and crew list, loaded once at start. */
export function RegistryProvider({
  registry,
  crew,
  children,
}: {
  registry: SignalRegistry;
  crew: CrewMember[];
  children: ReactNode;
}) {
  const value = useMemo<RegistryValue>(() => {
    const bySignal = new Map(registry.signals.map((s) => [s.signal, s]));
    const byId = new Map(crew.map((m) => [m.astronaut_id, m]));
    return {
      registry,
      crew,
      spec: (signal) => (signal ? bySignal.get(signal) : undefined),
      member: (id) => byId.get(id),
    };
  }, [registry, crew]);
  return <RegistryContext.Provider value={value}>{children}</RegistryContext.Provider>;
}
