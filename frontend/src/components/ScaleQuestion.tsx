import { useId } from "react";
import type { SignalSpec } from "../api/types";
import { severitySteps } from "../lib/severity";
import { SeverityDots } from "./SeverityDots";
import "./ScaleQuestion.css";

/**
 * One question on a word scale: a segmented row of radio buttons, each with
 * neutral severity dots (severity is not an alert level, so no level colours). Words, label and description come from the signal registry.
 * Used by the daily check-in (M11) and to correct a finding in the chat (M15).
 */
export function ScaleQuestion({
  spec,
  value,
  onChange,
  optional = false,
  describe = true,
}: {
  spec: SignalSpec;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  optional?: boolean;
  /** false hides the registry description (the chat report shows the label only). */
  describe?: boolean;
}) {
  const name = useId();
  const words = spec.scale_labels ?? [];
  return (
    <div className="scale" role="radiogroup" aria-labelledby={`${name}-label`} aria-describedby={describe ? `${name}-desc` : undefined}>
      <div className="scale__text">
        <span id={`${name}-label`} className="scale__label">
          {spec.label}
        </span>
        {describe && (
          <span id={`${name}-desc`} className="scale__desc">
            {spec.description}
          </span>
        )}
      </div>
      <div className="scale__controls">
        <div className="scale__options">
          {words.map((word, i) => {
            const optionValue = spec.plausible_min + i;
            const checked = value === optionValue;
            return (
              <label key={word} className="scale__option" data-checked={checked || undefined}>
                <input type="radio" name={name} value={optionValue} checked={checked} onChange={() => onChange(optionValue)} />
                <SeverityDots steps={severitySteps(optionValue, spec)} size={7} />
                <span>{word.charAt(0).toUpperCase() + word.slice(1)}</span>
              </label>
            );
          })}
        </div>
        {optional && value !== null && value !== undefined && (
          <button type="button" className="btn btn-ghost" onClick={() => onChange(null)}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
