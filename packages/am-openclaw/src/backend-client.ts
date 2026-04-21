/**
 * Backend HTTP transport for the Agentic Memory OpenClaw plugin.
 *
 * This module is intentionally the only place that performs raw HTTP requests.
 * Keeping transport isolated makes the trust boundary clearer for reviewers and
 * avoids mixing network code with setup wizard code or higher-level memory APIs.
 */

import type { PluginLogger, ResolvedPluginConfig } from "./shared.js";

const TRANSIENT_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);
const MAX_RETRY_ATTEMPTS = 3;
const RETRY_BASE_DELAY_MS = 150;

type BackendErrorEnvelope = {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    status?: number;
    details?: unknown;
  };
};

/**
 * Common OpenClaw identity payload sent by plugin-owned runtime, CLI, and tool
 * bridge requests.
 *
 * Keeping this shape in the backend client makes it easier to evolve the HTTP
 * contract without duplicating the same identity object in several modules.
 */
export type OpenClawBackendIdentityPayload = {
  workspace_id: string;
  device_id: string;
  agent_id: string;
  session_id: string;
  project_id?: string | null;
  metadata?: Record<string, unknown>;
};

/**
 * JSON shape returned by the plugin's tool-bridge endpoints.
 *
 * Each route returns a human-readable `text` field for the OpenClaw tool
 * surface plus an optional structured `payload` that the plugin can surface in
 * `structuredContent`.
 */
export type OpenClawBackendTextToolResponse<TPayload = unknown> = {
  status: "ok";
  text: string;
  payload?: TPayload;
  identity?: Record<string, unknown>;
};

/**
 * Stable backend error type used by the plugin runtime and setup commands.
 *
 * The backend now returns a machine-readable error envelope. This class keeps
 * that data structured so callers can decide whether to retry, fall back, or
 * surface a clearer operator-facing message.
 */
export class AgenticMemoryBackendError extends Error {
  constructor(
    message: string,
    readonly options: {
      status?: number | undefined;
      code?: string | undefined;
      requestId?: string | undefined;
      details?: unknown;
      retryable?: boolean | undefined;
      path: string;
    },
  ) {
    super(message);
    this.name = "AgenticMemoryBackendError";
  }

  get status(): number | undefined {
    return this.options.status;
  }

  get code(): string | undefined {
    return this.options.code;
  }

  get requestId(): string | undefined {
    return this.options.requestId;
  }

  get details(): unknown {
    return this.options.details;
  }

  get retryable(): boolean {
    return Boolean(this.options.retryable);
  }
}

export class AgenticMemoryBackendClient {
  private readonly logger: PluginLogger | undefined;

  constructor(
    private readonly config: ResolvedPluginConfig,
    logger?: PluginLogger,
  ) {
    this.logger = logger;
  }

