import assert from "node:assert/strict";
import test from "node:test";

import { createAgenticMemoryTools } from "../src/tools.js";

function createContext() {
  return {
    agentId: "runtime-agent",
    sessionId: "session-123",
    workspaceDir: "D:\\code\\agentic-memory",
  };
}

function createPluginConfig() {
  return {
    backendUrl: "http://127.0.0.1:8765",
    apiKey: "test-key",
    workspaceId: "workspace-1",
    deviceId: "device-1",
    agentId: "config-agent",
    mode: "augment_context",
  };
}

test("tool bridge exposes the expected Agentic Memory tool names", () => {
  const tools = createAgenticMemoryTools(createContext(), createPluginConfig());

  assert.deepEqual(
    tools.map((tool) => tool.name),
    [
      "search_codebase",
      "get_file_dependencies",
      "trace_execution_path",
      "search_all_memory",
      "search_conversations",
      "get_conversation_context",
    ],
  );
});

test("search_all_memory tool reuses the OpenClaw memory search route with runtime session identity", async () => {
  const tools = createAgenticMemoryTools(createContext(), createPluginConfig());
  const tool = tools.find((entry) => entry.name === "search_all_memory");
  assert.ok(tool);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://127.0.0.1:8765/openclaw/memory/search");
    assert.equal(init?.method, "POST");
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    assert.equal(body.workspace_id, "workspace-1");
    assert.equal(body.device_id, "device-1");
    assert.equal(body.agent_id, "runtime-agent");
    assert.equal(body.session_id, "session-123");
    assert.equal(body.query, "where is the graph code?");

    return new Response(
      JSON.stringify({
        results: [
          {
            path: "src/agentic_memory/server/app.py",
            score: 0.92,
            snippet: "def search_codebase(",
          },
        ],
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  };

  try {
    const response = await tool.execute("call-1", {
      query: "where is the graph code?",
    });
    const text = response.content[0]?.text ?? "";
    assert.match(text, /Agentic Memory Search/);
    assert.match(text, /src\/agentic_memory\/server\/app\.py/);
    assert.match(text, /def search_codebase/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("get_conversation_context tool calls the dedicated OpenClaw tool route", async () => {
  const tools = createAgenticMemoryTools(createContext(), createPluginConfig());
  const tool = tools.find((entry) => entry.name === "get_conversation_context");
  assert.ok(tool);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8765/openclaw/tools/get-conversation-context",
    );
    assert.equal(init?.method, "POST");
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    assert.equal(body.session_id, "session-123");
    assert.equal(body.agent_id, "runtime-agent");
    assert.equal(body.query, "what did we decide?");
    assert.equal(body.project_id, "project-1");

    return new Response(
      JSON.stringify({
        status: "ok",
        text: "## Conversation Context\n\nDecision recap",
        payload: {
          query: "what did we decide?",
          project_id: "project-1",
          turns: [],
        },
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  };

  try {
    const response = await tool.execute("call-2", {
      query: "what did we decide?",
      project_id: "project-1",
    });
    assert.equal(response.content[0]?.text, "## Conversation Context\n\nDecision recap");
    assert.deepEqual(response.structuredContent, {
      query: "what did we decide?",
      project_id: "project-1",
      turns: [],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
