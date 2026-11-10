import { createContext, useContext } from "react";
import type { CrewMember, SignalRegistry, SignalSpec } from "../api/types";

export interface RegistryValue {
  registry: SignalRegistry;
  crew: CrewMember[];
  spec: (signal: string | null | undefined) => SignalSpec | undefined;
  member: (astronautId: string) => CrewMember | undefined;
}

export const RegistryContext = createContext<RegistryValue | null>(null);

/** Signal registry and crew list, shared by every screen. */
export function useRegistry(): RegistryValue {
  const value = useContext(RegistryContext);
  if (!value) throw new Error("useRegistry must be used inside RegistryProvider");
  return value;
}
