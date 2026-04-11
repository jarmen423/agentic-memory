import type {
  AgentSessionsPayload,
  BootstrapPayload,
  DashboardSummaryPayload,
  HealthDetailedPayload,
  ProductStatusPayload,
  RecentSearchPayload,
  WorkspacesPayload,
} from "../dashboard-types";

/**
 * Thin dashboard-side API wrapper around the desktop shell proxy routes.
 *
 * The React workspace talks only to `/api/*` routes exposed by `desktop_shell`.
 * That keeps auth and backend URL handling in Python while the dashboard stays
 * a static client bundle.
 */

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Request failed for ${path}: ${response.status} ${detail}`);
  }
  return (await response.json()) as T;
}

export async function fetchBootstrap(): Promise<BootstrapPayload> {
  return fetchJson<BootstrapPayload>("/api/bootstrap");
}

export async function fetchProductStatus(): Promise<ProductStatusPayload> {
  return fetchJson<ProductStatusPayload>("/api/product/status");
}

export async function fetchDashboardSummary(): Promise<DashboardSummaryPayload> {
  return fetchJson<DashboardSummaryPayload>("/api/openclaw/metrics/summary");
}

export async function fetchHealthDetailed(): Promise<HealthDetailedPayload> {
  return fetchJson<HealthDetailedPayload>("/api/openclaw/health/detailed");
}

export async function fetchRecentSearches(limit = 12): Promise<RecentSearchPayload> {
  return fetchJson<RecentSearchPayload>(`/api/openclaw/search/recent?limit=${limit}`);
}

export async function fetchWorkspaces(): Promise<WorkspacesPayload> {
  return fetchJson<WorkspacesPayload>("/api/openclaw/workspaces");
}

export async function fetchAgentSessions(
  agentId: string,
  workspaceId?: string | null,
): Promise<AgentSessionsPayload> {
  const suffix = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return fetchJson<AgentSessionsPayload>(
    `/api/openclaw/agents/${encodeURIComponent(agentId)}/sessions${suffix}`,
  );
}
