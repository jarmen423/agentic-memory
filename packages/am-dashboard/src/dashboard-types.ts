/**
 * Shared dashboard response contracts used by the React shell.
 *
 * These types mirror the backend's machine-readable payloads so the UI stays
 * coupled to real route contracts rather than ad hoc browser-only models.
 */

export type BootstrapPayload = {
  shell: {
    name: string;
    version: string;
    dev_command: string;
  };
  backend: {
    url: string;
    auth_configured: boolean;
  };
};

export type ProductStatusPayload = {
  state_path: string;
  summary: {
    repo_count: number;
    integration_count?: number;
    active_project_count?: number;
    event_count?: number;
  };
  runtime: {
    components?: Record<string, { status: string; updated_at?: string; details?: Record<string, unknown> }>;
    server?: {
      status: string;
      version?: string;
    };
  };
  integrations: Array<Record<string, unknown>>;
  active_projects?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
};

export type DashboardCard = {
  key: string;
  label: string;
  value: number;
  unit?: string | null;
  status: string;
  description?: string | null;
};

export type DashboardSummaryPayload = {
  status: "ok";
  summary: {
    active_agents: number;
    active_sessions: number;
    turns_ingested: number;
    searches_total: number;
    context_resolves_total: number;
    error_responses_total: number;
    health_score: number;
    cards: DashboardCard[];
  };
  request_metrics: RequestMetric[];
  error_metrics: ErrorMetric[];
};

export type HealthDetailedPayload = {
  status: "ok";
  components: HealthComponent[];
  request_metrics: RequestMetric[];
  error_metrics: ErrorMetric[];
  summary: DashboardSummaryPayload["summary"];
};

export type HealthComponent = {
  component: string;
  status: string;
  details: Record<string, unknown>;
  updated_at?: string | null;
};

export type RequestMetric = {
  method: string;
  path: string;
  status_code: number;
  count: number;
  avg_seconds?: number | null;
};

export type ErrorMetric = {
  code: string;
  path: string;
  status_code: number;
  count: number;
};

export type RecentSearchPayload = {
  status: "ok";
  recent_searches: RecentSearch[];
  summary: {
    returned: number;
    limit: number;
  };
};

export type RecentSearch = {
  event_type: string;
  timestamp: string;
  workspace_id?: string | null;
  agent_id?: string | null;
  session_id?: string | null;
  query?: string | null;
  result_count?: number | null;
  project_id?: string | null;
};

export type AgentSessionsPayload = {
  status: "ok";
  agent_id: string;
  workspace_id?: string | null;
  sessions: AgentSession[];
};

export type AgentSession = {
  workspace_id: string;
  device_id?: string | null;
  agent_id: string;
  session_id: string;
  status: string;
  mode?: string | null;
  project_id?: string | null;
  context_engine?: string | null;
  integration_updated_at?: string | null;
  last_activity_at?: string | null;
  event_count: number;
};

export type WorkspacesPayload = {
  status: "ok";
  workspaces: Workspace[];
  summary: {
    workspace_count: number;
    device_count: number;
    agent_count: number;
  };
};

export type Workspace = {
  workspace_id: string;
  devices: WorkspaceDevice[];
  active_projects: Array<Record<string, unknown>>;
  automations: Array<Record<string, unknown>>;
};

export type WorkspaceDevice = {
  device_id: string;
  agents: WorkspaceAgent[];
};

export type WorkspaceAgent = {
  agent_id: string;
  session_id: string;
  status: string;
  project_id?: string | null;
  mode?: string | null;
  context_engine?: string | null;
  updated_at?: string | null;
};
