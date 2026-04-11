import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const originalFetch = global.fetch;

describe("App", () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const payloadByPath: Record<string, unknown> = {
        "/api/bootstrap": {
          shell: { name: "Agentic Memory Desktop Shell", version: "0.1.0", dev_command: "python -m desktop_shell" },
          backend: { url: "http://127.0.0.1:8765", auth_configured: true },
        },
        "/api/product/status": {
          state_path: "C:/Users/demo/.agentic-memory/product-state.json",
          summary: { repo_count: 2, integration_count: 3, active_project_count: 1, event_count: 4 },
          runtime: {
            server: { status: "healthy", version: "0.1.0" },
            components: {
              desktop_shell: { status: "healthy", updated_at: "2026-04-11T20:00:00+00:00", details: {} },
            },
          },
          integrations: [],
          active_projects: [],
          events: [],
        },
        "/api/openclaw/metrics/summary": {
          status: "ok",
          summary: {
            active_agents: 2,
            active_sessions: 2,
            turns_ingested: 18,
            searches_total: 7,
            context_resolves_total: 3,
            error_responses_total: 1,
            health_score: 92,
            cards: [
              { key: "active_agents", label: "Active Agents", value: 2, status: "healthy", description: "demo" },
              { key: "turns_ingested", label: "Turns Ingested", value: 18, status: "healthy", description: "demo" },
              { key: "searches_total", label: "Searches", value: 7, status: "healthy", description: "demo" },
              { key: "health_score", label: "Health Score", value: 92, status: "healthy", unit: "/100", description: "demo" },
            ],
          },
          request_metrics: [],
          error_metrics: [],
        },
        "/api/openclaw/health/detailed": {
          status: "ok",
          components: [
            { component: "server", status: "healthy", details: { version: "0.1.0" }, updated_at: "2026-04-11T20:00:00+00:00" },
          ],
          request_metrics: [
            { method: "POST", path: "/openclaw/memory/search", status_code: 200, count: 7, avg_seconds: 0.18 },
          ],
          error_metrics: [{ code: "internal_server_error", path: "/openclaw/memory/search", status_code: 500, count: 1 }],
          summary: {
            active_agents: 2,
            active_sessions: 2,
            turns_ingested: 18,
            searches_total: 7,
            context_resolves_total: 3,
            error_responses_total: 1,
            health_score: 92,
            cards: [],
          },
        },
        "/api/openclaw/search/recent?limit=12": {
          status: "ok",
          recent_searches: [
            {
              event_type: "openclaw_memory_search",
              timestamp: "2026-04-11T20:00:00+00:00",
              workspace_id: "workspace-a",
              agent_id: "agent-a",
              session_id: "session-a",
              query: "where is auth",
              result_count: 4,
            },
          ],
          summary: { returned: 1, limit: 12 },
        },
        "/api/openclaw/workspaces": {
          status: "ok",
          workspaces: [
            {
              workspace_id: "workspace-a",
              devices: [
                {
                  device_id: "device-1",
                  agents: [
                    {
                      agent_id: "agent-a",
                      session_id: "session-a",
                      status: "connected",
                      project_id: "project-a",
                      mode: "capture_only",
                      context_engine: "agentic-memory",
                      updated_at: "2026-04-11T20:00:00+00:00",
                    },
                  ],
                },
              ],
              active_projects: [{ project_id: "project-a" }],
              automations: [{ automation_kind: "research_ingestion" }],
            },
          ],
          summary: { workspace_count: 1, device_count: 1, agent_count: 1 },
        },
        "/api/openclaw/agents/agent-a/sessions?workspace_id=workspace-a": {
          status: "ok",
          agent_id: "agent-a",
          workspace_id: "workspace-a",
          sessions: [
            {
              workspace_id: "workspace-a",
              device_id: "device-1",
              agent_id: "agent-a",
              session_id: "session-a",
              status: "connected",
              project_id: "project-a",
              mode: "capture_only",
              context_engine: "agentic-memory",
              integration_updated_at: "2026-04-11T20:00:00+00:00",
              last_activity_at: "2026-04-11T20:00:00+00:00",
              event_count: 3,
            },
          ],
        },
      };

      const payload = payloadByPath[path];
      if (!payload) {
        return new Response(JSON.stringify({ message: `unexpected path ${path}` }), { status: 404 });
      }

      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("renders dashboard data from the desktop shell APIs", async () => {
    render(<App />);

    await waitFor(() => expect(screen.getByText("Active Agents")).toBeInTheDocument());

    expect(screen.getByText("Agentic Memory")).toBeInTheDocument();
    expect(screen.getByText("Control Plane")).toBeInTheDocument();
    expect(screen.getByText("OpenClaw Fleet")).toBeInTheDocument();
    expect(screen.getAllByText("Health Score")).toHaveLength(2);
    expect(screen.getByText("where is auth")).toBeInTheDocument();
    expect(screen.getByText(/workspace-a/i)).toBeInTheDocument();
  });
});
