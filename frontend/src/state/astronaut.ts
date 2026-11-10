import { useSearchParams } from "react-router-dom";
import { useRegistry } from "./registry";

/**
 * The astronaut being viewed lives in the URL (`?astronaut=AST-01`), so a
 * reload or a shared link shows the same person. Defaults to the first crew member.
 */
export function useAstronaut(): [string, (id: string) => void] {
  const [params, setParams] = useSearchParams();
  const { crew } = useRegistry();
  const requested = params.get("astronaut");
  const current = crew.some((m) => m.astronaut_id === requested) ? requested! : (crew[0]?.astronaut_id ?? "");
  const select = (id: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("astronaut", id);
        return next;
      },
      { replace: true },
    );
  return [current, select];
}
