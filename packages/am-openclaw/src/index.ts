/**
 * Native OpenClaw plugin runtime for Agentic Memory.
 *
 * This module turns the earlier scaffold into a real OpenClaw-native plugin
 * surface. The plugin owns two responsibilities:
 *
 * 1. Register a memory runtime so OpenClaw can query shared Agentic Memory
 *    state across devices.
 * 2. Register an optional context engine named `agentic-memory` that asks the
 *    backend to assemble context blocks from the same shared memory graph.
 *
 * The package intentionally stays backend-driven. OpenClaw remains the
 * orchestration/runtime host, while Agentic Memory remains the source of truth
 * for shared memory retrieval and context resolution.
 */

import os from "node:os";
import { stdin as input, stdout as output } from "node:process";
import { createInterface } from "node:readline/promises";
import { definePluginEntry } from "openclaw/plugin-sdk/core";
import { updateConfig } from "openclaw/plugin-sdk/config-runtime";
import type {
  AgentMessage,
  AssembleResult,
  BootstrapResult,
  CompactResult,
  ContextEngine,
  IngestBatchResult,
  IngestResult,
} from "openclaw/plugin-sdk";

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
}

type BackendResultHit = {
  module?: string;
  domain?: string;
  title?: string;
  name?: string;
  path?: string;
  score?: number;
  snippet?: string;
  content?: string;
  text?: string;
  start_line?: number;
  end_line?: number;
  source_kind?: string;
};

type BackendContextBlock = {
  title?: string;
  source?: string;
  score?: number;
  content?: string;
  provenance?: Record<string, unknown>;
};

type PluginLogger = {
  debug?: (...args: unknown[]) => void;
  info?: (...args: unknown[]) => void;
  warn?: (...args: unknown[]) => void;
  error?: (...args: unknown[]) => void;
};

type SearchResultRecord = {
  path: string;
  text: string;
};

type SearchManagerStatus = {
  backend: "builtin" | "qmd";
  provider: string;
  custom?: Record<string, unknown>;
};

type SetupCommandOptions = {
  backendUrl?: string;
  apiKey?: string;
  workspaceId?: string;
  deviceId?: string;
  agentId?: string;
  projectId?: string;
  enableContextEngine?: boolean;
  disableContextEngine?: boolean;
  json?: boolean;
};

type OpenClawConfig = Record<string, unknown>;

type ResolvedSetupValues = {
  backendUrl: string;
  apiKey: string;
  workspaceId: string;
  deviceId: string;
  agentId: string;
  projectId: string | null;
  enableContextEngine: boolean;
};

type AgenticMemoryCliContext = {
  program: any;
  config: OpenClawConfig;
  workspaceDir: string | undefined;
  logger: PluginLogger;
};

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
const DEFAULT_CONTEXT_ENGINE_ID = "agentic-memory";
const PLUGIN_ID = "agentic-memory";

const CONTEXT_ENGINE_INFO = {
  id: DEFAULT_CONTEXT_ENGINE_ID,
  name: "Agentic Memory",
  version: "0.1.0",
  ownsCompaction: false,
} as const;

const PLUGIN_CONFIG_SCHEMA = {
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
  },
} as const;

/**
 * Human-readable package metadata used by setup flows and documentation.
 */
export const OPENCLAW_PACKAGE_INFO = {
  packageName: "am-openclaw",
  pluginId: PLUGIN_ID,
  contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
  productName: "Agentic Memory OpenClaw Integration",
  defaultMode: "memory",
  supportedModes: ["memory", "context-engine"] as const,
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
    enableContextEngine?: boolean;
  },
) {
  const identity = normalizeOpenClawIdentity(options);

  return {
    plugins: {
      slots: {
        memory: PLUGIN_ID,
        contextEngine: options.enableContextEngine ? DEFAULT_CONTEXT_ENGINE_ID : "legacy",
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
          },
        },
      },
    },
  } as const;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function isInteractiveTerminal(): boolean {
  return Boolean(input.isTTY && output.isTTY);
}

function createDefaultDeviceId(): string {
  return os.hostname().trim() || "default-device";
}

function createDefaultAgentId(): string {
  const username = os.userInfo().username.trim().replace(/\s+/g, "-").toLowerCase();
  return username ? `claw-${username}` : "claw-main";
}

