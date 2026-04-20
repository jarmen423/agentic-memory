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
import { AgenticMemoryBackendClient } from "./backend-client.js";
import {
  formatDoctorText,
  runAgenticMemoryDoctor,
  validateSetupAgainstContract,
} from "./doctor.js";
import { AgenticMemorySearchManager } from "./runtime.js";
import {
  asRecord,
  asString,
  createDefaultAgentId,
  createDefaultDeviceId,
  createDefaultWorkspaceId,
  DEFAULT_BACKEND_URL,
  DEFAULT_CONTEXT_ENGINE_ID,
  OpenClawConfig,
  PLUGIN_CONFIG_SCHEMA_VERSION,
  PLUGIN_ID,
  PluginLogger,
  resolveAgenticMemoryPluginConfig,
} from "./shared.js";

export type SetupCommandOptions = {
  hosted?: boolean;
  selfHosted?: boolean;
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
  allowDegraded?: boolean;
  skipDoctor?: boolean;
  json?: boolean;
};

export type ResolvedSetupValues = {
  schemaVersion: number;
  backendKind: "hosted" | "self_hosted";
  backendUrl: string;
  apiKey: string;
  workspaceId: string;
  deviceId: string;
  agentId: string;
  projectId: string | null;
  mode: "capture_only" | "augment_context";
};

