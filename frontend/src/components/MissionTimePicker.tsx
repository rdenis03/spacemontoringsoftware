import { useEffect, useId, useRef, useState } from "react";
import "./MissionTimePicker.css";

/**
 * Mission day and time, editable for the demo: one quiet pill
 * ("Day 89 · 10:30 UTC") that opens a small panel with a day stepper and a
 * time field. Escape or a click outside closes it. Used by the chat and the
 * quick form.
 */
export function MissionTimePicker({
  day,
  time,
  onDay,
  onTime,
  defaultTime,
}: {
  day: number;
  time: string;
  onDay: (day: number) => void;
  onTime: (time: string) => void;
  defaultTime: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="mtime" ref={root}>
      <button
        ref={button}
        type="button"
        className="mtime__pill"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`Mission day ${day}, ${time} UTC. Change`}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7.5V12l3 2" />
        </svg>
        <span className="data">Day {day}</span>
        <span className="mtime__dot" aria-hidden="true" />
        <span className="data">{time} UTC</span>
      </button>

      {open && (
        <div id={id} className="mtime__panel" role="group" aria-label="Mission time">
          <div className="mtime__row">
            <span className="mtime__label" id={`${id}-day`}>
              Mission day
            </span>
            <div className="mtime__stepper" role="group" aria-labelledby={`${id}-day`}>
              <button type="button" className="mtime__step" aria-label="Previous day" disabled={day <= 1} onClick={() => onDay(Math.max(1, day - 1))}>
                <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M6 12h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
              <input
                className="mtime__day data"
                type="number"
                min={1}
                value={day}
                aria-labelledby={`${id}-day`}
                onChange={(e) => onDay(Math.max(1, Number(e.target.value) || 1))}
              />
              <button type="button" className="mtime__step" aria-label="Next day" onClick={() => onDay(day + 1)}>
                <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M6 12h12M12 6v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          </div>
          <label className="mtime__row">
            <span className="mtime__label">Time (UTC)</span>
            <input className="mtime__time data" type="time" value={time} onChange={(e) => onTime(e.target.value || defaultTime)} />
          </label>
          <p className="mtime__note">The demo mission runs in 2027.</p>
          <button type="button" className="btn btn-secondary mtime__done" onClick={() => setOpen(false)}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}