function resolveExistingPluginConfig(config: OpenClawConfig): AgenticMemoryPluginConfig {
  const plugins = asRecord(config.plugins);
  const entries = asRecord(plugins.entries);
  const pluginEntry = asRecord(entries[PLUGIN_ID]);
  return asRecord(pluginEntry.config) as AgenticMemoryPluginConfig;
}

function resolveExistingContextEngineSelection(config: OpenClawConfig): boolean {
  const plugins = asRecord(config.plugins);
  const slots = asRecord(plugins.slots);
  return asString(slots.contextEngine) === DEFAULT_CONTEXT_ENGINE_ID;
}

/**
 * Apply the plugin's config into the active OpenClaw config object.
 *
 * The setup command deliberately touches only the plugin's own config record
 * plus the `memory` and `contextEngine` slot selections. This keeps the change
 * narrowly scoped and makes repeated re-runs safe.
 */
export function mergeAgenticMemoryPluginConfigIntoOpenClawConfig(
  config: OpenClawConfig,
  values: ResolvedSetupValues,
): OpenClawConfig {
  const nextPlugins = asRecord(config.plugins);
  const nextEntries = asRecord(nextPlugins.entries);
  const nextSlots = asRecord(nextPlugins.slots);
  const nextPluginEntry = asRecord(nextEntries[PLUGIN_ID]);

  nextEntries[PLUGIN_ID] = {
    ...nextPluginEntry,
    enabled: true,
    config: {
      backendUrl: values.backendUrl,
      apiKey: values.apiKey,
      workspaceId: values.workspaceId,
      deviceId: values.deviceId,
      agentId: values.agentId,
      ...(values.projectId ? { projectId: values.projectId } : {}),
      contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
    },
  };

  nextSlots.memory = PLUGIN_ID;
  nextSlots.contextEngine = values.enableContextEngine ? DEFAULT_CONTEXT_ENGINE_ID : "legacy";

  return {
    ...config,
    plugins: {
      ...nextPlugins,
      entries: nextEntries,
      slots: nextSlots,
    },
  };
}

async function promptWithDefault(
  question: string,
  defaultValue: string,
  options?: { allowEmpty?: boolean },
): Promise<string> {
  const rl = createInterface({ input, output });
  try {
    const raw = await rl.question(`${question} [${defaultValue}]: `);
    const trimmed = raw.trim();
    if (!trimmed && options?.allowEmpty) {
      return "";
    }
    return trimmed || defaultValue;
  } finally {
    rl.close();
  }
}

async function promptYesNo(question: string, defaultValue: boolean): Promise<boolean> {
  const rl = createInterface({ input, output });
  const hint = defaultValue ? "Y/n" : "y/N";
  try {
    const raw = await rl.question(`${question} [${hint}]: `);
    const normalized = raw.trim().toLowerCase();
    if (!normalized) {
      return defaultValue;
    }
    return normalized === "y" || normalized === "yes";
  } finally {
    rl.close();
  }
}

function ensureSetupFlagCompatibility(options: SetupCommandOptions): void {
  if (options.enableContextEngine && options.disableContextEngine) {
    throw new Error("Use either --enable-context-engine or --disable-context-engine, not both.");
  }
}

async function resolveSetupValues(
  currentConfig: OpenClawConfig,
  options: SetupCommandOptions,
): Promise<ResolvedSetupValues> {
  ensureSetupFlagCompatibility(options);

  const existing = resolveExistingPluginConfig(currentConfig);
  const interactive = isInteractiveTerminal();
  const contextEngineDefault =
    options.enableContextEngine === true
      ? true
      : options.disableContextEngine === true
        ? false
        : resolveExistingContextEngineSelection(currentConfig);

  const backendUrlDefault = options.backendUrl?.trim() || existing.backendUrl || DEFAULT_BACKEND_URL;
  const apiKeyDefault = options.apiKey?.trim() || existing.apiKey || "${AGENTIC_MEMORY_API_KEY}";
  const workspaceIdDefault = options.workspaceId?.trim() || existing.workspaceId || "default-workspace";
  const deviceIdDefault = options.deviceId?.trim() || existing.deviceId || createDefaultDeviceId();
  const agentIdDefault = options.agentId?.trim() || existing.agentId || createDefaultAgentId();
  const projectIdDefault = options.projectId?.trim() || existing.projectId || "";

  if (!interactive) {
    return {
      backendUrl: backendUrlDefault,
      apiKey: apiKeyDefault,
      workspaceId: workspaceIdDefault,
      deviceId: deviceIdDefault,
      agentId: agentIdDefault,
      projectId: projectIdDefault || null,
      enableContextEngine: contextEngineDefault,
    };
  }

  const backendUrl = await promptWithDefault("Agentic Memory backend URL", backendUrlDefault);
  const apiKey = await promptWithDefault(
    "API key or interpolation template",
    apiKeyDefault,
  );
  const workspaceId = await promptWithDefault("OpenClaw workspace ID", workspaceIdDefault);
  const deviceId = await promptWithDefault("Device ID", deviceIdDefault);
  const agentId = await promptWithDefault("Agent ID", agentIdDefault);
  const projectId = await promptWithDefault("Project ID (optional)", projectIdDefault, {
    allowEmpty: true,
  });
  const enableContextEngine = await promptYesNo(
    "Enable Agentic Memory as the context engine too?",
    contextEngineDefault,
  );

  return {
    backendUrl,
    apiKey,
    workspaceId,
    deviceId,
    agentId,
    projectId: projectId.trim() || null,
    enableContextEngine,
  };
}

