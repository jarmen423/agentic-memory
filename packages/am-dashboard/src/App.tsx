import { startTransition, useEffect, useState } from "react";
import type {
  AgentSession,
  BootstrapPayload,
  DashboardSummaryPayload,
  HealthDetailedPayload,
  ProductStatusPayload,
  RecentSearchPayload,
  WorkspacesPayload,
  Workspace,
} from "./dashboard-types";
import {
  fetchAgentSessions,
  fetchBootstrap,
  fetchDashboardSummary,
  fetchHealthDetailed,
  fetchProductStatus,
  fetchRecentSearches,
  fetchWorkspaces,
} from "./lib/api";

type NavView = "overview" | "agents" | "memory" | "search" | "workspace" | "settings";

type DashboardData = {
  bootstrap: BootstrapPayload;
  productStatus: ProductStatusPayload;
  summary: DashboardSummaryPayload;
  health: HealthDetailedPayload;
  recentSearches: RecentSearchPayload;
  workspaces: WorkspacesPayload;
};

const NAV_ITEMS: Array<{ id: NavView; label: string; eyebrow: string }> = [
  { id: "overview", label: "Overview", eyebrow: "Home" },
  { id: "agents", label: "OpenClaw Fleet", eyebrow: "Agents" },
  { id: "memory", label: "Memory Health", eyebrow: "Health" },
  { id: "search", label: "Search Quality", eyebrow: "Search" },
  { id: "workspace", label: "Workspace", eyebrow: "Topology" },
  { id: "settings", label: "Settings", eyebrow: "Shell" },
];

/**
 * Fetch the dashboard shell state in one place.
 *
 * Keeping these requests together makes the shell easier to reason about when
 * future agents inspect the repo: the dashboard is just a stitched view over
 * existing Python proxy routes, not a second backend.
 */
async function loadDashboardData(): Promise<DashboardData> {
  const [bootstrap, productStatus, summary, health, recentSearches, workspaces] =
    await Promise.all([
      fetchBootstrap(),
      fetchProductStatus(),
      fetchDashboardSummary(),
      fetchHealthDetailed(),
      fetchRecentSearches(),
      fetchWorkspaces(),
    ]);

  return {
    bootstrap,
    productStatus,
    summary,
    health,
    recentSearches,
    workspaces,
  };
}

function flattenAgents(workspaces: Workspace[]): Array<{
  workspaceId: string;
  deviceId: string;
  agentId: string;
  status: string;
  projectId?: string | null;
}> {
  return workspaces.flatMap((workspace) =>
    workspace.devices.flatMap((device) =>
      device.agents.map((agent) => ({
        workspaceId: workspace.workspace_id,
        deviceId: device.device_id,
        agentId: agent.agent_id,
        status: agent.status,
        projectId: agent.project_id,
      })),
    ),
  );
}

