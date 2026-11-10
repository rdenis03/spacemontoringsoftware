import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { CrewMember, SignalRegistry, SignalSpec } from "../api/types";

interface RegistryValue {
  registry: SignalRegistry;
  crew: CrewMember[];
  spec: (signal: string | null | undefined) => SignalSpec | undefined;
  member: (astronautId: string) => CrewMember | undefined;
}

const RegistryContext = createContext<RegistryValue | null>(null);

/** Signal registry and crew list, loaded once at start and shared by every screen. */
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

export function useRegistry(): RegistryValue {
  const value = useContext(RegistryContext);
  if (!value) throw new Error("useRegistry must be used inside RegistryProvider");
  return value;
}
