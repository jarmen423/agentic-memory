/**
 * OpenClaw package surface for Agentic Memory.
 *
 * This file intentionally stays small. It gives the future plugin package a
 * typed home for shared configuration objects before the runtime wiring lands.
 */

/**
 * Identity values that tie one OpenClaw workspace to one device and one agent.
 */
export interface OpenClawIdentity {
  workspaceId: string;
  deviceId: string;
  agentId: string;
}

/**
 * Options used by the next-wave bootstrap command when it generates OpenClaw
 * configuration for a user.
 */
export interface OpenClawBootstrapOptions extends OpenClawIdentity {
  backendUrl: string;
  backendApiKey?: string | null;
  enableContextEngine?: boolean;
}

/**
 * Human-readable package metadata that can be displayed by installers and
 * setup flows.
 */
export const OPENCLAW_PACKAGE_INFO = {
  packageName: "am-openclaw",
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
 * Build the JSON payload the future setup command can write into a local config
 * file or send to a backend bootstrap endpoint.
 */
export function buildOpenClawBootstrapConfig(options: OpenClawBootstrapOptions) {
  const identity = normalizeOpenClawIdentity(options);

  return {
    ...identity,
    backendUrl: options.backendUrl.trim(),
    backendApiKey: options.backendApiKey?.trim() || null,
    enableContextEngine: options.enableContextEngine ?? false,
    packageName: OPENCLAW_PACKAGE_INFO.packageName,
    mode: options.enableContextEngine ? "context-engine" : "memory",
  } as const;
}
