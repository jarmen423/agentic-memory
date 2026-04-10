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
import { AgenticMemoryBackendClient } from "./backend-client.js";
import {
  asRecord,
  asString,
  createDefaultAgentId,
  createDefaultDeviceId,
  createDefaultWorkspaceId,
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
  mode?: "capture_only" | "augment_context";
  enableContextAugmentation?: boolean;
  disableContextAugmentation?: boolean;
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
  mode: "capture_only" | "augment_context";
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

function resolveExistingMode(config: OpenClawConfig): "capture_only" | "augment_context" {
  const existing = resolveExistingPluginConfig(config);
  return existing.mode === "augment_context" ? "augment_context" : "capture_only";
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
      mode: values.mode,
    },
  };

  nextSlots.memory = PLUGIN_ID;
  nextSlots.contextEngine = DEFAULT_CONTEXT_ENGINE_ID;

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
  if (
    options.enableContextAugmentation &&
    options.disableContextAugmentation
  ) {
    throw new Error(
      "Use either --enable-context-augmentation or --disable-context-augmentation, not both.",
    );
  }
  if (options.enableContextEngine && options.disableContextEngine) {
    throw new Error("Use either --enable-context-engine or --disable-context-engine, not both.");
  }
}

/**
 * Resolve the workspace Agentic Memory should use when the operator does not
 * provide one explicitly.
 *
 * The setup UX is intentionally biased toward "memory just works." That means
 * workspace should quietly follow the resolved agent identity unless the user
 * overrides it with a flag or an existing persisted config already pins a
 * different home base.
 */
function resolveWorkspaceIdDefault(
  existing: Record<string, unknown>,
  options: SetupCommandOptions,
  agentIdDefault: string,
): string {
  return (
    options.workspace?.trim() ||
    options.workspaceId?.trim() ||
    asString(existing.workspaceId) ||
    createDefaultWorkspaceId(agentIdDefault)
  );
}

async function resolveSetupValues(
  currentConfig: OpenClawConfig,
  options: SetupCommandOptions,
): Promise<ResolvedSetupValues> {
  ensureSetupFlagCompatibility(options);

  const existing = resolveExistingPluginConfig(currentConfig);
  const interactive = isInteractiveTerminal();
  const modeDefault =
    options.mode ??
    (options.enableContextAugmentation || options.enableContextEngine
      ? "augment_context"
      : options.disableContextAugmentation || options.disableContextEngine
        ? "capture_only"
        : resolveExistingMode(currentConfig));

  const backendUrlDefault = options.backendUrl?.trim() || asString(existing.backendUrl) || DEFAULT_BACKEND_URL;
  const apiKeyDefault = options.apiKey?.trim() || asString(existing.apiKey) || "${AGENTIC_MEMORY_API_KEY}";
  const deviceIdDefault = options.deviceId?.trim() || asString(existing.deviceId) || createDefaultDeviceId();
  const agentIdDefault = options.agentId?.trim() || asString(existing.agentId) || createDefaultAgentId();
  const workspaceIdDefault = resolveWorkspaceIdDefault(existing, options, agentIdDefault);

  if (!interactive) {
    return {
      backendUrl: backendUrlDefault,
      apiKey: apiKeyDefault,
      workspaceId: workspaceIdDefault,
      deviceId: deviceIdDefault,
      agentId: agentIdDefault,
      projectId: null,
      mode: modeDefault,
    };
  }

  const backendUrl = await promptWithDefault("Agentic Memory backend URL", backendUrlDefault);
  const apiKey = await promptWithDefault("API key or interpolation template", apiKeyDefault);
  const deviceId = await promptWithDefault("Device ID", deviceIdDefault);
  const agentId = await promptWithDefault("Agent ID", agentIdDefault);
  const workspaceId = resolveWorkspaceIdDefault(existing, options, agentId);
  const enableContextAugmentation = await promptYesNo(
    "Enable Agentic Memory context augmentation now?",
    modeDefault === "augment_context",
  );

  return {
    backendUrl,
    apiKey,
    workspaceId,
    deviceId,
    agentId,
    projectId: null,
    mode: enableContextAugmentation ? "augment_context" : "capture_only",
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
    mode: values.mode,
    contextAugmentationEnabled: values.mode === "augment_context",
  };

  if (options.json) {
    output.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }

  output.write(`Configured ${PLUGIN_ID} in the active OpenClaw profile.\n`);
  output.write(`Backend: ${values.backendUrl}\n`);
  output.write(`Workspace: ${values.workspaceId} (auto-resolved unless overridden)\n`);
  output.write(`Device: ${values.deviceId}\n`);
  output.write(`Agent: ${values.agentId}\n`);
  output.write(`Memory slot: ${PLUGIN_ID}\n`);
  output.write(`Capture mode: memory capture enabled\n`);
  output.write(
    `Context augmentation: ${values.mode === "augment_context" ? "enabled" : "disabled"}\n`,
  );
  ctx.logger.info?.("Agentic Memory plugin setup complete.");
}

