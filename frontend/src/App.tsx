import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { LoadError, Loading } from "./components/StateMessage";
import { useAsync } from "./lib/useAsync";
import DashboardPage from "./routes/dashboard/DashboardPage";
import { useAstronaut } from "./state/astronaut";
import { RegistryProvider } from "./state/registry";
import { useRegistry } from "./state/registry-context";
import "./App.css";

export default function App() {
  const boot = useAsync(async (signal) => {
    const [registry, crew] = await Promise.all([api.signals(signal), api.crew(signal)]);
    return { registry, crew };
  }, []);

  if (!boot.data) {
    return (
      <div className="app">
        <header className="app-header">
          <Brand />
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
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="5" className="brand__core" />
        <ellipse cx="16" cy="16" rx="13" ry="6" className="brand__orbit" transform="rotate(-25 16 16)" />
      </svg>
      ORBIT
    </span>
  );
}

function Shell() {
  const { crew } = useRegistry();
  const [astronaut, setAstronaut] = useAstronaut();
  const search = `?astronaut=${encodeURIComponent(astronaut)}`;

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <Brand />
        <nav className="app-nav" aria-label="Screens">
          <NavLink to={{ pathname: "/", search }} end>
            Dashboard
          </NavLink>
          <NavLink to={{ pathname: "/checkin", search }}>Check-in</NavLink>
          <NavLink to={{ pathname: "/crew", search }}>Crew</NavLink>
        </nav>
        <label className="astronaut-switcher">
          <span className="visually-hidden">Astronaut</span>
          <select className="select" value={astronaut} onChange={(e) => setAstronaut(e.target.value)}>
            {crew.map((m) => (
              <option key={m.astronaut_id} value={m.astronaut_id}>
                {m.callsign} · {m.astronaut_id}
              </option>
            ))}
          </select>
        </label>
      </header>

      <main id="main" className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage astronautId={astronaut} />} />
          <Route path="/checkin" element={<Planned title="Daily check-in" module="M11" />} />
          <Route path="/crew" element={<Planned title="Crew view" module="M14" />} />
          <Route path="*" element={<Navigate to={{ pathname: "/", search }} replace />} />
        </Routes>
      </main>

      <footer className="app-footer secondary">
        Scores and action cards are illustrative for this demo, not medical advice.
      </footer>
    </div>
  );
}

function Planned({ title, module }: { title: string; module: string }) {
  return (
    <section className="card planned">
      <h2>{title}</h2>
      <p className="secondary">This screen is being built ({module}).</p>
    </section>
  );
}