  private async sleep(ms: number): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, ms));
  }

  private retryDelayMs(attempt: number): number {
    return RETRY_BASE_DELAY_MS * (2 ** attempt);
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

  private shouldRetryStatus(status: number): boolean {
    return TRANSIENT_STATUS_CODES.has(status);
  }

  private parseBackendErrorBody(rawBody: string): BackendErrorEnvelope["error"] | null {
    if (!rawBody.trim()) {
      return null;
    }

    try {
      const parsed = JSON.parse(rawBody) as BackendErrorEnvelope;
      if (parsed && typeof parsed === "object" && parsed.error && typeof parsed.error === "object") {
        return parsed.error;
      }
    } catch {
      // Some failures will still return plain text from upstream proxies or
      // older backends. In that case we fall back to the raw body below.
    }

    return null;
  }

  private async buildResponseError(path: string, response: Response): Promise<AgenticMemoryBackendError> {
    const rawBody = await response.text();
    const parsed = this.parseBackendErrorBody(rawBody);
    const status = response.status;
    const requestId = parsed?.request_id;
    const code = parsed?.code ?? `http_${status}`;
    const message = parsed?.message ?? (rawBody || `HTTP ${status}`);
    const formatted = requestId
      ? `Agentic Memory backend request failed (${status} ${code}, request ${requestId}): ${message}`
      : `Agentic Memory backend request failed (${status} ${code}): ${message}`;

    return new AgenticMemoryBackendError(formatted, {
      status,
      code,
      requestId,
      details: parsed?.details,
      retryable: this.shouldRetryStatus(status),
      path,
    });
  }

  private buildTransportError(path: string, error: unknown): AgenticMemoryBackendError {
    const message = error instanceof Error ? error.message : String(error);
    return new AgenticMemoryBackendError(
      `Agentic Memory backend request failed (network_error): ${message}`,
      {
        code: "network_error",
        retryable: true,
        details: { cause: message },
        path,
      },
    );
  }

  /**
   * Send one JSON request to the Agentic Memory backend with retry logic.
   *
   * We keep one internal request helper so setup/doctor and runtime code share
   * the same transport guarantees and error shape.
   */
  private async requestJson<T>(
    method: "GET" | "POST",
    path: string,
    payload?: Record<string, unknown>,
  ): Promise<T> {
    const url = new URL(path, this.config.backendUrl).toString();
    let lastError: AgenticMemoryBackendError | null = null;

    for (let attempt = 0; attempt < MAX_RETRY_ATTEMPTS; attempt += 1) {
      try {
        const response = await fetch(url, {
          method,
          headers: this.buildHeaders(),
          ...(payload ? { body: JSON.stringify(payload) } : {}),
        });

        if (!response.ok) {
          const error = await this.buildResponseError(path, response);
          if (!error.retryable || attempt === MAX_RETRY_ATTEMPTS - 1) {
            this.logger?.warn?.("Agentic Memory backend request failed", {
              path,
              status: error.status,
              code: error.code,
              requestId: error.requestId,
            });
            throw error;
          }

          lastError = error;
          this.logger?.warn?.("Agentic Memory backend transient failure; retrying", {
            path,
            status: error.status,
            code: error.code,
            requestId: error.requestId,
            attempt: attempt + 1,
            maxAttempts: MAX_RETRY_ATTEMPTS,
          });
          await this.sleep(this.retryDelayMs(attempt));
          continue;
        }

        return (await response.json()) as T;
      } catch (error) {
        const backendError =
          error instanceof AgenticMemoryBackendError ? error : this.buildTransportError(path, error);
        if (!backendError.retryable || attempt === MAX_RETRY_ATTEMPTS - 1) {
          this.logger?.warn?.("Agentic Memory backend transport failed", {
            path,
            code: backendError.code,
            requestId: backendError.requestId,
          });
          throw backendError;
        }

        lastError = backendError;
        this.logger?.warn?.("Agentic Memory backend transport failed; retrying", {
          path,
          code: backendError.code,
          attempt: attempt + 1,
          maxAttempts: MAX_RETRY_ATTEMPTS,
        });
        await this.sleep(this.retryDelayMs(attempt));
      }
    }

    throw lastError ?? new AgenticMemoryBackendError("Agentic Memory backend request failed.", {
      code: "unknown_error",
      retryable: false,
      path,
    });
  }

  /**
   * Send a typed GET request to the Agentic Memory backend.
   */
  async get<T>(path: string): Promise<T> {
    return this.requestJson<T>("GET", path);
  }

  /**
   * Send a typed POST request to the Agentic Memory backend.
   */
  async post<T>(path: string, payload: Record<string, unknown>): Promise<T> {
    return this.requestJson<T>("POST", path, payload);
  }

  /**
   * Run unified memory search through the OpenClaw-specific backend contract.
   *
   * This is the same search surface used by the runtime memory adapter. The
   * tool bridge reuses it so OpenClaw's explicit tools and memory runtime stay
   * grounded in the same backend search implementation.
   */
  async searchAllMemory(payload: OpenClawBackendIdentityPayload & {
    query: string;
    limit?: number;
    repo_id?: string | null;
    as_of?: string | null;
    modules?: string[] | null;
  }): Promise<{
    results?: Array<Record<string, unknown>>;
    response?: Record<string, unknown>;
    identity?: Record<string, unknown>;
  }> {
    return this.post("/openclaw/memory/search", payload);
  }

  /**
   * Run codebase search through the OpenClaw tool bridge.
   */
  async searchCodebaseTool(payload: OpenClawBackendIdentityPayload & {
    query: string;
    limit?: number;
    domain?: string;
    repo_id?: string | null;
  }): Promise<OpenClawBackendTextToolResponse> {
    return this.post("/openclaw/tools/search-codebase", payload);
  }

  /**
   * List known project ids and repo ids for explicit agent-side scope selection.
   */
  async listProjectAndRepoIdsTool(
    payload: OpenClawBackendIdentityPayload,
  ): Promise<OpenClawBackendTextToolResponse> {
    return this.post("/openclaw/tools/list-project-and-repo-ids", payload);
  }

  /**
   * Return direct and reverse import relationships for one file.
   */
  async getFileDependenciesTool(payload: OpenClawBackendIdentityPayload & {
    file_path: string;
    repo_id?: string | null;
  }): Promise<OpenClawBackendTextToolResponse> {
    return this.post("/openclaw/tools/get-file-dependencies", payload);
  }

  /**
   * Trace likely execution edges for one function or symbol.
   */
  async traceExecutionPathTool(payload: OpenClawBackendIdentityPayload & {
    start_symbol: string;
    max_depth?: number;
    force_refresh?: boolean;
    repo_id?: string | null;
  }): Promise<OpenClawBackendTextToolResponse> {
    return this.post("/openclaw/tools/trace-execution-path", payload);
  }

  /**
   * Search conversation memory with OpenClaw identity/project routing applied.
   */
  async searchConversationsTool(payload: OpenClawBackendIdentityPayload & {
    query: string;
    limit?: number;
    role?: string | null;
    as_of?: string | null;
  }): Promise<OpenClawBackendTextToolResponse> {
    return this.post("/openclaw/tools/search-conversations", payload);
  }

  /**
   * Retrieve a structured conversation-context bundle for one query.
   */
  async getConversationContextTool(payload: OpenClawBackendIdentityPayload & {
    query: string;
    limit?: number;
    include_session_context?: boolean;
    as_of?: string | null;
  }): Promise<OpenClawBackendTextToolResponse> {
    return this.post("/openclaw/tools/get-conversation-context", payload);
  }
}
