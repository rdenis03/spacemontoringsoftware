import type { ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api/client";
import { LoadError, Loading } from "./components/StateMessage";
import { formatClock } from "./lib/format";
import { useAsync } from "./lib/useAsync";
import CheckinPage from "./routes/checkin/CheckinPage";
import CrewPage from "./routes/crew/CrewPage";
import EarthPage from "./routes/earth/EarthPage";
import TriagePage from "./routes/triage/TriagePage";
import DashboardPage from "./routes/dashboard/DashboardPage";
import { useAstronaut } from "./state/astronaut";
import { RegistryProvider } from "./state/registry";
import { useRegistry } from "./state/registry-context";
import "./App.css";

/** The status is polled every 60 s (ORBIT frontend rules). */
const POLL_MS = 60_000;

/** Line icons for the four screens, drawn for ORBIT (24×24, 1.6 stroke). */
const ICONS: Record<string, ReactNode> = {
  chat: <path d="M4.5 6.5a3 3 0 0 1 3-3h9a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3h-5.5l-4.5 3.5v-3.5a2.5 2.5 0 0 1-2-2.5Z" />,
  today: <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />,
  crew: (
    <>
      <circle cx="9" cy="8.5" r="3" />
      <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
      <circle cx="16.5" cy="9.5" r="2.5" />
      <path d="M16.5 14.5a4.5 4.5 0 0 1 4.5 4.5" />
    </>
  ),
  earth: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5s1.1-6.1 3.5-8.5Z" />
    </>
  ),
};

/** The tabs. The chat is the home screen; the quick form (/checkin) is a link in the chat. */
const SCREENS = [
  { id: "chat", path: "/", label: "Chat" },
  { id: "today", path: "/today", label: "Today" },
  { id: "crew", path: "/crew", label: "Crew" },
  { id: "earth", path: "/earth", label: "Earth" },
] as const;

/** Old chat links (/checkin/chat?session=…&astronaut=…) open the chat at / with the same query. */
function ChatRedirect() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: "/", search }} replace />;
}

function ScreenIcon({ id }: { id: string }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICONS[id]}
    </svg>
  );
}

export default function App() {
  const boot = useAsync(async (signal) => {
    const [registry, crew] = await Promise.all([api.signals(signal), api.crew(signal)]);
    return { registry, crew };
  }, []);

  if (!boot.data) {
    return (
      <div className="app">
        <header className="app-bar">
          <div className="app-bar__inner">
            <Brand />
          </div>
        </header>
        <main className="app-main">
          {boot.error ? <LoadError error={boot.error} retry={boot.reload} what="the mission data" /> : <Loading what="mission data" />}
        </main>
      </div>
    );
  }

  return (
    <RegistryProvider registry={boot.data.registry} crew={boot.data.crew}>
      <Shell />
    </RegistryProvider>
  );
}

function Brand({ title }: { title?: string }) {
  return (
    <span className="brand">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="4.5" className="brand__core" />
        <ellipse cx="16" cy="16" rx="13" ry="6" className="brand__orbit" transform="rotate(-25 16 16)" />
      </svg>
      <span className="brand__word">ORBIT</span>
      {title && (
        <span className="brand__title" aria-hidden="true">
          {title}
        </span>
      )}
    </span>
  );
}

function Shell() {
  const { crew } = useRegistry();
  const [astronaut, setAstronaut] = useAstronaut();
  const { pathname } = useLocation();
  const search = `?astronaut=${encodeURIComponent(astronaut)}`;
  const status = useAsync((signal) => api.status(astronaut, signal), [astronaut], {
    pollMs: POLL_MS,
    enabled: Boolean(astronaut),
  });
  const title = pathname === "/checkin" ? "Quick check-in" : (SCREENS.find((s) => s.path === pathname)?.label ?? "Chat");

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-bar">
        <div className="app-bar__inner">
          <Brand title={title} />
          <nav className="tabs" aria-label="Screens">
            {SCREENS.map((s) => (
              <NavLink key={s.id} to={{ pathname: s.path, search }} end={s.path === "/"} className="tabs__item">
                <ScreenIcon id={s.id} />
                <span>{s.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="app-bar__tools">
            <div className="clock">
              <span className="clock__label">Mission time</span>
              <span className="clock__value data">
                {status.data ? `Day ${status.data.mission_day} · ${formatClock(status.data.as_of)}` : "—"}
              </span>
            </div>
            <label className="astronaut-switcher">
              <span className="visually-hidden">Astronaut</span>
              <select className="input" value={astronaut} onChange={(e) => setAstronaut(e.target.value)}>
                {crew.map((m) => (
                  <option key={m.astronaut_id} value={m.astronaut_id}>
                    {m.callsign} · {m.astronaut_id}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </header>

      <main id="main" className="app-main">
        <Routes>
          <Route path="/" element={<TriagePage astronautId={astronaut} status={status} />} />
          <Route path="/today" element={<DashboardPage astronautId={astronaut} status={status} />} />
          <Route path="/checkin" element={<CheckinPage astronautId={astronaut} status={status} />} />
          <Route path="/checkin/chat" element={<ChatRedirect />} />
          <Route path="/crew" element={<CrewPage freshness={status.data?.as_of ?? ""} />} />
          <Route path="/earth" element={<EarthPage astronautId={astronaut} status={status} />} />
          <Route path="*" element={<Navigate to={{ pathname: "/", search }} replace />} />
        </Routes>
      </main>

      <footer className="app-footer">
        <span>Scores and action cards are illustrative for this demo, not medical advice.</span>
        <span className="data">Status refreshes every 60 s · mission time, UTC</span>
      </footer>
    </div>
  );
}