export default function App() {
  const [view, setView] = useState<NavView>("overview");
  const [data, setData] = useState<DashboardData | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [selectedAgentSessions, setSelectedAgentSessions] = useState<AgentSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      try {
        const next = await loadDashboardData();
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setData(next);
          const firstAgent = flattenAgents(next.workspaces.workspaces)[0];
          setSelectedAgentId((current) => current ?? firstAgent?.agentId ?? null);
          setSelectedWorkspaceId((current) => current ?? firstAgent?.workspaceId ?? null);
          setError(null);
        });
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : String(loadError));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    hydrate();
    const interval = window.setInterval(() => {
      setIsRefreshing(true);
      hydrate();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!selectedAgentId) {
      setSelectedAgentSessions([]);
      return;
    }
    const agentId = selectedAgentId;

    async function hydrateAgentSessions() {
      try {
        const response = await fetchAgentSessions(agentId, selectedWorkspaceId);
        if (!cancelled) {
          setSelectedAgentSessions(response.sessions);
        }
      } catch {
        if (!cancelled) {
          setSelectedAgentSessions([]);
        }
      }
    }

    hydrateAgentSessions();
    return () => {
      cancelled = true;
    };
  }, [selectedAgentId, selectedWorkspaceId]);

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      const next = await loadDashboardData();
      startTransition(() => {
        setData(next);
        setError(null);
      });
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
    } finally {
      setIsRefreshing(false);
    }
  }

  if (isLoading) {
    return <div className="screen-state">Loading OpenClaw control plane…</div>;
  }

  if (!data) {
    return <div className="screen-state error-state">Dashboard failed: {error ?? "unknown error"}</div>;
  }

  const agents = flattenAgents(data.workspaces.workspaces);

  return (
    <div className="dashboard-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <aside className="dashboard-sidebar">
        <div className="brand-block">
          <p className="eyebrow">Agentic Memory</p>
          <h1>Control Plane</h1>
          <p className="lede">
            Operator-grade visibility for OpenClaw memory capture, search quality, and
            workspace state.
          </p>
        </div>

        <section className="sidebar-panel">
          <span className="panel-label">Backend</span>
          <dl className="definition-list">
            <div>
              <dt>URL</dt>
              <dd>{data.bootstrap.backend.url}</dd>
            </div>
            <div>
              <dt>Auth</dt>
              <dd>{data.bootstrap.backend.auth_configured ? "Configured" : "Missing"}</dd>
            </div>
            <div>
              <dt>State</dt>
              <dd>{data.productStatus.state_path}</dd>
            </div>
          </dl>
        </section>

        <nav className="nav-stack" aria-label="Dashboard views">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-button ${view === item.id ? "is-active" : ""}`}
              onClick={() => setView(item.id)}
              type="button"
            >
              <span className="nav-eyebrow">{item.eyebrow}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="dashboard-main">
        <header className="hero-panel">
          <div>
            <p className="eyebrow">Phase 13</p>
            <h2>OpenClaw Testing + Dashboard</h2>
            <p className="hero-copy">
              The shell now renders backend-backed views over OpenClaw sessions, dashboard
              metrics, and workspace topology from the Python proxy layer.
            </p>
          </div>

          <div className="hero-metrics">
            <div className="hero-badge">
              <span className="hero-badge-label">Health Score</span>
              <strong>{data.summary.summary.health_score}</strong>
            </div>
            <button className="refresh-button" type="button" onClick={handleRefresh}>
              {isRefreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </header>

        {error ? <p className="error-banner">{error}</p> : null}

        {view === "overview" ? (
          <section className="view-grid">
            <section className="card-grid">
              {data.summary.summary.cards.map((card) => (
                <article key={card.key} className={`metric-card status-${card.status}`}>
                  <span className="panel-label">{card.label}</span>
                  <strong className="metric-value">
                    {card.value}
                    {card.unit ?? ""}
                  </strong>
                  <p>{card.description}</p>
                </article>
              ))}
            </section>

            <section className="two-column-grid">
              <article className="dashboard-panel">
                <span className="panel-label">Runtime Summary</span>
                <ul className="fact-list">
                  <li>Repos tracked: {data.productStatus.summary.repo_count}</li>
                  <li>Integrations: {data.productStatus.summary.integration_count ?? 0}</li>
                  <li>Active projects: {data.productStatus.summary.active_project_count ?? 0}</li>
                  <li>Event log size: {data.productStatus.summary.event_count ?? 0}</li>
                </ul>
              </article>

              <article className="dashboard-panel">
                <span className="panel-label">Recent Search Activity</span>
                <div className="search-feed">
                  {data.recentSearches.recent_searches.length === 0 ? (
                    <p className="muted-copy">No search activity recorded yet.</p>
                  ) : (
                    data.recentSearches.recent_searches.map((item) => (
                      <div key={`${item.event_type}:${item.timestamp}:${item.session_id}`} className="search-feed-item">
                        <strong>{item.query ?? "Search query missing"}</strong>
                        <span>
                          {item.event_type} • {item.workspace_id ?? "unknown workspace"} • {item.result_count ?? 0} hits
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </article>
            </section>
          </section>
        ) : null}

        {view === "agents" ? (
          <section className="two-column-grid">
            <article className="dashboard-panel">
              <span className="panel-label">OpenClaw Fleet</span>
              <div className="fleet-list">
                {agents.map((agent) => (
                  <button
                    key={`${agent.workspaceId}:${agent.deviceId}:${agent.agentId}`}
                    type="button"
                    className={`fleet-item ${selectedAgentId === agent.agentId ? "is-selected" : ""}`}
                    onClick={() => {
                      setSelectedAgentId(agent.agentId);
                      setSelectedWorkspaceId(agent.workspaceId);
                    }}
                  >
                    <strong>{agent.agentId}</strong>
                    <span>
                      {agent.workspaceId} • {agent.deviceId} • {agent.status}
                    </span>
                    <span>{agent.projectId ?? "no active project"}</span>
                  </button>
                ))}
              </div>
            </article>

            <article className="dashboard-panel">
              <span className="panel-label">Agent Detail</span>
              {selectedAgentSessions.length === 0 ? (
                <p className="muted-copy">Select an agent to inspect its registered sessions.</p>
              ) : (
                <div className="session-stack">
                  {selectedAgentSessions.map((session) => (
                    <div key={session.session_id} className="session-card">
                      <strong>{session.session_id}</strong>
                      <span>
                        {session.workspace_id} • {session.device_id ?? "unknown device"} • {session.mode ?? "mode unknown"}
                      </span>
                      <span>
                        project {session.project_id ?? "none"} • {session.event_count} events
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          </section>
        ) : null}

        {view === "memory" ? (
          <section className="two-column-grid">
            <article className="dashboard-panel">
              <span className="panel-label">Runtime Components</span>
              <div className="component-grid">
                {data.health.components.map((component) => (
                  <div key={component.component} className={`component-card status-${component.status}`}>
                    <strong>{component.component}</strong>
                    <span>{component.status}</span>
                    <p>{component.updated_at ?? "No timestamp"}</p>
                  </div>
                ))}
              </div>
            </article>

            <article className="dashboard-panel">
              <span className="panel-label">Request Metrics</span>
              <div className="metric-table">
                {data.health.request_metrics.map((metric) => (
                  <div key={`${metric.method}:${metric.path}:${metric.status_code}`} className="metric-row">
                    <strong>{metric.path}</strong>
                    <span>
                      {metric.method} • {metric.status_code} • {metric.count} requests • avg {(metric.avg_seconds ?? 0).toFixed(2)}s
                    </span>
                  </div>
                ))}
              </div>
            </article>
          </section>
        ) : null}

        {view === "search" ? (
          <section className="two-column-grid">
            <article className="dashboard-panel">
              <span className="panel-label">Recent Searches</span>
              <div className="metric-table">
                {data.recentSearches.recent_searches.map((item) => (
                  <div key={`${item.timestamp}:${item.query}`} className="metric-row">
                    <strong>{item.query ?? "Unknown query"}</strong>
                    <span>
                      {item.agent_id ?? "unknown agent"} • {item.result_count ?? 0} hits • {item.event_type}
                    </span>
                  </div>
                ))}
              </div>
            </article>

            <article className="dashboard-panel">
              <span className="panel-label">Error Budget</span>
              <div className="metric-table">
                {data.health.error_metrics.length === 0 ? (
                  <p className="muted-copy">No normalized API errors recorded.</p>
                ) : (
                  data.health.error_metrics.map((metric) => (
                    <div key={`${metric.code}:${metric.path}:${metric.status_code}`} className="metric-row">
                      <strong>{metric.code}</strong>
                      <span>
                        {metric.path} • {metric.status_code} • {metric.count} responses
                      </span>
                    </div>
                  ))
                )}
              </div>
            </article>
          </section>
        ) : null}

        {view === "workspace" ? (
          <section className="workspace-stack">
            {data.workspaces.workspaces.map((workspace) => (
              <article key={workspace.workspace_id} className="dashboard-panel workspace-panel">
                <div className="workspace-header">
                  <div>
                    <span className="panel-label">Workspace</span>
                    <h3>{workspace.workspace_id}</h3>
                  </div>
                  <div className="workspace-summary">
                    <span>{workspace.devices.length} devices</span>
                    <span>{workspace.active_projects.length} active projects</span>
                    <span>{workspace.automations.length} automations</span>
                  </div>
                </div>

                <div className="workspace-device-grid">
                  {workspace.devices.map((device) => (
                    <div key={`${workspace.workspace_id}:${device.device_id}`} className="device-card">
                      <strong>{device.device_id}</strong>
                      {device.agents.map((agent) => (
                        <div key={agent.session_id} className="device-agent-row">
                          <span>{agent.agent_id}</span>
                          <span>{agent.project_id ?? "no project"}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </section>
        ) : null}

        {view === "settings" ? (
          <section className="two-column-grid">
            <article className="dashboard-panel">
              <span className="panel-label">Shell Configuration</span>
              <ul className="fact-list">
                <li>Desktop shell command: {data.bootstrap.shell.dev_command}</li>
                <li>Shell version: {data.bootstrap.shell.version}</li>
                <li>Backend URL: {data.bootstrap.backend.url}</li>
                <li>Auth configured: {data.bootstrap.backend.auth_configured ? "yes" : "no"}</li>
              </ul>
            </article>

            <article className="dashboard-panel">
              <span className="panel-label">Wave Status</span>
              <p className="muted-copy">
                Phase 13 is focused on dashboard replacement, operational verification, and CI
                gates. Packaging, marketplace release, and GTM work remain deferred.
              </p>
            </article>
          </section>
        ) : null}
      </main>
    </div>
  );
}