function printSetupResult(
  ctx: AgenticMemoryCliContext,
  values: ResolvedSetupValues,
  options: SetupCommandOptions,
): void {
  const payload = {
    ok: true,
    pluginId: PLUGIN_ID,
    backendUrl: values.backendUrl,
    workspaceId: values.workspaceId,
    deviceId: values.deviceId,
    agentId: values.agentId,
    projectId: values.projectId,
    contextEngineEnabled: values.enableContextEngine,
  };

  if (options.json) {
    output.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }

  output.write(`Configured ${PLUGIN_ID} in the active OpenClaw profile.\n`);
  output.write(`Backend: ${values.backendUrl}\n`);
  output.write(`Workspace: ${values.workspaceId}\n`);
  output.write(`Device: ${values.deviceId}\n`);
  output.write(`Agent: ${values.agentId}\n`);
  if (values.projectId) {
    output.write(`Project: ${values.projectId}\n`);
  }
  output.write(`Memory slot: ${PLUGIN_ID}\n`);
  output.write(
    `Context engine: ${values.enableContextEngine ? DEFAULT_CONTEXT_ENGINE_ID : "legacy"}\n`,
  );
  ctx.logger.info?.("Agentic Memory plugin setup complete.");
}

/**
 * Register the plugin-owned CLI command so OpenClaw users can finish setup
 * without bouncing back into the Python CLI.
 *
 * This is the bridge from "plugin installed" to "plugin configured." It keeps
 * the flow OpenClaw-native by writing directly into the active OpenClaw config
 * profile using the host SDK's config writer.
 */
function registerAgenticMemoryCli(ctx: AgenticMemoryCliContext): void {
  const root = ctx.program
    .command(PLUGIN_ID)
    .description("Configure and inspect the Agentic Memory OpenClaw integration");

  root
    .command("setup")
    .description("Run the Agentic Memory setup wizard or apply flags non-interactively")
    .option("--backend-url <url>", "Agentic Memory backend URL")
    .option(
      "--api-key <value>",
      "Backend API key or interpolation template such as ${AGENTIC_MEMORY_API_KEY}",
    )
    .option("--workspace-id <id>", "OpenClaw workspace identifier")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--project-id <id>", "Optional project label")
    .option(
      "--enable-context-engine",
      "Set plugins.slots.contextEngine to agentic-memory",
      false,
    )
    .option("--disable-context-engine", "Restore the legacy context engine", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: SetupCommandOptions) => {
      const values = await resolveSetupValues(ctx.config, options);
      await updateConfig((config) => mergeAgenticMemoryPluginConfigIntoOpenClawConfig(config, values));
      printSetupResult(ctx, values, options);
    });
}

