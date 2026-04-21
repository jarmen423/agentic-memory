/**
 * OpenClaw runtime adapters backed by Agentic Memory.
 *
 * This file owns the high-level memory and context-engine behaviors that
 * OpenClaw calls during a live session. It deliberately does not implement raw
 * HTTP itself; instead it depends on `AgenticMemoryBackendClient` so the code
 * remains easier to audit and reason about.
 *
 * Product semantics:
 *
 * - memory owns session registration, turn capture, search, and read
 * - context augmentation is optional and only affects `assemble()`
 *
 * Current OpenClaw host lifecycle hooks arrive through the ContextEngine
 * interface, so this implementation still uses those callbacks as the event
 * source for capture. That is an implementation detail rather than the
 * user-facing mental model.
 */

import type {
  AgentMessage,
  AssembleResult,
  BootstrapResult,
  CompactResult,
  ContextEngine,
  IngestBatchResult,
  IngestResult,
} from "openclaw/plugin-sdk";
import { AgenticMemoryBackendClient } from "./backend-client.js";
import {
  asRecord,
  buildSessionId,
  CONTEXT_ENGINE_INFO,
  estimateTokenCount,
  normalizeMessageText,
  PLUGIN_ID,
  resolveAgenticMemoryPluginConfig,
  type ResolvedPluginConfig,
  type SearchManagerStatus,
  type SearchResultRecord,
  type PluginLogger,
} from "./shared.js";

/**
 * Minimal memory-runtime shape that current OpenClaw hosts expect from either
 * the legacy `registerMemoryRuntime(...)` hook or the newer unified
 * `registerMemoryCapability({ runtime })` surface.
 *
 * The plugin keeps this type local instead of importing host-private SDK types
 * so the code remains buildable even when the user's installed OpenClaw version
 * drifts slightly from the repo's local declaration shim.
 */
export interface AgenticMemoryMemoryRuntime {
  getMemorySearchManager(params: {
    cfg: unknown;
    agentId: string;
    purpose?: "default" | "status";
  }): Promise<{
    manager: AgenticMemorySearchManager;
  }>;
  resolveMemoryBackendConfig(params?: unknown): {
    backend: "builtin";
  };
  closeAllMemorySearchManagers(): Promise<void>;
}

/**
 * Minimal unified memory capability shape used by modern OpenClaw builds.
 *
 * Today the plugin only needs to expose:
 *
 * - `runtime`, so CLI/runtime flows can resolve the active memory backend
 * - `promptBuilder`, so memory guidance still reaches prompt assembly through
 *   the preferred capability registration path
 *
 * The host also supports optional `publicArtifacts`, but Agentic Memory does
 * not yet export that surface from the backend, so the plugin intentionally
 * leaves it undefined instead of advertising a fake empty implementation.
 */
export interface AgenticMemoryMemoryCapability {
  runtime: AgenticMemoryMemoryRuntime;
  promptBuilder: typeof buildMemoryPromptSection;
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

function getRole(message: AgentMessage): string {
  const rawRole = typeof message.role === "string" ? message.role.toLowerCase() : "user";
  if (rawRole === "assistant" || rawRole === "system" || rawRole === "tool" || rawRole === "user") {
    return rawRole;
  }
  return "user";
}

export class AgenticMemorySearchManager {
  private readonly cachedFiles = new Map<string, SearchResultRecord>();

  constructor(
    private readonly client: AgenticMemoryBackendClient,
    private readonly config: ResolvedPluginConfig,
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
        mode: this.config.mode,
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

  /**
   * Read a canonical memory document for a previously returned search hit.
   */
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
        mode: this.config.mode,
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

/**
 * Build the memory-runtime adapter for the current plugin config snapshot.
 *
 * OpenClaw still routes some memory flows through the legacy runtime hook while
 * newer builds prefer the unified memory capability. By creating one shared
 * runtime object here, both registration paths stay behaviorally identical
 * instead of drifting over time.
 */
export function createAgenticMemoryMemoryRuntime(params: {
  pluginConfig: Record<string, unknown>;
  logger?: PluginLogger;
}): AgenticMemoryMemoryRuntime {
  return {
    async getMemorySearchManager(runtimeParams) {
      const mergedConfig = resolveAgenticMemoryPluginConfig(
        asRecord(params.pluginConfig),
        runtimeParams.agentId,
      );

      return {
        manager: new AgenticMemorySearchManager(
          new AgenticMemoryBackendClient(mergedConfig, params.logger),
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
  };
}

/**
 * Build the unified memory capability registration payload expected by newer
 * OpenClaw hosts.
 *
 * Registering this capability does not replace the legacy runtime hook yet.
 * The plugin intentionally registers both so:
 *
 * - older hosts continue to work through `registerMemoryRuntime(...)`
 * - newer hosts can discover the active memory plugin through the preferred
 *   capability API and consume prompt/runtime surfaces from one object
 */
export function createAgenticMemoryMemoryCapability(params: {
  pluginConfig: Record<string, unknown>;
  logger?: PluginLogger;
}): AgenticMemoryMemoryCapability {
  return {
    runtime: createAgenticMemoryMemoryRuntime(params),
    promptBuilder: buildMemoryPromptSection,
  };
}

export class AgenticMemoryContextEngine implements ContextEngine {
  readonly info = CONTEXT_ENGINE_INFO;

  private readonly turnIndexBySession = new Map<string, number>();

  constructor(
    private readonly client: AgenticMemoryBackendClient,
    private readonly config: ResolvedPluginConfig,
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
        mode: this.config.mode,
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

    await this.client.post("/openclaw/memory/ingest-turn", {
      ...this.identityPayload(sessionId),
      role: getRole(message),
      content,
      turn_index: this.nextTurnIndex(sessionId),
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
      mode: this.config.mode,
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
    if (this.config.mode !== "augment_context") {
      return {
        messages: params.messages,
        estimatedTokens: 0,
      };
    }

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

export function buildMemoryPromptSection(params: { availableTools: Set<string> }): string[] {
  if (!params.availableTools.has("memory_search")) {
    return [];
  }

  return [
    "## Shared Agentic Memory",
    "Before answering questions about prior work, decisions, or multi-device activity, query shared Agentic Memory first.",
    "",
  ];
}
