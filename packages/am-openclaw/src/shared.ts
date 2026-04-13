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
  schemaVersion?: number;
  backendKind?: "hosted" | "self_hosted";
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
  schemaVersion: number;
  backendKind: "hosted" | "self_hosted";
  backendUrl: string;
  apiKey: string | null;
  projectId: string | null;
  contextEngineId: string;
  mode: "capture_only" | "augment_context";
};

/**
 * Backend-reported onboarding service status row from `/health/onboarding`.
 *
 * The OpenClaw plugin does not guess whether parts of the stack are required.
 * Instead, it consumes the server's explicit contract so setup and doctor can
 * stay aligned with the backend's current truth.
 */
export interface OnboardingServiceStatus {
  service_id: string;
  label: string;
  required: boolean;
  status: string;
  summary: string;
  component?: string | null;
  depends_on?: string[];
  details?: Record<string, unknown>;
}

/**
 * Roll-up readiness booleans returned by the backend onboarding contract.
 */
export interface OnboardingReadinessStatus {
  setup_ready: boolean;
  capture_only_ready: boolean;
  augment_context_ready: boolean;
  required_healthy: number;
  required_total: number;
  optional_healthy: number;
  optional_total: number;
  blocking_services: string[];
  degraded_optional_services: string[];
}

/**
 * Machine-readable backend contract for OpenClaw onboarding.
 */
export interface BackendOnboardingContract {
  status: string;
  deployment_mode: string;
  supported_deployment_modes: string[];
  auth_strategy: string;
  provider_key_mode: string;
  hosted_base_url?: string | null;
  plugin_package_name: string;
  plugin_id: string;
  install_command: string;
  setup_command: string;
  doctor_command: string;
  required_services: OnboardingServiceStatus[];
  optional_services: OnboardingServiceStatus[];
  readiness: OnboardingReadinessStatus;
  notes: string[];
}

export const PLUGIN_CONFIG_SCHEMA_VERSION = 1;
export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
export const DEFAULT_CONTEXT_ENGINE_ID = "agentic-memory";
export const PLUGIN_ID = "agentic-memory";

/**
 * Human-readable package metadata used by setup flows and documentation.
 *
 * The npm package name is intentionally more specific than the plugin id:
 *
 * - operators install `agentic-memory-openclaw`
 * - once installed, OpenClaw still registers the plugin under the stable
 *   `agentic-memory` memory/context-engine id
 *
 * Keeping those identities separate lets the public npm surface stay explicit
 * about its OpenClaw role without breaking the runtime ids already baked into
 * the host config shape.
 */
export const OPENCLAW_PACKAGE_INFO = {
  packageName: "agentic-memory-openclaw",
  pluginId: PLUGIN_ID,
  contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
  productName: "Agentic Memory OpenClaw Integration",
  schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
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
    schemaVersion: { type: "integer" },
    backendKind: { enum: ["hosted", "self_hosted"] },
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
    backendKind?: "hosted" | "self_hosted";
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
            schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
            backendKind: options.backendKind ?? "self_hosted",
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
 * Best-effort parsing of an OpenClaw session id into workspace/device/agent.
 *
 * The current local test harness and product assumptions use the stable form:
 *
 *   `<workspace_id>:<device_id>:<agent_id>`
 *
 * If the host emits some other opaque session id, the parser returns null and
 * the runtime falls back to the persisted plugin config.
 */
export function parseOpenClawSessionIdentity(
  sessionId?: string,
): OpenClawIdentity | null {
  const normalized = sessionId?.trim();
  if (!normalized) {
    return null;
  }

  const pieces = normalized.split(":");
  if (pieces.length < 3) {
    return null;
  }

  const agentId = pieces.at(-1)?.trim();
  const deviceId = pieces.at(-2)?.trim();
  const workspaceId = pieces.slice(0, -2).join(":").trim();
  if (!workspaceId || !deviceId || !agentId) {
    return null;
  }

  return {
    workspaceId,
    deviceId,
    agentId,
  };
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
  const resolvedAgentId = agentIdFromHost?.trim() || asString(pluginConfig.agentId) || "default-agent";
  const mode: "capture_only" | "augment_context" =
    pluginConfig.mode === "augment_context" ? "augment_context" : "capture_only";
  const backendKind: "hosted" | "self_hosted" =
    pluginConfig.backendKind === "hosted" ? "hosted" : "self_hosted";
  const resolved: ResolvedPluginConfig = {
    schemaVersion:
      typeof pluginConfig.schemaVersion === "number" && Number.isFinite(pluginConfig.schemaVersion)
        ? pluginConfig.schemaVersion
        : PLUGIN_CONFIG_SCHEMA_VERSION,
    backendKind,
    backendUrl: asString(pluginConfig.backendUrl) ?? DEFAULT_BACKEND_URL,
    apiKey: asString(pluginConfig.apiKey) ?? null,
    workspaceId: asString(pluginConfig.workspaceId) ?? createDefaultWorkspaceId(resolvedAgentId),
    deviceId: asString(pluginConfig.deviceId) ?? "default-device",
    agentId: resolvedAgentId,
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