export type DoctorCommandOptions = {
  hosted?: boolean;
  selfHosted?: boolean;
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

export type AgenticMemoryCliContext = {
  program: any;
  config: OpenClawConfig;
  workspaceDir: string | undefined;
  logger: PluginLogger;
};

type MemoryStatusCommandOptions = {
  agent?: string;
  json?: boolean;
  deep?: boolean;
};

type MemorySearchCommandOptions = {
  query?: string;
  agent?: string;
  maxResults?: number;
  minScore?: number;
  json?: boolean;
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

function isAgenticMemoryActiveMemoryPlugin(config: OpenClawConfig): boolean {
  const plugins = asRecord(config.plugins);
  const slots = asRecord(plugins.slots);
  return asString(slots.memory) === PLUGIN_ID;
}

function resolveExistingMode(config: OpenClawConfig): "capture_only" | "augment_context" {
  const existing = resolveExistingPluginConfig(config);
  return existing.mode === "augment_context" ? "augment_context" : "capture_only";
}

function resolveExistingBackendKind(config: OpenClawConfig): "hosted" | "self_hosted" | null {
  const existing = resolveExistingPluginConfig(config);
  if (existing.backendKind === "hosted") {
    return "hosted";
  }
  if (existing.backendKind === "self_hosted") {
    return "self_hosted";
  }
  return null;
}

function describeBackendUrlSource(existing: Record<string, unknown>, options: SetupCommandOptions): string {
  if (options.backendUrl?.trim()) {
    return "command flag";
  }
  if (asString(existing.backendUrl)) {
    return "saved config";
  }
  return "default";
}

function describeBackendKindSource(existing: Record<string, unknown>, options: SetupCommandOptions): string {
  if (options.hosted || options.selfHosted) {
    return "command flag";
  }
  if (existing.backendKind === "hosted" || existing.backendKind === "self_hosted") {
    return "saved config";
  }
  return "default";
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
      schemaVersion: values.schemaVersion ?? PLUGIN_CONFIG_SCHEMA_VERSION,
      backendKind: values.backendKind,
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
  defaultValue: string | null,
  options?: { allowEmpty?: boolean },
): Promise<string> {
  const rl = createInterface({ input, output });
  try {
    const prompt = defaultValue ? `${question} [${defaultValue}]: ` : `${question}: `;
    const raw = await rl.question(prompt);
    const trimmed = raw.trim();
    if (!trimmed && options?.allowEmpty) {
      return "";
    }
    if (!trimmed && defaultValue) {
      return defaultValue;
    }
    if (!trimmed) {
      throw new Error(`${question} is required.`);
    }
    return trimmed;
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

async function promptBackendKind(
  defaultValue: "hosted" | "self_hosted",
): Promise<"hosted" | "self_hosted"> {
  const rl = createInterface({ input, output });
  const defaultLabel = defaultValue === "hosted" ? "hosted" : "self-hosted";
  try {
    const raw = await rl.question(
      `Agentic Memory backend mode [${defaultLabel}] (hosted/self-hosted): `,
    );
    const normalized = raw.trim().toLowerCase();
    if (!normalized) {
      return defaultValue;
    }
    if (normalized === "hosted") {
      return "hosted";
    }
    if (normalized === "self-hosted" || normalized === "self_hosted" || normalized === "selfhosted") {
      return "self_hosted";
    }
    throw new Error("Backend mode must be either hosted or self-hosted.");
  } finally {
    rl.close();
  }
}

function ensureSetupFlagCompatibility(options: SetupCommandOptions): void {
  if (options.hosted && options.selfHosted) {
    throw new Error("Use either --hosted or --self-hosted, not both.");
  }
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

function resolveBackendKindDefault(
  currentConfig: OpenClawConfig,
  options: SetupCommandOptions,
): "hosted" | "self_hosted" {
  if (options.hosted) {
    return "hosted";
  }
  if (options.selfHosted) {
    return "self_hosted";
  }
  return resolveExistingBackendKind(currentConfig) ?? "self_hosted";
}

function resolveBackendUrlDefault(
  existing: Record<string, unknown>,
  options: SetupCommandOptions,
  backendKind: "hosted" | "self_hosted",
): string | null {
  if (options.backendUrl?.trim()) {
    return options.backendUrl.trim();
  }
  if (asString(existing.backendUrl)) {
    return asString(existing.backendUrl)!;
  }
  if (backendKind === "hosted") {
    return null;
  }
  return DEFAULT_BACKEND_URL;
}

async function resolveSetupValues(
  currentConfig: OpenClawConfig,
  options: SetupCommandOptions,
): Promise<ResolvedSetupValues> {
  ensureSetupFlagCompatibility(options);

  const existing = resolveExistingPluginConfig(currentConfig);
  const interactive = isInteractiveTerminal();
  const backendKindDefault = resolveBackendKindDefault(currentConfig, options);
  const modeDefault =
    options.mode ??
    (options.enableContextAugmentation || options.enableContextEngine
      ? "augment_context"
      : options.disableContextAugmentation || options.disableContextEngine
        ? "capture_only"
        : resolveExistingMode(currentConfig));

  const backendUrlDefault = resolveBackendUrlDefault(existing, options, backendKindDefault);
  const apiKeyDefault = options.apiKey?.trim() || asString(existing.apiKey) || "${AGENTIC_MEMORY_API_KEY}";
  const deviceIdDefault = options.deviceId?.trim() || asString(existing.deviceId) || createDefaultDeviceId();
  const agentIdDefault = options.agentId?.trim() || asString(existing.agentId) || createDefaultAgentId();
  const workspaceIdDefault = resolveWorkspaceIdDefault(existing, options, agentIdDefault);

  if (!backendUrlDefault) {
    throw new Error(
      backendKindDefault === "hosted"
        ? "No hosted backend URL is configured yet. Pass --backend-url or save one in existing plugin config first."
        : "No self-hosted backend URL is configured yet.",
    );
  }

  if (!interactive) {
    return {
      schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
      backendKind: backendKindDefault,
      backendUrl: backendUrlDefault,
      apiKey: apiKeyDefault,
      workspaceId: workspaceIdDefault,
      deviceId: deviceIdDefault,
      agentId: agentIdDefault,
      projectId: null,
      mode: modeDefault,
    };
  }

  const backendKindSource = describeBackendKindSource(existing, options);
  output.write(`Backend mode default source: ${backendKindSource}\n`);
  const backendKind = await promptBackendKind(backendKindDefault);
  const backendUrl = await promptWithDefault(
    backendKind === "hosted"
      ? `Agentic Memory hosted backend URL (${describeBackendUrlSource(existing, options)})`
      : `Agentic Memory self-hosted backend URL (${describeBackendUrlSource(existing, options)})`,
    resolveBackendUrlDefault(existing, options, backendKind),
  );
  const apiKey = await promptWithDefault("API key or interpolation template", apiKeyDefault);
  const deviceId = await promptWithDefault("Device ID", deviceIdDefault);
  const agentId = await promptWithDefault("Agent ID", agentIdDefault);
  const workspaceId = resolveWorkspaceIdDefault(existing, options, agentId);
  const enableContextAugmentation = await promptYesNo(
    "Enable Agentic Memory context augmentation now?",
    modeDefault === "augment_context",
  );

  return {
    schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
    backendKind,
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
  doctorSummary?: {
    setupReady: boolean;
    captureOnlyReady: boolean;
    augmentContextReady: boolean;
  },
): void {
  const payload = {
    ok: true,
    pluginId: PLUGIN_ID,
    schemaVersion: values.schemaVersion,
    backendKind: values.backendKind,
    backendUrl: values.backendUrl,
    workspaceId: values.workspaceId,
    deviceId: values.deviceId,
    agentId: values.agentId,
    projectId: values.projectId,
    mode: values.mode,
    contextAugmentationEnabled: values.mode === "augment_context",
    doctor: doctorSummary ?? null,
  };

  if (options.json) {
    output.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }

  output.write(`Configured ${PLUGIN_ID} in the active OpenClaw profile.\n`);
  output.write(`Backend kind: ${values.backendKind === "hosted" ? "hosted" : "self-hosted"}\n`);
  output.write(`Backend: ${values.backendUrl}\n`);
  output.write(`Workspace: ${values.workspaceId} (auto-resolved unless overridden)\n`);
  output.write(`Device: ${values.deviceId}\n`);
  output.write(`Agent: ${values.agentId}\n`);
  output.write(`Memory slot: ${PLUGIN_ID}\n`);
  output.write(`Capture mode: memory capture enabled\n`);
  output.write(
    `Context augmentation: ${values.mode === "augment_context" ? "enabled" : "disabled"}\n`,
  );
  if (doctorSummary) {
    output.write(`Backend setup ready: ${doctorSummary.setupReady ? "yes" : "no"}\n`);
    output.write(`Capture-only ready: ${doctorSummary.captureOnlyReady ? "yes" : "no"}\n`);
    output.write(`Augment-context ready: ${doctorSummary.augmentContextReady ? "yes" : "no"}\n`);
  }
  ctx.logger.info?.("Agentic Memory plugin setup complete.");
}

type ProjectCommandOptions = {
  sessionId?: string;
  workspace?: string;
  workspaceId?: string;
  deviceId?: string;
  agentId?: string;
  json?: boolean;
  automation?: boolean;
};

type ProjectStopOptions = Omit<ProjectCommandOptions, "automation">;

async function persistOpenClawConfig(
  mutate: (config: OpenClawConfig) => OpenClawConfig,
): Promise<void> {
  /**
   * `updateConfig` lives in the OpenClaw host runtime package, which is not
   * present in normal package-local test environments. Loading it lazily keeps
   * this module importable for unit tests while preserving the real host
   * behavior at command execution time.
   */
  const { updateConfig } = await import("openclaw/plugin-sdk/config-runtime");
  await updateConfig(mutate);
}

function resolveProjectCommandConfig(
  currentConfig: OpenClawConfig,
  options: ProjectCommandOptions | ProjectStopOptions,
) {
  const existing = resolveExistingPluginConfig(currentConfig);
  const agentId =
    options.agentId?.trim() || asString(existing.agentId) || createDefaultAgentId();
  return {
    backendKind: resolveExistingBackendKind(currentConfig) ?? "self_hosted",
    backendUrl: asString(existing.backendUrl) ?? DEFAULT_BACKEND_URL,
    apiKey: asString(existing.apiKey) ?? null,
    workspaceId: resolveWorkspaceIdDefault(existing, options, agentId),
    deviceId: options.deviceId?.trim() || asString(existing.deviceId) || createDefaultDeviceId(),
    agentId,
  };
}

function resolveDoctorConfig(
  currentConfig: OpenClawConfig,
  options: DoctorCommandOptions,
) {
  const existing = resolveExistingPluginConfig(currentConfig);
  const agentId =
    options.agentId?.trim() || asString(existing.agentId) || createDefaultAgentId();
  const backendKind = resolveBackendKindDefault(currentConfig, options);
  const backendUrl =
    options.backendUrl?.trim() ||
    asString(existing.backendUrl) ||
    (backendKind === "self_hosted" ? DEFAULT_BACKEND_URL : null);

  if (!backendUrl) {
    throw new Error(
      backendKind === "hosted"
        ? "No hosted backend URL is configured yet. Pass --backend-url or save one in plugin config first."
        : "No self-hosted backend URL is configured yet.",
    );
  }

  return {
    schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
    backendKind,
    backendUrl,
    apiKey: options.apiKey?.trim() || asString(existing.apiKey) || null,
    workspaceId: resolveWorkspaceIdDefault(existing, options, agentId),
    deviceId: options.deviceId?.trim() || asString(existing.deviceId) || createDefaultDeviceId(),
    agentId,
    projectId: asString(existing.projectId) ?? null,
    contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
    mode:
      options.mode ??
      (options.enableContextAugmentation || options.enableContextEngine
        ? "augment_context"
        : options.disableContextAugmentation || options.disableContextEngine
          ? "capture_only"
          : resolveExistingMode(currentConfig)),
  };
}

async function printDoctorResult(
  ctx: AgenticMemoryCliContext,
  options: DoctorCommandOptions,
): Promise<void> {
  const config = resolveDoctorConfig(ctx.config, options);
  const report = await runAgenticMemoryDoctor(
    new AgenticMemoryBackendClient(config, ctx.logger),
    config,
  );

  if (options.json) {
    output.write(
      `${JSON.stringify(
        {
          ok: report.ok,
          backendUrl: report.backendUrl,
          backendKind: report.backendKind,
          mode: report.mode,
          readiness: report.contract.readiness,
          blockingReasons: report.blockingReasons,
          localWarnings: report.localWarnings,
          contract: report.contract,
        },
        null,
        2,
      )}\n`,
    );
    return;
  }

  output.write(formatDoctorText(report));
}

function printProjectPayload(payload: Record<string, unknown>, json = false): void {
  if (json) {
    output.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }
  output.write(`${JSON.stringify(payload, null, 2)}\n`);
}

function extractResolvedSessionId(payload: unknown): string | null {
  const record = asRecord(payload);
  const identity = asRecord(record.identity);
  return asString(identity.session_id) ?? null;
}

function buildProjectRequestIdentity(config: {
  workspaceId: string;
  deviceId: string;
  agentId: string;
}, options: ProjectCommandOptions | ProjectStopOptions): Record<string, unknown> {
  return {
    workspace_id: config.workspaceId,
    device_id: config.deviceId,
    agent_id: config.agentId,
    ...(options.sessionId?.trim() ? { session_id: options.sessionId.trim() } : {}),
  };
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
      schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
      ...config,
      projectId: null,
      contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
      mode: resolveExistingMode(ctx.config),
    },
    ctx.logger,
  );
  const activation = await client.post("/openclaw/project/activate", {
    ...buildProjectRequestIdentity(config, options),
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
      sessionId: options.sessionId ?? extractResolvedSessionId(activation),
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
    .option("--hosted", "Use the hosted Agentic Memory path", false)
    .option("--self-hosted", "Use the self-hosted Agentic Memory path", false)
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
    .option(
      "--allow-degraded",
      "Persist config even if doctor says the requested mode is not ready yet",
      false,
    )
    .option("--skip-doctor", "Skip backend readiness validation before writing config", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: SetupCommandOptions) => {
      const values = await resolveSetupValues(ctx.config, options);
      let doctorSummary: {
        setupReady: boolean;
        captureOnlyReady: boolean;
        augmentContextReady: boolean;
      } | undefined;

      if (!options.skipDoctor) {
        const doctorConfig = {
          schemaVersion: values.schemaVersion,
          backendKind: values.backendKind,
          backendUrl: values.backendUrl,
          apiKey: values.apiKey,
          workspaceId: values.workspaceId,
          deviceId: values.deviceId,
          agentId: values.agentId,
          projectId: values.projectId,
          contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
          mode: values.mode,
        };
        const report = await runAgenticMemoryDoctor(
          new AgenticMemoryBackendClient(doctorConfig, ctx.logger),
          doctorConfig,
        );
        const validation = validateSetupAgainstContract(doctorConfig, report.contract);
        doctorSummary = {
          setupReady: report.contract.readiness.setup_ready,
          captureOnlyReady: report.contract.readiness.capture_only_ready,
          augmentContextReady: report.contract.readiness.augment_context_ready,
        };

        if (!validation.ok && !options.allowDegraded) {
          const failureMessage = [
            "Agentic Memory setup refused to save config because the backend is not ready for the requested mode.",
            "",
            formatDoctorText(report).trimEnd(),
            "",
            "Run the doctor command again after fixing the blocking services, or use --allow-degraded if you intentionally want to save config early.",
          ].join("\n");
          throw new Error(failureMessage);
        }
      }

      await persistOpenClawConfig((config) => mergeAgenticMemoryPluginConfigIntoOpenClawConfig(config, values));
      printSetupResult(ctx, values, options, doctorSummary);
    });

  root
    .command("doctor")
    .description("Check whether the configured backend is honestly ready for OpenClaw setup")
    .option("--hosted", "Check readiness for the hosted Agentic Memory path", false)
    .option("--self-hosted", "Check readiness for the self-hosted Agentic Memory path", false)
    .option("--backend-url <url>", "Agentic Memory backend URL")
    .option(
      "--api-key <value>",
      "Backend API key or interpolation template such as ${AGENTIC_MEMORY_API_KEY}",
    )
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--mode <mode>", "Requested plugin mode: capture_only or augment_context")
    .option("--enable-context-augmentation", "Check readiness for augment_context mode", false)
    .option("--disable-context-augmentation", "Check readiness for capture_only mode", false)
    .option("--enable-context-engine", "Legacy alias for --enable-context-augmentation", false)
    .option("--disable-context-engine", "Legacy alias for --disable-context-augmentation", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: DoctorCommandOptions) => {
      await printDoctorResult(ctx, options);
    });

  const project = root.command("project").description("Manage the active Agentic Memory project");

  project
    .command("init <projectId>")
    .description("Create or activate a project for the current OpenClaw session")
    .option("--session-id <id>", "Optional session override. Usually inferred from the active OpenClaw session.")
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
    .option("--session-id <id>", "Optional session override. Usually inferred from the active OpenClaw session.")
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
    .option("--session-id <id>", "Optional session override. Usually inferred from the active OpenClaw session.")
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
    .option("--session-id <id>", "Optional session override. Usually inferred from the active OpenClaw session.")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: ProjectStopOptions) => {
      const config = resolveProjectCommandConfig(ctx.config, options);
      const client = new AgenticMemoryBackendClient(
        {
          schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
          ...config,
          projectId: null,
          contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
          mode: resolveExistingMode(ctx.config),
        },
        ctx.logger,
      );
      const response = await client.post("/openclaw/project/deactivate", {
        ...buildProjectRequestIdentity(config, options),
        metadata: { plugin: PLUGIN_ID },
      });
      printProjectPayload(
        {
          ok: true,
          action: "project_stop",
          sessionId: options.sessionId ?? extractResolvedSessionId(response),
          response,
        },
        options.json,
      );
    });

  project
    .command("status")
    .description("Show the active project for one OpenClaw session")
    .option("--session-id <id>", "Optional session override. Usually inferred from the active OpenClaw session.")
    .option("--workspace <id>", "Optional workspace override")
    .option("--workspace-id <id>", "Legacy alias for --workspace")
    .option("--device-id <id>", "Device identifier")
    .option("--agent-id <id>", "Agent identifier")
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: ProjectStopOptions) => {
      const config = resolveProjectCommandConfig(ctx.config, options);
      const client = new AgenticMemoryBackendClient(
        {
          schemaVersion: PLUGIN_CONFIG_SCHEMA_VERSION,
          ...config,
          projectId: null,
          contextEngineId: DEFAULT_CONTEXT_ENGINE_ID,
          mode: resolveExistingMode(ctx.config),
        },
        ctx.logger,
      );
      const response = await client.post("/openclaw/project/status", {
        ...buildProjectRequestIdentity(config, options),
        metadata: { plugin: PLUGIN_ID },
      });
      printProjectPayload(
        {
          ok: true,
          action: "project_status",
          sessionId: options.sessionId ?? extractResolvedSessionId(response),
          response,
        },
        options.json,
      );
    });

  if (!isAgenticMemoryActiveMemoryPlugin(ctx.config)) {
    return;
  }

  const memory = ctx.program
    .command("memory")
    .description("Agentic Memory-backed memory status and search commands");

  memory
    .command("status")
    .description("Show Agentic Memory runtime status for the active OpenClaw memory plugin")
    .option("--agent <id>", "Override the configured agent id")
    .option("--deep", "Include backend readiness checks", false)
    .option("--json", "Print machine-readable JSON", false)
    .action(async (options: MemoryStatusCommandOptions) => {
      const existing = resolveExistingPluginConfig(ctx.config);
      const resolved = resolveAgenticMemoryPluginConfig(
        {
          ...existing,
          ...(options.agent ? { agentId: options.agent } : {}),
        },
        options.agent,
      );
      const client = new AgenticMemoryBackendClient(resolved, ctx.logger);
      const manager = new AgenticMemorySearchManager(client, resolved);
      const status = manager.status();
      let doctor: Awaited<ReturnType<typeof runAgenticMemoryDoctor>> | null = null;

      if (options.deep) {
        doctor = await runAgenticMemoryDoctor(client, resolved);
      }

      const payload = {
        ok: true,
        provider: status.provider,
        backend: status.backend,
        custom: status.custom ?? {},
        deep: doctor
          ? {
              setupReady: doctor.contract.readiness.setup_ready,
              captureOnlyReady: doctor.contract.readiness.capture_only_ready,
              augmentContextReady: doctor.contract.readiness.augment_context_ready,
              blockingServices: doctor.contract.readiness.blocking_services,
            }
          : null,
      };

      if (options.json) {
        output.write(`${JSON.stringify(payload, null, 2)}\n`);
        return;
      }

      output.write("Agentic Memory memory status\n");
      output.write(`Provider: ${status.provider}\n`);
      output.write(`Backend: ${status.backend}\n`);
      output.write(`Backend URL: ${String(status.custom?.backendUrl ?? "unknown")}\n`);
      output.write(`Workspace: ${String(status.custom?.workspaceId ?? "unknown")}\n`);
      output.write(`Device: ${String(status.custom?.deviceId ?? "unknown")}\n`);
      output.write(`Agent: ${String(status.custom?.agentId ?? "unknown")}\n`);
      output.write(`Mode: ${String(status.custom?.mode ?? "unknown")}\n`);
      if (doctor) {
        output.write(`Setup ready: ${doctor.contract.readiness.setup_ready ? "yes" : "no"}\n`);
        output.write(
          `Capture-only ready: ${doctor.contract.readiness.capture_only_ready ? "yes" : "no"}\n`,
        );
        output.write(
          `Augment-context ready: ${doctor.contract.readiness.augment_context_ready ? "yes" : "no"}\n`,
        );
        if (doctor.contract.readiness.blocking_services.length > 0) {
          output.write(
            `Blocking services: ${doctor.contract.readiness.blocking_services.join(", ")}\n`,
          );
        }
      }
    });

  memory
    .command("search [query]")
    .description("Search Agentic Memory from the OpenClaw memory CLI surface")
    .option("--query <text>", "Explicit query text")
    .option("--agent <id>", "Override the configured agent id")
    .option("--max-results <n>", "Maximum results to return", (value: string) => Number(value))
    .option("--min-score <n>", "Minimum score threshold", (value: string) => Number(value))
    .option("--json", "Print machine-readable JSON", false)
    .action(async (queryArg: string | undefined, options: MemorySearchCommandOptions) => {
      const query = options.query?.trim() || queryArg?.trim();
      if (!query) {
        throw new Error("Provide a query either positionally or with --query.");
      }

      const existing = resolveExistingPluginConfig(ctx.config);
      const resolved = resolveAgenticMemoryPluginConfig(
        {
          ...existing,
          ...(options.agent ? { agentId: options.agent } : {}),
        },
        options.agent,
      );
      const client = new AgenticMemoryBackendClient(resolved, ctx.logger);
      const manager = new AgenticMemorySearchManager(client, resolved);
      const searchOptions: {
        maxResults?: number;
        minScore?: number;
      } = {};
      if (options.maxResults !== undefined) {
        searchOptions.maxResults = options.maxResults;
      }
      if (options.minScore !== undefined) {
        searchOptions.minScore = options.minScore;
      }
      const hits = await manager.search(query, searchOptions);

      if (options.json) {
        output.write(`${JSON.stringify({ ok: true, query, results: hits }, null, 2)}\n`);
        return;
      }

      if (hits.length === 0) {
        output.write(`No Agentic Memory hits found for "${query}".\n`);
        return;
      }

      output.write(`Agentic Memory results for "${query}"\n`);
      for (const [index, hit] of hits.entries()) {
        output.write(`${index + 1}. ${hit.path}\n`);
        output.write(`   score=${hit.score.toFixed(3)} source=${hit.source}\n`);
        if (hit.snippet) {
          output.write(`   ${hit.snippet}\n`);
        }
      }
    });
}
