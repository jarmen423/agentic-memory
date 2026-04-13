/**
 * Whole-stack doctor logic for the Agentic Memory OpenClaw plugin.
 *
 * The product problem in Phase 16 is not "can we write config?" It is
 * "can we honestly tell an operator this stack is usable right now?"
 *
 * This module keeps that answer separate from CLI wiring so both:
 *
 * - `openclaw agentic-memory doctor`
 * - `openclaw agentic-memory setup`
 *
 * can share the same backend contract parsing and readiness rules.
 */

import { AgenticMemoryBackendClient } from "./backend-client.js";
import {
  OPENCLAW_PACKAGE_INFO,
  type BackendOnboardingContract,
  type OnboardingServiceStatus,
  type ResolvedPluginConfig,
} from "./shared.js";

export interface DoctorReport {
  ok: boolean;
  backendUrl: string;
  backendKind: "hosted" | "self_hosted";
  mode: "capture_only" | "augment_context";
  contract: BackendOnboardingContract;
  localWarnings: string[];
  blockingReasons: string[];
  suggestedNextCommand: string;
}

export interface SetupValidationResult {
  ok: boolean;
  blockingReasons: string[];
  localWarnings: string[];
}

function summarizeService(service: OnboardingServiceStatus): string {
  return `${service.label} [${service.service_id}] is ${service.status}: ${service.summary}`;
}

function findService(
  contract: BackendOnboardingContract,
  serviceId: string,
): OnboardingServiceStatus | undefined {
  return [...contract.required_services, ...contract.optional_services].find(
    (service) => service.service_id === serviceId,
  );
}

function localConfigWarnings(config: ResolvedPluginConfig): string[] {
  const warnings: string[] = [];
  if (!config.apiKey?.trim()) {
    warnings.push(
      "The plugin config does not currently resolve an API key. Authenticated OpenClaw routes will fail after setup.",
    );
  }
  return warnings;
}

function backendModeWarnings(
  config: ResolvedPluginConfig,
  contract: BackendOnboardingContract,
): string[] {
  const warnings: string[] = [];
  const expectedKind = contract.deployment_mode === "managed" ? "hosted" : "self_hosted";
  if (config.backendKind !== expectedKind) {
    warnings.push(
      `The saved plugin backend mode is ${config.backendKind}, but the backend reports ${contract.deployment_mode}.`,
    );
  }
  return warnings;
}

function packageIdentityWarnings(contract: BackendOnboardingContract): string[] {
  const warnings: string[] = [];
  if (contract.plugin_package_name !== OPENCLAW_PACKAGE_INFO.packageName) {
    warnings.push(
      `Backend expects package ${contract.plugin_package_name}, but this build identifies itself as ${OPENCLAW_PACKAGE_INFO.packageName}.`,
    );
  }
  if (contract.plugin_id !== OPENCLAW_PACKAGE_INFO.pluginId) {
    warnings.push(
      `Backend expects plugin id ${contract.plugin_id}, but this build uses ${OPENCLAW_PACKAGE_INFO.pluginId}.`,
    );
  }
  return warnings;
}

/**
 * Decide whether a requested mode is honestly ready according to the backend.
 */
export function validateSetupAgainstContract(
  config: ResolvedPluginConfig,
  contract: BackendOnboardingContract,
): SetupValidationResult {
  const blockingReasons: string[] = [];
  const warnings = [
    ...localConfigWarnings(config),
    ...packageIdentityWarnings(contract),
    ...backendModeWarnings(config, contract),
  ];

  if (!contract.readiness.setup_ready) {
    for (const serviceId of contract.readiness.blocking_services) {
      const service = findService(contract, serviceId);
      blockingReasons.push(
        service ? summarizeService(service) : `Required onboarding service ${serviceId} is blocked.`,
      );
    }
  }

  if (config.mode === "capture_only" && !contract.readiness.capture_only_ready) {
    if (blockingReasons.length === 0) {
      blockingReasons.push(
        "Capture-only mode is not ready yet even though the backend returned no explicit blocking services.",
      );
    }
  }

  if (config.mode === "augment_context" && !contract.readiness.augment_context_ready) {
    const contextEngine = findService(contract, "openclaw_context_engine");
    blockingReasons.push(
      contextEngine
        ? summarizeService(contextEngine)
        : "Augment-context mode requires the OpenClaw context engine to be healthy.",
    );
  }

  return {
    ok: blockingReasons.length === 0,
    blockingReasons,
    localWarnings: warnings,
  };
}

/**
 * Fetch the backend onboarding contract and evaluate the requested plugin mode.
 */
export async function runAgenticMemoryDoctor(
  client: AgenticMemoryBackendClient,
  config: ResolvedPluginConfig,
): Promise<DoctorReport> {
  const contract = await client.get<BackendOnboardingContract>("/health/onboarding");
  const validation = validateSetupAgainstContract(config, contract);
  return {
    ok: validation.ok,
    backendUrl: config.backendUrl,
    backendKind: config.backendKind,
    mode: config.mode,
    contract,
    localWarnings: validation.localWarnings,
    blockingReasons: validation.blockingReasons,
    suggestedNextCommand: contract.doctor_command || "openclaw agentic-memory doctor",
  };
}

/**
 * Render a readable doctor report for terminal output.
 */
export function formatDoctorText(report: DoctorReport): string {
  const lines = [
    `Agentic Memory doctor for ${report.backendUrl}`,
    `Mode: ${report.mode}`,
    `Configured backend kind: ${report.backendKind === "hosted" ? "hosted" : "self-hosted"}`,
    `Backend deployment mode: ${report.contract.deployment_mode}`,
    `Backend auth strategy: ${report.contract.auth_strategy}`,
    `Provider key mode: ${report.contract.provider_key_mode}`,
    `Install command: ${report.contract.install_command}`,
    `Setup command: ${report.contract.setup_command}`,
    `Doctor command: ${report.contract.doctor_command}`,
    `Setup ready: ${report.contract.readiness.setup_ready ? "yes" : "no"}`,
    `Capture-only ready: ${report.contract.readiness.capture_only_ready ? "yes" : "no"}`,
    `Augment-context ready: ${report.contract.readiness.augment_context_ready ? "yes" : "no"}`,
    "",
    "Required services:",
    ...report.contract.required_services.map(
      (service) => `- ${service.label}: ${service.status}`,
    ),
    "",
    "Optional services:",
    ...report.contract.optional_services.map(
      (service) => `- ${service.label}: ${service.status}`,
    ),
  ];

  if (report.blockingReasons.length > 0) {
    lines.push("", "Blocking reasons:", ...report.blockingReasons.map((reason) => `- ${reason}`));
  }

  if (report.localWarnings.length > 0) {
    lines.push("", "Warnings:", ...report.localWarnings.map((warning) => `- ${warning}`));
  }

  if (report.contract.notes.length > 0) {
    lines.push("", "Backend notes:", ...report.contract.notes.map((note) => `- ${note}`));
  }

  return `${lines.join("\n")}\n`;
}