function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function normalizeMessageText(content: unknown): string {
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

function getRole(message: AgentMessage): string {
  const rawRole = typeof message.role === "string" ? message.role.toLowerCase() : "user";
  if (rawRole === "assistant" || rawRole === "system" || rawRole === "tool" || rawRole === "user") {
    return rawRole;
  }
  return "user";
}

function estimateTokenCount(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

function buildSessionId(sessionId: string, suffix: string): string {
  return `${sessionId}:${suffix}`;
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
): Required<OpenClawIdentity> & {
  backendUrl: string;
  apiKey: string | null;
  projectId: string | null;
  contextEngineId: string;
} {
  const resolved = {
    backendUrl: asString(pluginConfig.backendUrl) ?? DEFAULT_BACKEND_URL,
    apiKey: asString(pluginConfig.apiKey) ?? null,
    workspaceId: asString(pluginConfig.workspaceId) ?? "default-workspace",
    deviceId: asString(pluginConfig.deviceId) ?? "default-device",
    agentId: asString(pluginConfig.agentId) ?? agentIdFromHost ?? "default-agent",
    projectId: asString(pluginConfig.projectId) ?? null,
    contextEngineId: asString(pluginConfig.contextEngineId) ?? DEFAULT_CONTEXT_ENGINE_ID,
  };

  return normalizeOpenClawIdentity({
    workspaceId: resolved.workspaceId,
    deviceId: resolved.deviceId,
    agentId: resolved.agentId,
  }) && resolved;
}

class AgenticMemoryBackendClient {
  private readonly logger: PluginLogger | undefined;

  constructor(
    private readonly config: ReturnType<typeof resolveAgenticMemoryPluginConfig>,
    logger?: PluginLogger,
  ) {
    this.logger = logger;
  }

  private buildHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.config.apiKey) {
      headers.Authorization = `Bearer ${this.config.apiKey}`;
    }
    return headers;
  }

  async post<T>(path: string, payload: Record<string, unknown>): Promise<T> {
    const url = new URL(path, this.config.backendUrl).toString();
    const response = await fetch(url, {
      method: "POST",
      headers: this.buildHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const detail = await response.text();
      this.logger?.warn?.("Agentic Memory backend request failed", {
        path,
        status: response.status,
        detail,
      });
      throw new Error(`Agentic Memory backend request failed (${response.status}): ${detail}`);
    }

    return (await response.json()) as T;
  }
}

class AgenticMemorySearchManager {
  private readonly cachedFiles = new Map<string, SearchResultRecord>();

  constructor(
    private readonly client: AgenticMemoryBackendClient,
    private readonly config: ReturnType<typeof resolveAgenticMemoryPluginConfig>,
  ) {}

  private identityPayload(sessionKey?: string): Record<string, unknown> {
    return {
      workspace_id: this.config.workspaceId,
      device_id: this.config.deviceId,
      agent_id: this.config.agentId,
      session_id: sessionKey || buildSessionId(this.config.agentId, "memory"),
      project_id: this.config.projectId,
      metadata: {
        plugin: PLUGIN_ID,
      },
    };
  }

  private cacheHit(hit: BackendResultHit): void {
    const path = hit.path?.trim();
    const text = hit.content ?? hit.snippet ?? hit.text;
    if (!path || !text) {
      return;
    }
    this.cachedFiles.set(path, { path, text });
  }

  async search(
    query: string,
    opts?: { maxResults?: number; minScore?: number; sessionKey?: string },
  ): Promise<
    Array<{
      path: string;
      startLine: number;
      endLine: number;
      score: number;
      snippet: string;
      source: "memory" | "sessions";
      citation?: string;
    }>
  > {
    const response = await this.client.post<{
      results?: BackendResultHit[];
    }>("/openclaw/memory/search", {
      ...this.identityPayload(opts?.sessionKey),
      query,
      limit: opts?.maxResults ?? 10,
    });

    const hits = Array.isArray(response.results) ? response.results : [];
    return hits
      .filter((hit) => (hit.score ?? 0) >= (opts?.minScore ?? 0))
      .map((hit) => {
        this.cacheHit(hit);
        const citation = hit.path ? `${hit.path}#L${hit.start_line ?? 1}` : undefined;
        return {
          path: hit.path ?? `${hit.module ?? "memory"}:${hit.title ?? "result"}`,
          startLine: hit.start_line ?? 1,
          endLine: hit.end_line ?? 1,
          score: hit.score ?? 0,
          snippet: hit.snippet ?? hit.content ?? hit.text ?? "",
          source: hit.module === "conversation" ? "sessions" : "memory",
          ...(citation ? { citation } : {}),
        };
      });
  }

  async readFile(params: {
    relPath: string;
    from?: number;
    lines?: number;
  }): Promise<{ text: string; path: string }> {
    try {
      const response = await this.client.post<{
        path?: string;
        text?: string;
      }>("/openclaw/memory/read", {
        ...this.identityPayload(),
        rel_path: params.relPath,
        from_line: params.from,
        lines: params.lines,
      });

      if (response.path && response.text) {
        return {
          path: response.path,
          text: response.text,
        };
      }
    } catch {
      // The backend currently supports canonical reads for conversation turns
      // first. Unsupported hit types still fall back to the last cached
      // snippet from search results.
    }

    const cached = this.cachedFiles.get(params.relPath);
    if (cached) {
      return {
        path: cached.path,
        text: cached.text,
      };
    }

    return {
      path: params.relPath,
      text: `No canonical Agentic Memory read is available for ${params.relPath}, and no cached snippet exists yet.`,
    };
  }

  status(): SearchManagerStatus {
    return {
      backend: "builtin",
      provider: PLUGIN_ID,
      custom: {
        backendUrl: this.config.backendUrl,
        workspaceId: this.config.workspaceId,
        deviceId: this.config.deviceId,
        agentId: this.config.agentId,
        projectId: this.config.projectId,
        cachedFiles: this.cachedFiles.size,
      },
    };
  }

  async sync(): Promise<void> {
    // The backend already owns ingestion and indexing. There is nothing local
    // for the OpenClaw plugin to synchronize yet.
  }

  async probeEmbeddingAvailability(): Promise<{ ok: boolean; error?: string }> {
    return { ok: true };
  }

  async probeVectorAvailability(): Promise<boolean> {
    return true;
  }
}

class AgenticMemoryContextEngine implements ContextEngine {
  readonly info = CONTEXT_ENGINE_INFO;

  private readonly turnIndexBySession = new Map<string, number>();

  constructor(
    private readonly client: AgenticMemoryBackendClient,
    private readonly config: ReturnType<typeof resolveAgenticMemoryPluginConfig>,
  ) {}

  private identityPayload(sessionId: string): Record<string, unknown> {
    return {
      workspace_id: this.config.workspaceId,
      device_id: this.config.deviceId,
      agent_id: this.config.agentId,
      session_id: sessionId,
      project_id: this.config.projectId,
      metadata: {
        plugin: PLUGIN_ID,
      },
    };
  }

  private nextTurnIndex(sessionId: string): number {
    const next = this.turnIndexBySession.get(sessionId) ?? 0;
    this.turnIndexBySession.set(sessionId, next + 1);
    return next;
  }

  private async ingestOne(sessionId: string, message: AgentMessage): Promise<void> {
    const content = normalizeMessageText(message.content);
    if (!content.trim()) {
      return;
    }

    await this.client.post("/ingest/conversation", {
      role: getRole(message),
      content,
      project_id: this.config.projectId ?? "openclaw",
      session_id: sessionId,
      turn_index: this.nextTurnIndex(sessionId),
      workspace_id: this.config.workspaceId,
      device_id: this.config.deviceId,
      agent_id: this.config.agentId,
      source_key: "chat_openclaw",
      ingestion_mode: "active",
    });
  }

  async bootstrap(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
  }): Promise<BootstrapResult> {
    await this.client.post("/openclaw/session/register", {
      ...this.identityPayload(params.sessionId),
      context_engine: this.config.contextEngineId,
      metadata: {
        plugin: PLUGIN_ID,
        session_file: params.sessionFile,
      },
    });
    return { bootstrapped: true, reason: "registered-with-agentic-memory" };
  }

  async ingest(params: {
    sessionId: string;
    sessionKey?: string;
    message: AgentMessage;
    isHeartbeat?: boolean;
  }): Promise<IngestResult> {
    await this.ingestOne(params.sessionId, params.message);
    return { ingested: true };
  }

  async ingestBatch(params: {
    sessionId: string;
    sessionKey?: string;
    messages: AgentMessage[];
    isHeartbeat?: boolean;
  }): Promise<IngestBatchResult> {
    let ingestedCount = 0;
    for (const message of params.messages) {
      const text = normalizeMessageText(message.content);
      if (!text.trim()) {
        continue;
      }
      await this.ingestOne(params.sessionId, message);
      ingestedCount += 1;
    }
    return { ingestedCount };
  }

  async afterTurn(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
    messages: AgentMessage[];
    prePromptMessageCount: number;
    autoCompactionSummary?: string;
    isHeartbeat?: boolean;
    tokenBudget?: number;
    runtimeContext?: Record<string, unknown>;
  }): Promise<void> {
    const ingestParams: {
      sessionId: string;
      messages: AgentMessage[];
      isHeartbeat?: boolean;
    } = {
      sessionId: params.sessionId,
      messages: params.messages.slice(params.prePromptMessageCount),
    };
    if (params.isHeartbeat !== undefined) {
      ingestParams.isHeartbeat = params.isHeartbeat;
    }
    await this.ingestBatch(ingestParams);
  }

  async assemble(params: {
    sessionId: string;
    sessionKey?: string;
    messages: AgentMessage[];
    tokenBudget?: number;
    model?: string;
    prompt?: string;
  }): Promise<AssembleResult> {
    const query =
      params.prompt ??
      normalizeMessageText(params.messages.at(-1)?.content) ??
      "Recall the most relevant shared workspace context.";
    const response = await this.client.post<{
      context_blocks?: BackendContextBlock[];
      system_prompt_addition?: string;
    }>("/openclaw/context/resolve", {
      ...this.identityPayload(params.sessionId),
      context_engine: this.config.contextEngineId,
      query,
      limit: 6,
      context_budget_tokens: params.tokenBudget,
      include_system_prompt: true,
    });

    const blocks = Array.isArray(response.context_blocks) ? response.context_blocks : [];
    const contextText = blocks
      .map((block, index) => {
        const title = block.title ?? `Memory block ${index + 1}`;
        const source = block.source ?? "memory";
        const body = block.content ?? "";
        return `[#${index + 1}] ${title} (${source})\n${body}`;
      })
      .join("\n\n");
    const messages = contextText
      ? [
          {
            role: "system",
            content: `Shared Agentic Memory context:\n\n${contextText}`,
          },
          ...params.messages,
        ]
      : params.messages;

    return {
      messages,
      estimatedTokens: estimateTokenCount(contextText),
      ...(response.system_prompt_addition
        ? { systemPromptAddition: response.system_prompt_addition }
        : {}),
    };
  }

  async compact(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
    tokenBudget?: number;
    force?: boolean;
    currentTokenCount?: number;
    compactionTarget?: "budget" | "threshold";
    customInstructions?: string;
    runtimeContext?: Record<string, unknown>;
  }): Promise<CompactResult> {
    const result: {
      summary: string;
      tokensBefore: number;
      tokensAfter?: number;
    } = {
      summary: "Agentic Memory delegates compaction to the OpenClaw runtime in v1.",
      tokensBefore: params.currentTokenCount ?? 0,
    };
    if (params.currentTokenCount !== undefined) {
      result.tokensAfter = params.currentTokenCount;
    }

    return {
      ok: true,
      compacted: false,
      reason: "delegated-to-openclaw-runtime",
      result,
    };
  }

  async dispose(): Promise<void> {
    this.turnIndexBySession.clear();
  }
}

