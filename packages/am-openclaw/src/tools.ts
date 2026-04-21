/**
 * OpenClaw agent-tool bridge for Agentic Memory.
 *
 * The Agentic Memory product already exposes a larger public MCP tool surface,
 * but the OpenClaw plugin historically only registered a memory runtime and a
 * context engine. This module closes that gap by registering first-class
 * OpenClaw tools that proxy into backend routes backed by the same memory and
 * graph services.
 */

import { AgenticMemoryBackendClient } from "./backend-client.js";
import {
  asRecord,
  buildSessionId,
  PLUGIN_ID,
  resolveAgenticMemoryPluginConfig,
  safeJsonStringify,
  type PluginLogger,
  type ResolvedPluginConfig,
} from "./shared.js";
import type {
  OpenClawAgentTool,
  OpenClawPluginToolContext,
} from "openclaw/plugin-sdk/core";

type ToolResult = {
  content: Array<{
    type: "text";
    text: string;
  }>;
  structuredContent?: unknown;
};

function readRequiredString(
  params: Record<string, unknown>,
  key: string,
  label: string,
): string {
  const value = params[key];
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} is required.`);
  }
  return value.trim();
}

function readOptionalString(params: Record<string, unknown>, key: string): string | undefined {
  const value = params[key];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function readOptionalNumber(params: Record<string, unknown>, key: string): number | undefined {
  const value = params[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readOptionalBoolean(params: Record<string, unknown>, key: string): boolean | undefined {
  const value = params[key];
  return typeof value === "boolean" ? value : undefined;
}

/**
 * Resolve the effective plugin config for a tool invocation.
 *
 * The OpenClaw runtime may provide per-session agent identity in the trusted
 * tool context. The bridge prefers those values over the static plugin config
 * so tool calls stay aligned with the live session that invoked them.
 */
function resolveToolConfig(
  ctx: OpenClawPluginToolContext,
  pluginConfig: Record<string, unknown>,
): ResolvedPluginConfig {
  return resolveAgenticMemoryPluginConfig(
    {
      ...pluginConfig,
      ...(ctx.agentId ? { agentId: ctx.agentId } : {}),
    },
    ctx.agentId,
  );
}

function buildToolIdentity(
  cfg: ResolvedPluginConfig,
  ctx: OpenClawPluginToolContext,
  projectId?: string | null,
): {
  workspace_id: string;
  device_id: string;
  agent_id: string;
  session_id: string;
  project_id: string | null;
  metadata: Record<string, unknown>;
} {
  const sessionId =
    (typeof ctx.sessionId === "string" && ctx.sessionId.trim()) ||
    (typeof ctx.sessionKey === "string" && ctx.sessionKey.trim()) ||
    buildSessionId(cfg.agentId, "tools");

  return {
    workspace_id: cfg.workspaceId,
    device_id: cfg.deviceId,
    agent_id: cfg.agentId,
    session_id: sessionId,
    project_id: projectId ?? cfg.projectId,
    metadata: {
      plugin: PLUGIN_ID,
      session_key: ctx.sessionKey ?? null,
      workspace_dir: ctx.workspaceDir ?? null,
      agent_dir: ctx.agentDir ?? null,
    },
  };
}

function textToolResult(text: string, structuredContent?: unknown): ToolResult {
  return {
    content: [{ type: "text", text }],
    ...(structuredContent !== undefined ? { structuredContent } : {}),
  };
}

function withDefinedProperties<T extends Record<string, unknown>>(payload: T): T {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  ) as T;
}

function formatSearchResults(
  title: string,
  query: string,
  results: Array<Record<string, unknown>>,
): string {
  if (results.length === 0) {
    return `## ${title}\n\nQuery: \`${query}\`\n\nNo results found.`;
  }

  const lines = [`## ${title}`, "", `Query: \`${query}\``, ""];
  for (const [index, hit] of results.entries()) {
    const path = typeof hit.path === "string" && hit.path ? hit.path : "unknown";
    const titleText =
      (typeof hit.title === "string" && hit.title) ||
      (typeof hit.name === "string" && hit.name) ||
      path;
    const score = typeof hit.score === "number" ? hit.score.toFixed(3) : "n/a";
    const repoId = typeof hit.repo_id === "string" && hit.repo_id ? hit.repo_id : undefined;
    const projectId =
      typeof hit.project_id === "string" && hit.project_id ? hit.project_id : undefined;
    const snippet =
      (typeof hit.snippet === "string" && hit.snippet) ||
      (typeof hit.text === "string" && hit.text) ||
      (typeof hit.content === "string" && hit.content) ||
      "";
    lines.push(`${index + 1}. ${titleText}`);
    if (repoId) {
      lines.push(`Repo ID: \`${repoId}\``);
    }
    if (projectId) {
      lines.push(`Project ID: \`${projectId}\``);
    }
    lines.push(`Path: \`${path}\``);
    lines.push(`Score: ${score}`);
    if (snippet) {
      lines.push(`Snippet: ${snippet}`);
    }
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}

/**
 * Build the Agentic Memory OpenClaw tools for one trusted runtime context.
 */
