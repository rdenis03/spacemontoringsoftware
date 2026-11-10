import { useRef, type KeyboardEvent } from "react";
import "./SegmentedTabs.css";

interface Props<T extends string> {
  label: string;
  tabs: readonly { id: T; label: string }[];
  current: T;
  onChange: (id: T) => void;
  idPrefix: string;
}

/** Segmented control acting as tabs, with arrow-key navigation. */
export function SegmentedTabs<T extends string>({ label, tabs, current, onChange, idPrefix }: Props<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKey = (event: KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + tabs.length) % tabs.length;
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div className="segmented" role="tablist" aria-label={label}>
      {tabs.map((tab, i) => {
        const selected = tab.id === current;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${tab.id}`}
            aria-controls={`${idPrefix}-panel-${tab.id}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className="segmented__tab"
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
