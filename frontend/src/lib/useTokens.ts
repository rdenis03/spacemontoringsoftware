import { useEffect, useState } from "react";

/**
 * Resolved colour tokens for chart libraries, which write colours into SVG
 * attributes where CSS variables are not reliable. Re-reads when the system
 * appearance or contrast setting changes. Only plain colours are read here
 * (no color-mix), so every value is safe in an SVG attribute.
 */
export interface Tokens {
  text: string;
  bg: string;
  surface: string;
  n400: string;
  n500: string;
  n600: string;
  n700: string;
  n800: string;
  accent: string;
  accent100: string;
  accent500: string;
  accent700: string;
  level: Record<string, string>;
  ink: Record<string, string>;
  // older names kept for existing charts
  content: string;
  secondary: string;
  separator: string;
  raised: string;
  band: string;
  bandEdge: string;
}

function read(): Tokens {
  const style = getComputedStyle(document.documentElement);
  const get = (name: string) => style.getPropertyValue(name).trim();
  const levels = ["green", "yellow", "orange", "red"];
  const t = {
    text: get("--color-text"),
    bg: get("--color-bg"),
    surface: get("--color-surface"),
    n400: get("--color-neutral-400"),
    n500: get("--color-neutral-500"),
    n600: get("--color-neutral-600"),
    n700: get("--color-neutral-700"),
    n800: get("--color-neutral-800"),
    accent: get("--color-accent"),
    accent100: get("--color-accent-100"),
    accent500: get("--color-accent-500"),
    accent700: get("--color-accent-700"),
    level: Object.fromEntries(levels.map((l) => [l, get(`--level-${l}`)])),
    ink: Object.fromEntries(levels.map((l) => [l, get(`--level-${l}-ink`)])),
  };
  return {
    ...t,
    content: t.text,
    secondary: t.n700,
    separator: t.n400,
    raised: t.bg,
    band: t.accent100,
    bandEdge: t.accent500,
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
