/**
 * Severity is not a level: it is drawn with neutral dots, never level colours.
 * An empty ring for the good end of the scale (none), then one filled dot per
 * step (mild ●, moderate ●●, severe ●●●). The colour follows the text
 * (`currentColor`), so a selected option can show it in the accent.
 * Decorative: the scale word next to it is what screen readers announce.
 */
export function SeverityDots({ steps, size = 8 }: { steps: number; size?: number }) {
  const gap = size * 0.5;
  if (steps <= 0) {
    return (
      <svg width={size} height={size} viewBox="0 0 8 8" className="severity-dots" aria-hidden="true" focusable="false">
        <circle cx="4" cy="4" r="3.1" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    );
  }
  const width = steps * size + (steps - 1) * gap;
  return (
    <svg width={width} height={size} viewBox={`0 0 ${width} ${size}`} className="severity-dots" aria-hidden="true" focusable="false">
      {Array.from({ length: steps }, (_, i) => (
        <circle key={i} cx={i * (size + gap) + size / 2} cy={size / 2} r={size / 2} fill="currentColor" />
      ))}
    </svg>
  );
}

