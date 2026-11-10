import { useEffect, useState } from "react";

/**
 * Resolved colour tokens for chart libraries, which write colours into SVG
 * attributes where CSS variables are not reliable. Re-reads when the system
 * appearance or contrast setting changes.
 */
export interface Tokens {
  content: string;
  secondary: string;
  separator: string;
  raised: string;
  band: string;
  bandEdge: string;
  level: Record<string, string>;
}

function read(): Tokens {
  const style = getComputedStyle(document.documentElement);
  const get = (name: string) => style.getPropertyValue(name).trim();
  return {
    content: get("--content"),
    secondary: get("--secondary"),
    separator: get("--separator"),
    raised: get("--raised"),
    band: get("--band"),
    bandEdge: get("--band-edge"),
    level: {
      green: get("--level-green"),
      yellow: get("--level-yellow"),
      orange: get("--level-orange"),
      red: get("--level-red"),
    },
  };
}

export function useTokens(): Tokens {
  const [tokens, setTokens] = useState(read);
  useEffect(() => {
    const queries = ["(prefers-color-scheme: light)", "(prefers-contrast: more)"].map((q) => window.matchMedia(q));
    const update = () => setTokens(read());
    queries.forEach((q) => q.addEventListener("change", update));
    return () => queries.forEach((q) => q.removeEventListener("change", update));
  }, []);
  return tokens;
}
