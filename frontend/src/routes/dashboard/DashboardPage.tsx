/**
 * M12 astronaut dashboard: "Am I OK? Why? What do I do?" at a glance,
 * with trends and history for anyone who wants the detail.
 *
 * Data: the status (DayResult) comes from the app shell, which polls
 * GET /status every 60 s; Trends and History fetch /observations,
 * /baselines, /events and /assessments and refresh with each new result.
 */
import { useSearchParams } from "react-router-dom";
import type { DayResult } from "../../api/types";
import { SegmentedTabs } from "../../components/SegmentedTabs";
import type { AsyncState } from "../../lib/useAsync";
import { useRegistry } from "../../state/registry-context";
import History from "./History";
import Today from "./Today";
import Trends from "./Trends";
import "./Dashboard.css";

const TABS = [
  { id: "today", label: "Today" },
  { id: "trends", label: "Trends" },
  { id: "history", label: "History" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export default function DashboardPage({ astronautId, status }: { astronautId: string; status: AsyncState<DayResult> }) {
  const { member } = useRegistry();
  const astronaut = member(astronautId);
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.some((t) => t.id === params.get("tab")) ? (params.get("tab") as Tab) : "today";

  const setTab = (next: Tab) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("tab", next);
        return p;
      },
      { replace: true },
    );

  // Trends and History refetch when a new assessment arrives.
  const freshness = status.data?.as_of ?? "";
  const callsign = astronaut?.callsign ?? astronautId;

  return (
    <div className="dashboard">
      <header className="page-head">
        <div className="identity">
          <span className="avatar" aria-hidden="true">
            {callsign.charAt(0)}
          </span>
          <div className="identity__text">
            <h1 className="large-title">{callsign}</h1>
            <p className="identity__meta secondary">
              {[astronaut?.role, astronautId, status.data ? `Mission day ${status.data.mission_day}` : null]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
        </div>
        <SegmentedTabs label="Dashboard views" tabs={TABS} current={tab} onChange={setTab} idPrefix="dash" />
      </header>

      <div role="tabpanel" id={`dash-panel-${tab}`} aria-labelledby={`dash-tab-${tab}`} className="enter" key={tab}>
        {tab === "today" && <Today status={status} astronautId={astronautId} freshness={freshness} />}
        {tab === "trends" && <Trends astronautId={astronautId} status={status.data} freshness={freshness} />}
        {tab === "history" && <History astronautId={astronautId} freshness={freshness} />}
      </div>
    </div>
  );
}
