/**
 * M12 astronaut dashboard: "Am I OK? Why? What do I do?" at a glance,
 * with trends and history for anyone who wants the detail.
 *
 * Data: GET /status (polled every 60 s), plus /observations, /baselines,
 * /events and /assessments for the Trends and History tabs.
 */
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { SegmentedTabs } from "../../components/SegmentedTabs";
import { formatMissionTime } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";
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

const POLL_MS = 60_000;

export default function DashboardPage({ astronautId }: { astronautId: string }) {
  const { member } = useRegistry();
  const astronaut = member(astronautId);
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.some((t) => t.id === params.get("tab")) ? (params.get("tab") as Tab) : "today";

  const status = useAsync((signal) => api.status(astronautId, signal), [astronautId], {
    pollMs: POLL_MS,
    enabled: Boolean(astronautId),
  });

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

  return (
    <div className="dashboard">
      <div className="dashboard__head">
        <div>
          <h1 className="dashboard__name">
            {astronaut?.callsign ?? astronautId}
            <span className="secondary dashboard__role"> {astronaut?.role}</span>
          </h1>
          {status.data && (
            <p className="secondary">
              Mission day <span className="data">{status.data.mission_day}</span> ·{" "}
              <span className="data">{formatMissionTime(status.data.as_of)}</span>
            </p>
          )}
        </div>
        <SegmentedTabs label="Dashboard views" tabs={TABS} current={tab} onChange={setTab} idPrefix="dash" />
      </div>

      <div role="tabpanel" id={`dash-panel-${tab}`} aria-labelledby={`dash-tab-${tab}`}>
        {tab === "today" && <Today status={status} />}
        {tab === "trends" && <Trends astronautId={astronautId} status={status.data} freshness={freshness} />}
        {tab === "history" && <History astronautId={astronautId} freshness={freshness} />}
      </div>
    </div>
  );
}