type ProjectCommandOptions = {
  sessionId: string;
  workspace?: string;
  workspaceId?: string;
  deviceId?: string;
  agentId?: string;
  json?: boolean;
  automation?: boolean;
};

type ProjectStopOptions = Omit<ProjectCommandOptions, "automation">;

function resolveProjectCommandConfig(
  currentConfig: OpenClawConfig,
  options: ProjectCommandOptions | ProjectStopOptions,
) {
  const existing = resolveExistingPluginConfig(currentConfig);
  const agentId =
    options.agentId?.trim() || asString(existing.agentId) || createDefaultAgentId();
  return {
    backendUrl: asString(existing.backendUrl) ?? DEFAULT_BACKEND_URL,
    apiKey: asString(existing.apiKey) ?? null,
    workspaceId: resolveWorkspaceIdDefault(existing, options, agentId),
    deviceId: options.deviceId?.trim() || asString(existing.deviceId) || createDefaultDeviceId(),
    agentId,
  };
}

function printProjectPayload(payload: Record<string, unknown>, json = false): void {
  if (json) {
    output.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }
  output.write(`${JSON.stringify(payload, null, 2)}\n`);
}

/**
 * Activate a project for one OpenClaw session.
 *
 * `init` and `use` deliberately share the same backend write today:
 *
 * - `init` is the user-facing "start working on this project now" command
 * - `use` is the user-facing "switch into an existing project" command
 * - `start` remains as a backward-compatible alias
 *
 * The backend treats project activation idempotently, so repeated calls are
 * safe and simply keep the requested project active for the target session.
 */
