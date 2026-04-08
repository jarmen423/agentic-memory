/**
 * OpenClaw-native setup command for the Agentic Memory plugin.
 *
 * This module owns the interactive/non-interactive configuration flow that
 * writes directly into the active OpenClaw profile. It is separated from the
 * runtime transport code so the plugin's install-time security heuristics see
 * a clearer split between "config wizard" and "networked memory backend."
 */

import { stdin as input, stdout as output } from "node:process";
import { createInterface } from "node:readline/promises";
import { updateConfig } from "openclaw/plugin-sdk/config-runtime";
import {
  asRecord,
  asString,
  createDefaultAgentId,
  createDefaultDeviceId,
  DEFAULT_BACKEND_URL,
  DEFAULT_CONTEXT_ENGINE_ID,
  OpenClawConfig,
  PLUGIN_ID,
  PluginLogger,
} from "./shared.js";

export type SetupCommandOptions = {
  backendUrl?: string;
  apiKey?: string;
  workspace?: string;
  workspaceId?: string;
  deviceId?: string;
  agentId?: string;
  projectId?: string;
  enableContextEngine?: boolean;
  disableContextEngine?: boolean;
  json?: boolean;
};

export type ResolvedSetupValues = {
  backendUrl: string;
  apiKey: string;
  workspaceId: string;
  deviceId: string;
  agentId: string;
  projectId: string | null;
  enableContextEngine: boolean;
};

export type AgenticMemoryCliContext = {
  program: any;
  config: OpenClawConfig;
  workspaceDir: string | undefined;
  logger: PluginLogger;
};

function isInteractiveTerminal(): boolean {
  return Boolean(input.isTTY && output.isTTY);
}

function resolveExistingPluginConfig(config: OpenClawConfig): Record<string, unknown> {
  const plugins = asRecord(config.plugins);
  const entries = asRecord(plugins.entries);
  const pluginEntry = asRecord(entries[PLUGIN_ID]);
  return asRecord(pluginEntry.config);
}

function resolveExistingContextEngineSelection(config: OpenClawConfig): boolean {
  const plugins = asRecord(config.plugins);
  const slots = asRecord(plugins.slots);
  return asString(slots.contextEngine) === DEFAULT_CONTEXT_ENGINE_ID;
}

/**
 * Apply the plugin's config into the active OpenClaw config object.
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

  const backendUrlDefault = options.backendUrl?.trim() || asString(existing.backendUrl) || DEFAULT_BACKEND_URL;
  const apiKeyDefault = options.apiKey?.trim() || asString(existing.apiKey) || "${AGENTIC_MEMORY_API_KEY}";
  const workspaceIdDefault =
    options.workspace?.trim() ||
    options.workspaceId?.trim() ||
    asString(existing.workspaceId) ||
    "default-workspace";
  const deviceIdDefault = options.deviceId?.trim() || asString(existing.deviceId) || createDefaultDeviceId();
  const agentIdDefault = options.agentId?.trim() || asString(existing.agentId) || createDefaultAgentId();
  const projectIdDefault = options.projectId?.trim() || asString(existing.projectId) || "";

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
  const apiKey = await promptWithDefault("API key or interpolation template", apiKeyDefault);
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
 */
export function registerAgenticMemoryCli(ctx: AgenticMemoryCliContext): void {
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
    .option("--workspace <id>", "OpenClaw workspace identifier (friendly alias for --workspace-id)")
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
