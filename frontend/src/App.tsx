import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { LoadError, Loading } from "./components/StateMessage";
import { formatClock } from "./lib/format";
import { useAsync } from "./lib/useAsync";
import CheckinPage from "./routes/checkin/CheckinPage";
import CrewPage from "./routes/crew/CrewPage";
import EarthPage from "./routes/earth/EarthPage";
import DashboardPage from "./routes/dashboard/DashboardPage";
import { useAstronaut } from "./state/astronaut";
import { RegistryProvider } from "./state/registry";
import { useRegistry } from "./state/registry-context";
import "./App.css";

/** The status is polled every 60 s (ORBIT frontend rules). */
const POLL_MS = 60_000;

export default function App() {
  const boot = useAsync(async (signal) => {
    const [registry, crew] = await Promise.all([api.signals(signal), api.crew(signal)]);
    return { registry, crew };
  }, []);

  if (!boot.data) {
    return (
      <div className="app">
        <header className="app-header">
          <div className="app-header__inner">
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

function Brand() {
  return (
    <span className="brand">
      <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="5" className="brand__core" />
        <ellipse cx="16" cy="16" rx="13" ry="6" className="brand__orbit" transform="rotate(-25 16 16)" />
      </svg>
      <span className="brand__word">ORBIT</span>
    </span>
  );
}

function Shell() {
  const { crew } = useRegistry();
  const [astronaut, setAstronaut] = useAstronaut();
  const search = `?astronaut=${encodeURIComponent(astronaut)}`;
  const status = useAsync((signal) => api.status(astronaut, signal), [astronaut], {
    pollMs: POLL_MS,
    enabled: Boolean(astronaut),
  });

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <div className="app-header__inner">
          <Brand />
          <nav className="app-nav" aria-label="Screens">
            <NavLink to={{ pathname: "/", search }} end>
              Dashboard
            </NavLink>
            <NavLink to={{ pathname: "/checkin", search }}>Check-in</NavLink>
            <NavLink to={{ pathname: "/crew", search }}>Crew</NavLink>
            <NavLink to={{ pathname: "/earth", search }}>Earth</NavLink>
          </nav>
          <div className="app-header__tools">
            <div className="clock">
              <span className="kicker">Mission time</span>
              <span className="clock__value data">
                {status.data ? `MD ${status.data.mission_day} · ${formatClock(status.data.as_of)}` : "—"}
              </span>
            </div>
            <label className="astronaut-switcher">
              <span className="kicker">Astronaut</span>
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
          <Route path="/" element={<DashboardPage astronautId={astronaut} status={status} />} />
          <Route path="/checkin" element={<CheckinPage astronautId={astronaut} status={status} />} />
          <Route path="/crew" element={<CrewPage freshness={status.data?.as_of ?? ""} />} />
          <Route path="/earth" element={<EarthPage astronautId={astronaut} status={status} />} />
          <Route path="*" element={<Navigate to={{ pathname: "/", search }} replace />} />
        </Routes>
      </main>

      <footer className="app-footer">
        <div className="app-footer__inner">
          <span>Scores and action cards are illustrative for this demo, not medical advice.</span>
          <span className="data">Status refreshes every 60 s · mission time, UTC</span>
        </div>
      </footer>
    </div>
  );
}
