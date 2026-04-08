/**
 * Backend HTTP transport for the Agentic Memory OpenClaw plugin.
 *
 * This module is intentionally the only place that performs raw HTTP requests.
 * Keeping transport isolated makes the trust boundary clearer for reviewers and
 * avoids mixing network code with setup wizard code or higher-level memory APIs.
 */

import type { PluginLogger, ResolvedPluginConfig } from "./shared.js";

export class AgenticMemoryBackendClient {
  private readonly logger: PluginLogger | undefined;

  constructor(
    private readonly config: ResolvedPluginConfig,
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

  /**
   * Send a typed POST request to the Agentic Memory backend.
   */
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
