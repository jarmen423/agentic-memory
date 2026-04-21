import assert from "node:assert/strict";
import test from "node:test";

import { formatDoctorText, validateSetupAgainstContract } from "../src/doctor.js";
import { type BackendOnboardingContract, resolveAgenticMemoryPluginConfig } from "../src/shared.js";

function createContract(
  overrides: Partial<BackendOnboardingContract> = {},
): BackendOnboardingContract {
  return {
    status: "ok",
    deployment_mode: "self_hosted",
    supported_deployment_modes: ["managed", "self_hosted"],
    auth_strategy: "shared_api_key",
    provider_key_mode: "operator_managed",
    hosted_base_url: null,
    plugin_package_name: "agentic-memory-openclaw",
    plugin_id: "agentic-memory",
    install_command: "openclaw plugin install agentic-memory-openclaw",
    setup_command: "openclaw agentic-memory setup",
    doctor_command: "openclaw agentic-memory doctor",
    required_services: [
      {
        service_id: "backend_http",
        label: "Agentic Memory backend HTTP API",
        required: true,
        status: "healthy",
        summary: "Backend is reachable.",
      },
      {
        service_id: "api_auth",
        label: "Backend API authentication",
        required: true,
        status: "healthy",
        summary: "Backend API auth is configured.",
      },
      {
        service_id: "openclaw_memory",
        label: "OpenClaw memory capture pipeline",
        required: true,
        status: "healthy",
        summary: "Memory pipeline is healthy.",
      },
    ],
    optional_services: [
      {
        service_id: "openclaw_context_engine",
        label: "OpenClaw context engine",
        required: false,
        status: "healthy",
        summary: "Context engine is healthy.",
      },
    ],
    readiness: {
      setup_ready: true,
      capture_only_ready: true,
      augment_context_ready: true,
      required_healthy: 3,
      required_total: 3,
      optional_healthy: 1,
      optional_total: 1,
      blocking_services: [],
      degraded_optional_services: [],
    },
    notes: [],
    ...overrides,
  };
}

test("doctor validation accepts capture_only when required services are healthy", () => {
  const config = resolveAgenticMemoryPluginConfig(
    {
      backendUrl: "http://127.0.0.1:8765",
      apiKey: "test-key",
      workspaceId: "workspace-1",
      deviceId: "device-1",
      agentId: "agent-1",
      mode: "capture_only",
    },
    "agent-1",
  );

  const result = validateSetupAgainstContract(config, createContract());

  assert.equal(result.ok, true);
  assert.deepEqual(result.blockingReasons, []);
});

test("doctor validation blocks augment_context when context engine is not ready", () => {
  const config = resolveAgenticMemoryPluginConfig(
    {
      backendUrl: "http://127.0.0.1:8765",
      apiKey: "test-key",
      workspaceId: "workspace-1",
      deviceId: "device-1",
      agentId: "agent-1",
      mode: "augment_context",
    },
    "agent-1",
  );

  const result = validateSetupAgainstContract(
    config,
    createContract({
      optional_services: [
        {
          service_id: "openclaw_context_engine",
          label: "OpenClaw context engine",
          required: false,
          status: "degraded",
          summary: "Context engine warmup failed.",
        },
      ],
      readiness: {
        setup_ready: true,
        capture_only_ready: true,
        augment_context_ready: false,
        required_healthy: 3,
        required_total: 3,
        optional_healthy: 0,
        optional_total: 1,
        blocking_services: [],
        degraded_optional_services: ["openclaw_context_engine"],
      },
    }),
  );

  assert.equal(result.ok, false);
  assert.match(result.blockingReasons[0] ?? "", /OpenClaw context engine/);
});

test("doctor formatting includes blocking reasons for failed readiness", () => {
  const text = formatDoctorText({
    ok: false,
    backendUrl: "http://127.0.0.1:8765",
    backendKind: "self_hosted",
    mode: "capture_only",
    contract: createContract({
      readiness: {
        setup_ready: false,
        capture_only_ready: false,
        augment_context_ready: false,
        required_healthy: 1,
        required_total: 3,
        optional_healthy: 1,
        optional_total: 1,
        blocking_services: ["api_auth", "openclaw_memory"],
        degraded_optional_services: [],
      },
    }),
    localWarnings: [],
    blockingReasons: [
      "Backend API authentication [api_auth] is missing_config: Backend API auth is configured.",
    ],
    suggestedNextCommand: "openclaw agentic-memory doctor",
  });

  assert.match(text, /Setup ready: no/);
  assert.match(text, /Blocking reasons:/);
  assert.match(text, /api_auth/);
});
