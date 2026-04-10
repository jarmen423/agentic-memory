/**
 * Shared constants, types, and config helpers for the Agentic Memory OpenClaw
 * plugin.
 *
 * This module intentionally contains no network calls and no OpenClaw command
 * registration. Its job is to centralize the domain model so the runtime,
 * setup wizard, and registration entrypoint all speak the same config shape.
 */

import os from "node:os";

/**
 * Identity values that tie one OpenClaw workspace to one device and one agent.
 */
export interface OpenClawIdentity {
  workspaceId: string;
  deviceId: string;
  agentId: string;
}

/**
 * Plugin config fields stored under `plugins.entries.agentic-memory.config`.
 *
 * This mirrors the OpenClaw-native config shape rather than the earlier custom
 * setup artifact so the CLI-generated config can be used directly by OpenClaw.
 */
export interface AgenticMemoryPluginConfig extends Partial<OpenClawIdentity> {
  backendUrl?: string;
  apiKey?: string | null;
  projectId?: string | null;
  contextEngineId?: string | null;
  mode?: "capture_only" | "augment_context";
}

export type PluginLogger = {
  debug?: (...args: unknown[]) => void;
  info?: (...args: unknown[]) => void;
  warn?: (...args: unknown[]) => void;
  error?: (...args: unknown[]) => void;
};

export type SearchResultRecord = {
  path: string;
  text: string;
};

export type SearchManagerStatus = {
  backend: "builtin" | "qmd";
  provider: string;
  custom?: Record<string, unknown>;
};

export type OpenClawConfig = Record<string, unknown>;

export type ResolvedPluginConfig = Required<OpenClawIdentity> & {
  backendUrl: string;
  apiKey: string | null;
  projectId: string | null;
  contextEngineId: string;
  mode: "capture_only" | "augment_context";
};

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
export const DEFAULT_CONTEXT_ENGINE_ID = "agentic-memory";
export const PLUGIN_ID = "agentic-memory";

/**
 * Human-readable package metadata used by setup flows and documentation.
 */
export const OPENCLAW_PACKAGE_INFO = {
  packageName: "agentic-memory",
  pluginId: PLUGIN_ID,
  contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
  productName: "Agentic Memory OpenClaw Integration",
  defaultMode: "capture_only",
  supportedModes: ["capture_only", "augment_context"] as const,
} as const;

export const CONTEXT_ENGINE_INFO = {
  id: DEFAULT_CONTEXT_ENGINE_ID,
  name: "Agentic Memory",
  version: "0.1.0",
  ownsCompaction: false,
} as const;

export const PLUGIN_CONFIG_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    backendUrl: { type: "string" },
    apiKey: { type: "string" },
    workspaceId: { type: "string" },
    deviceId: { type: "string" },
    agentId: { type: "string" },
    projectId: { type: "string" },
    contextEngineId: { type: "string" },
    mode: { enum: ["capture_only", "augment_context"] },
  },
} as const;

/**
 * Normalize an identity object by trimming empty whitespace and rejecting
 * missing values early.
 */
export function normalizeOpenClawIdentity(identity: OpenClawIdentity): OpenClawIdentity {
  const workspaceId = identity.workspaceId.trim();
  const deviceId = identity.deviceId.trim();
  const agentId = identity.agentId.trim();

  if (!workspaceId || !deviceId || !agentId) {
    throw new Error("OpenClaw identity requires workspaceId, deviceId, and agentId.");
  }

  return { workspaceId, deviceId, agentId };
}

/**
 * Build the canonical plugin config payload shared by both setup paths:
 *
 * - the product-side Python helper `agentic-memory openclaw-setup`
 * - the OpenClaw-native helper `openclaw agentic-memory setup`
 */