function buildMemoryPromptSection(params: { availableTools: Set<string> }): string[] {
  if (!params.availableTools.has("memory_search")) {
    return [];
  }

  return [
    "## Shared Agentic Memory",
    "Before answering questions about prior work, decisions, or multi-device activity, query shared Agentic Memory first.",
    "",
  ];
}

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Agentic Memory",
  description: "Shared Agentic Memory runtime and context engine for OpenClaw.",
  kind: "memory",
  configSchema: PLUGIN_CONFIG_SCHEMA,
  register(api: any) {
    api.registerCli(({ program, config, workspaceDir, logger }: AgenticMemoryCliContext) => {
      registerAgenticMemoryCli({ program, config, workspaceDir, logger });
    }, {
      descriptors: [
        {
          name: PLUGIN_ID,
          description: "Configure the Agentic Memory plugin",
          hasSubcommands: true,
        },
      ],
    });

    if (api.registrationMode === "cli-metadata") {
      return;
    }

    const config = resolveAgenticMemoryPluginConfig(
      asRecord(api.pluginConfig),
      asString(asRecord(api.pluginConfig).agentId),
    );
    const client = new AgenticMemoryBackendClient(config, api.logger);

    api.registerMemoryPromptSection(buildMemoryPromptSection);
    api.registerMemoryRuntime({
      async getMemorySearchManager(params: {
        cfg: unknown;
        agentId: string;
        purpose?: "default" | "status";
      }) {
        const mergedConfig = resolveAgenticMemoryPluginConfig(asRecord(api.pluginConfig), params.agentId);
        return {
          manager: new AgenticMemorySearchManager(
            new AgenticMemoryBackendClient(mergedConfig, api.logger),
            mergedConfig,
          ),
        };
      },
      resolveMemoryBackendConfig() {
        return {
          backend: "builtin",
        } as const;
      },
      async closeAllMemorySearchManagers() {
        // The current runtime is stateless per manager instance.
      },
    });

    api.registerContextEngine(config.contextEngineId, async () => {
      return new AgenticMemoryContextEngine(client, config);
    });
  },
});
