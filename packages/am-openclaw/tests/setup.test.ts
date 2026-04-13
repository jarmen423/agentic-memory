import assert from "node:assert/strict";
import test from "node:test";

import { OPENCLAW_PACKAGE_INFO } from "../src/shared.js";
import { mergeAgenticMemoryPluginConfigIntoOpenClawConfig } from "../src/setup.js";

test("setup config merge enables the plugin and fills both OpenClaw slots", () => {
  const next = mergeAgenticMemoryPluginConfigIntoOpenClawConfig(
    {
      plugins: {
        entries: {
          existing: { enabled: true, config: { answer: 42 } },
        },
        slots: {
          memory: "existing-memory",
        },
      },
    },
    {
      backendKind: "self_hosted",
      backendUrl: "http://127.0.0.1:8765",
      apiKey: "${AGENTIC_MEMORY_API_KEY}",
      workspaceId: "workspace-1",
      deviceId: "device-1",
      agentId: "agent-1",
      projectId: null,
      mode: "augment_context",
    },
  );

  const pluginEntry = (next.plugins as Record<string, unknown>).entries as Record<string, unknown>;
  const slots = (next.plugins as Record<string, unknown>).slots as Record<string, unknown>;
  const agenticMemory = pluginEntry["agentic-memory"] as Record<string, unknown>;
  const config = agenticMemory.config as Record<string, unknown>;

  assert.equal(agenticMemory.enabled, true);
  assert.equal(config.schemaVersion, 1);
  assert.equal(config.backendKind, "self_hosted");
  assert.equal(config.backendUrl, "http://127.0.0.1:8765");
  assert.equal(config.workspaceId, "workspace-1");
  assert.equal(config.deviceId, "device-1");
  assert.equal(config.agentId, "agent-1");
  assert.equal(config.mode, "augment_context");
  assert.equal(slots.memory, "agentic-memory");
  assert.equal(slots.contextEngine, "agentic-memory");
  assert.ok(pluginEntry["existing"]);
});

test("package metadata keeps npm install identity separate from the plugin id", () => {
  assert.equal(OPENCLAW_PACKAGE_INFO.packageName, "agentic-memory-openclaw");
  assert.equal(OPENCLAW_PACKAGE_INFO.pluginId, "agentic-memory");
  assert.equal(OPENCLAW_PACKAGE_INFO.contextEngineId, "agentic-memory");
});