async function activateProjectForSession(
  ctx: AgenticMemoryCliContext,
  projectId: string,
  options: ProjectCommandOptions,
  action: "project_init" | "project_use" | "project_start",
): Promise<void> {
  const config = resolveProjectCommandConfig(ctx.config, options);
  const client = new AgenticMemoryBackendClient(
    {
      ...config,
      projectId: null,
      contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
      mode: resolveExistingMode(ctx.config),
    },
    ctx.logger,
  );
  const activation = await client.post("/openclaw/project/activate", {
    workspace_id: config.workspaceId,
    device_id: config.deviceId,
    agent_id: config.agentId,
    session_id: options.sessionId,
    project_id: projectId,
    title: projectId,
    metadata: { plugin: PLUGIN_ID, action },
  });
  let automation: unknown = null;
  if (options.automation) {
    automation = await client.post("/openclaw/project/automation", {
      workspace_id: config.workspaceId,
      project_id: projectId,
      automation_kind: "research_ingestion",
      enabled: true,
      metadata: { plugin: PLUGIN_ID, action },
    });
  }
  printProjectPayload(
    {
      ok: true,
      action,
      projectId,
      sessionId: options.sessionId,
      workspaceId: config.workspaceId,
      agentId: config.agentId,
      activation,
      automation,
    },
    options.json,
  );
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
    .option(
      "--workspace <id>",
      "Optional workspace override. When omitted, Agentic Memory auto-resolves the workspace from the active agent/default config.",
    )
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option(
      "--mode <mode>",
      "Plugin mode: capture_only or augment_context",
    )
    .option("--enable-context-augmentation", "Enable Agentic Memory context augmentation", false)
    .option("--disable-context-augmentation", "Leave Agentic Memory in capture-only mode", false)
    .option("--enable-context-engine", "Legacy alias for --enable-context-augmentation", false)
    .option("--disable-context-engine", "Legacy alias for --disable-context-augmentation", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: SetupCommandOptions) => {
      const values = await resolveSetupValues(ctx.config, options);
      await updateConfig((config) => mergeAgenticMemoryPluginConfigIntoOpenClawConfig(config, values));
      printSetupResult(ctx, values, options);
    });

  const project = root.command("project").description("Manage the active Agentic Memory project");

  project
    .command("init <projectId>")
    .description("Create or activate a project for the current OpenClaw session")
    .requiredOption("--session-id <id>", "Session identifier to scope the active project")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--automation", "Also enable project automation for this workspace", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (projectId: string, options: ProjectCommandOptions) => {
      await activateProjectForSession(ctx, projectId, options, "project_init");
    });

  project
    .command("use <projectId>")
    .description("Switch the current OpenClaw session into an existing project")
    .requiredOption("--session-id <id>", "Session identifier to scope the active project")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--automation", "Also enable project automation for this workspace", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (projectId: string, options: ProjectCommandOptions) => {
      await activateProjectForSession(ctx, projectId, options, "project_use");
    });

  project
    .command("start <projectId>")
    .description("Legacy alias for project init")
    .requiredOption("--session-id <id>", "Session identifier to scope the active project")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--automation", "Also enable project automation for this workspace", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (projectId: string, options: ProjectCommandOptions) => {
      await activateProjectForSession(ctx, projectId, options, "project_start");
    });

  project
    .command("stop")
    .description("Deactivate the current project for one OpenClaw session")
    .requiredOption("--session-id <id>", "Session identifier to clear")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: ProjectStopOptions) => {
      const config = resolveProjectCommandConfig(ctx.config, options);
      const client = new AgenticMemoryBackendClient(
        {
          ...config,
          projectId: null,
          contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
          mode: resolveExistingMode(ctx.config),
        },
        ctx.logger,
      );
      const response = await client.post("/openclaw/project/deactivate", {
        workspace_id: config.workspaceId,
        device_id: config.deviceId,
        agent_id: config.agentId,
        session_id: options.sessionId,
        metadata: { plugin: PLUGIN_ID },
      });
      printProjectPayload(
        {
          ok: true,
          action: "project_stop",
          sessionId: options.sessionId,
          response,
        },
        options.json,
      );
    });

  project
    .command("status")
    .description("Show the active project for one OpenClaw session")
    .requiredOption("--session-id <id>", "Session identifier to inspect")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: ProjectStopOptions) => {
      const config = resolveProjectCommandConfig(ctx.config, options);
      const client = new AgenticMemoryBackendClient(
        {
          ...config,
          projectId: null,
          contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
          mode: resolveExistingMode(ctx.config),
        },
        ctx.logger,
      );
      const response = await client.post("/openclaw/project/status", {
        workspace_id: config.workspaceId,
        device_id: config.deviceId,
        agent_id: config.agentId,
        session_id: options.sessionId,
        metadata: { plugin: PLUGIN_ID },
      });
      printProjectPayload(
        {
          ok: true,
          action: "project_status",
          sessionId: options.sessionId,
          response,
        },
        options.json,
      );
    });
}