export function createAgenticMemoryTools(
  ctx: OpenClawPluginToolContext,
  pluginConfig: Record<string, unknown>,
  logger?: PluginLogger,
): OpenClawAgentTool[] {
  const resolved = resolveToolConfig(ctx, pluginConfig);
  const client = new AgenticMemoryBackendClient(resolved, logger);

  return [
    {
      name: "list_project_and_repo_ids",
      description:
        "List the currently known project_id and repo_id values so scoped searches can use exact identities.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {},
      },
      async execute() {
        const response = await client.listProjectAndRepoIdsTool(
          buildToolIdentity(resolved, ctx),
        );
        return textToolResult(response.text, response.payload);
      },
    },
    {
      name: "search_codebase",
      description:
        "Search the Agentic Memory code graph for functions, files, and implementation details.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string" },
          limit: { type: "number" },
          domain: { type: "string", enum: ["code", "git", "hybrid"] },
          repo_id: { type: "string" },
        },
      },
      async execute(_id, rawParams) {
        const params = asRecord(rawParams);
        const response = await client.searchCodebaseTool({
          ...buildToolIdentity(resolved, ctx),
          query: readRequiredString(params, "query", "query"),
          ...withDefinedProperties({
            limit: readOptionalNumber(params, "limit"),
            domain: readOptionalString(params, "domain"),
            repo_id: readOptionalString(params, "repo_id"),
          }),
        } as never);
        return textToolResult(response.text, response.payload);
      },
    },
    {
      name: "get_file_dependencies",
      description:
        "Show which files one code file imports and which files import it.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["file_path"],
        properties: {
          file_path: { type: "string" },
          repo_id: { type: "string" },
        },
      },
      async execute(_id, rawParams) {
        const params = asRecord(rawParams);
        const response = await client.getFileDependenciesTool({
          ...buildToolIdentity(resolved, ctx),
          file_path: readRequiredString(params, "file_path", "file_path"),
          ...withDefinedProperties({
            repo_id: readOptionalString(params, "repo_id"),
          }),
        } as never);
        return textToolResult(response.text, response.payload);
      },
    },
    {
      name: "trace_execution_path",
      description:
        "Trace the likely execution path starting from one symbol or function.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["start_symbol"],
        properties: {
          start_symbol: { type: "string" },
          max_depth: { type: "number" },
          force_refresh: { type: "boolean" },
          repo_id: { type: "string" },
        },
      },
      async execute(_id, rawParams) {
        const params = asRecord(rawParams);
        const response = await client.traceExecutionPathTool({
          ...buildToolIdentity(resolved, ctx),
          start_symbol: readRequiredString(params, "start_symbol", "start_symbol"),
          ...withDefinedProperties({
            max_depth: readOptionalNumber(params, "max_depth"),
            force_refresh: readOptionalBoolean(params, "force_refresh"),
            repo_id: readOptionalString(params, "repo_id"),
          }),
        } as never);
        return textToolResult(response.text, response.payload);
      },
    },
    {
      name: "search_all_memory",
      description:
        "Search Agentic Memory across code, web research, and conversations.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string" },
          limit: { type: "number" },
          repo_id: { type: "string" },
          as_of: { type: "string" },
          modules: {
            type: "array",
            items: { type: "string" },
          },
          project_id: { type: "string" },
        },
      },
      async execute(_id, rawParams) {
        const params = asRecord(rawParams);
        const query = readRequiredString(params, "query", "query");
        const modules = Array.isArray(params.modules)
          ? params.modules.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
          : undefined;
        const response = await client.searchAllMemory({
          ...buildToolIdentity(resolved, ctx, readOptionalString(params, "project_id") ?? resolved.projectId),
          query,
          ...withDefinedProperties({
            limit: readOptionalNumber(params, "limit"),
            repo_id: readOptionalString(params, "repo_id"),
            as_of: readOptionalString(params, "as_of"),
            modules,
          }),
        } as never);
        const results = Array.isArray(response.results) ? response.results : [];
        return textToolResult(
          formatSearchResults("Agentic Memory Search", query, results),
          response.response ?? response.results ?? null,
        );
      },
    },
    {
      name: "search_conversations",
      description:
        "Search prior conversation turns stored in Agentic Memory for this workspace and project.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string" },
          limit: { type: "number" },
          role: { type: "string" },
          as_of: { type: "string" },
          project_id: { type: "string" },
        },
      },
      async execute(_id, rawParams) {
        const params = asRecord(rawParams);
        const response = await client.searchConversationsTool({
          ...buildToolIdentity(resolved, ctx, readOptionalString(params, "project_id") ?? resolved.projectId),
          query: readRequiredString(params, "query", "query"),
          ...withDefinedProperties({
            limit: readOptionalNumber(params, "limit"),
            role: readOptionalString(params, "role"),
            as_of: readOptionalString(params, "as_of"),
          }),
        } as never);
        return textToolResult(response.text, response.payload);
      },
    },
    {
      name: "get_conversation_context",
      description:
        "Retrieve a compact conversation-context bundle for grounding a response in prior exchanges.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string" },
          limit: { type: "number" },
          include_session_context: { type: "boolean" },
          as_of: { type: "string" },
          project_id: { type: "string" },
        },
      },
      async execute(_id, rawParams) {
        const params = asRecord(rawParams);
        const response = await client.getConversationContextTool({
          ...buildToolIdentity(resolved, ctx, readOptionalString(params, "project_id") ?? resolved.projectId),
          query: readRequiredString(params, "query", "query"),
          ...withDefinedProperties({
            limit: readOptionalNumber(params, "limit"),
            include_session_context: readOptionalBoolean(params, "include_session_context"),
            as_of: readOptionalString(params, "as_of"),
          }),
        } as never);
        return textToolResult(response.text, response.payload);
      },
    },
  ];
}

/**
 * Convert an unknown failure into the plain-text tool result OpenClaw expects.
 */
export function toolErrorResult(error: unknown): ToolResult {
  const message = error instanceof Error ? error.message : safeJsonStringify(error);
  return textToolResult(`Agentic Memory tool request failed: ${message}`);
}
