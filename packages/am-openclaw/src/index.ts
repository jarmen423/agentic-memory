/**
 * Thin OpenClaw plugin registration entrypoint for Agentic Memory.
 *
 * The project previously kept setup, transport, and runtime behavior inside one
 * file. This entrypoint now stays intentionally small and delegates to
 * dedicated modules:
 *
 * - `shared.ts`: domain model and config helpers
 * - `setup.ts`: native `openclaw agentic-memory setup` command
 * - `backend-client.ts`: raw HTTP transport to the Agentic Memory backend
 * - `runtime.ts`: OpenClaw memory runtime and context engine adapters
 *
 * That split preserves behavior while making the trust boundaries in the code
 * easier for humans and static security heuristics to understand.
 */

import { definePluginEntry } from "openclaw/plugin-sdk/core";
import { AgenticMemoryBackendClient } from "./backend-client.js";
import {
  AgenticMemoryContextEngine,
  AgenticMemorySearchManager,
  buildMemoryPromptSection,
} from "./runtime.js";
import { registerAgenticMemoryCli, type AgenticMemoryCliContext } from "./setup.js";
import {
  asRecord,
  asString,
  OPENCLAW_PACKAGE_INFO,
  PLUGIN_CONFIG_SCHEMA,
  PLUGIN_ID,
  resolveAgenticMemoryPluginConfig,
} from "./shared.js";

export {
  buildOpenClawBootstrapConfig,
  OPENCLAW_PACKAGE_INFO,
  resolveAgenticMemoryPluginConfig,
} from "./shared.js";
export { mergeAgenticMemoryPluginConfigIntoOpenClawConfig } from "./setup.js";

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Agentic Memory",
  description: "Shared Agentic Memory runtime and context engine for OpenClaw.",
  /**
   * The runtime intentionally exposes both plugin capabilities:
   *
   * - `memory`: retrieval, canonical reads, and capture plumbing
   * - `context-engine`: optional context assembly plus the current
   *   OpenClaw lifecycle hook surface used for turn capture
   *
   * OpenClaw doctor compares this exported kind against the manifest kind, so
   * the entrypoint must advertise the same multi-kind surface as
   * `openclaw.plugin.json`.
   */
  kind: ["memory", "context-engine"] as any,
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