export function buildOpenClawBootstrapConfig(
  options: OpenClawIdentity & {
    backendUrl: string;
    backendApiKey?: string | null;
    apiKeyTemplateVar?: string | null;
    projectId?: string | null;
    mode?: "capture_only" | "augment_context";
  },
) {
  const identity = normalizeOpenClawIdentity(options);

  return {
    plugins: {
      slots: {
        memory: PLUGIN_ID,
        // Agentic Memory always occupies the ContextEngine slot because current
        // OpenClaw lifecycle hooks arrive through that surface. In
        // `capture_only` mode the engine captures turns but intentionally does
        // not assemble custom context.
        contextEngine: DEFAULT_CONTEXT_ENGINE_ID,
      },
      entries: {
        [PLUGIN_ID]: {
          enabled: true,
          config: {
            backendUrl: options.backendUrl.trim(),
            apiKey:
              options.backendApiKey?.trim() ||
              `\${${options.apiKeyTemplateVar?.trim() || "AGENTIC_MEMORY_API_KEY"}}`,
            workspaceId: identity.workspaceId,
            deviceId: identity.deviceId,
            agentId: identity.agentId,
            projectId: options.projectId?.trim() || undefined,
            contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
            mode: options.mode ?? "capture_only",
          },
        },
      },
    },
  } as const;
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export function createDefaultDeviceId(): string {
  return os.hostname().trim() || "default-device";
}

export function createDefaultAgentId(): string {
  const username = os.userInfo().username.trim().replace(/\s+/g, "-").toLowerCase();
  return username ? `claw-${username}` : "claw-main";
}

/**
 * Derive a stable default workspace from the resolved agent identity.
 *
 * Product intent:
 *
 * - users should not have to think about workspace during normal setup
 * - one agent should naturally land in one home-base workspace unless the
 *   operator explicitly overrides it
 *
 * This does not guarantee that OpenClaw has exposed a richer host-side
 * workspace concept. It simply gives Agentic Memory a predictable home base
 * that follows the agent identity by default.
 */
export function createDefaultWorkspaceId(agentId?: string): string {
  const normalizedAgentId = agentId?.trim();
  if (!normalizedAgentId) {
    return "default-workspace";
  }

  return normalizedAgentId;
}

/**
 * Resolve plugin configuration from the OpenClaw plugin config payload.
 *
 * The plugin prefers explicit plugin config because both the Python helper and
 * the OpenClaw-native setup command write the same `plugins.entries` shape.
 * Secrets should already be resolved by the host configuration layer before
 * the plugin receives them.
 */
export function resolveAgenticMemoryPluginConfig(
  pluginConfig: Record<string, unknown>,
  agentIdFromHost?: string,
): ResolvedPluginConfig {
  const mode: "capture_only" | "augment_context" =
    pluginConfig.mode === "augment_context" ? "augment_context" : "capture_only";
  const resolved = {
    backendUrl: asString(pluginConfig.backendUrl) ?? DEFAULT_BACKEND_URL,
    apiKey: asString(pluginConfig.apiKey) ?? null,
    workspaceId: asString(pluginConfig.workspaceId) ?? "default-workspace",
    deviceId: asString(pluginConfig.deviceId) ?? "default-device",
    agentId: asString(pluginConfig.agentId) ?? agentIdFromHost ?? "default-agent",
    projectId: asString(pluginConfig.projectId) ?? null,
    contextEngineId: asString(pluginConfig.contextEngineId) ?? DEFAULT_CONTEXT_ENGINE_ID,
    mode,
  };

  normalizeOpenClawIdentity({
    workspaceId: resolved.workspaceId,
    deviceId: resolved.deviceId,
    agentId: resolved.agentId,
  });

  return resolved;
}

export function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function normalizeMessageText(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && "text" in item) {
          return String((item as Record<string, unknown>).text ?? "");
        }
        return safeJsonStringify(item);
      })
      .filter(Boolean)
      .join("\n");
  }
  if (content && typeof content === "object" && "text" in (content as Record<string, unknown>)) {
    return String((content as Record<string, unknown>).text ?? "");
  }
  return safeJsonStringify(content);
}

export function estimateTokenCount(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

export function buildSessionId(sessionId: string, suffix: string): string {
  return `${sessionId}:${suffix}`;
}
