import { useEffect, useState } from "react";

/**
 * Resolved colour tokens for chart libraries, which write colours into SVG
 * attributes where CSS variables are not reliable. Re-reads when the system
 * appearance or contrast setting changes. Every token read here is a plain
 * hex value in tokens.css (no color-mix), so it is safe in an SVG attribute.
 */
export interface Tokens {
  text: string;
  text2: string;
  text3: string;
  bg: string;
  card: string;
  fill: string;
  separator: string;
  accent: string;
  accentTint: string;
  level: Record<string, string>;
  ink: Record<string, string>;
  // older names kept for existing charts
  surface: string;
  n400: string;
  n500: string;
  n600: string;
  n700: string;
  n800: string;
  accent100: string;
  accent500: string;
  accent700: string;
}

function read(): Tokens {
  const style = getComputedStyle(document.documentElement);
  const get = (name: string) => style.getPropertyValue(name).trim();
  const levels = ["green", "yellow", "orange", "red"];
  const t = {
    text: get("--text"),
    text2: get("--text-2"),
    text3: get("--text-3"),
    bg: get("--bg"),
    card: get("--card"),
    fill: get("--fill"),
    separator: get("--separator"),
    accent: get("--accent"),
    accentTint: get("--accent-tint"),
    level: Object.fromEntries(levels.map((l) => [l, get(`--level-${l}`)])),
    ink: Object.fromEntries(levels.map((l) => [l, get(`--level-${l}-ink`)])),
  };
  return {
    ...t,
    surface: t.card,
    n400: t.separator,
    n500: t.text3,
    n600: t.text3,
    n700: t.text2,
    n800: t.text,
    accent100: t.accentTint,
    accent500: t.accent,
    accent700: t.accent,
  };
}

export function useTokens(): Tokens {
  const [tokens, setTokens] = useState(read);
  useEffect(() => {
    const queries = ["(prefers-color-scheme: dark)", "(prefers-contrast: more)"].map((q) => window.matchMedia(q));
    const update = () => setTokens(read());
    queries.forEach((q) => q.addEventListener("change", update));
    return () => queries.forEach((q) => q.removeEventListener("change", update));
  }, []);
  return tokens;
}
