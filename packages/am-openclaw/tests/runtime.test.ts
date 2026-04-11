import assert from "node:assert/strict";
import test from "node:test";

import {
  AgenticMemoryContextEngine,
  AgenticMemorySearchManager,
} from "../src/runtime.js";
import { resolveAgenticMemoryPluginConfig } from "../src/shared.js";

function createConfig(mode: "capture_only" | "augment_context" = "capture_only") {
  return resolveAgenticMemoryPluginConfig(
    {
      backendUrl: "http://127.0.0.1:8765",
      apiKey: "test-key",
      workspaceId: "workspace-1",
      deviceId: "device-1",
      agentId: "agent-1",
      mode,
    },
    "agent-1",
  );
}

test("search manager falls back to the cached snippet when canonical read fails", async () => {
  let callCount = 0;
  const client = {
    async post(path: string) {
      callCount += 1;
      if (path === "/openclaw/memory/search") {
        return {
          results: [
            {
              path: "session-1:4",
              score: 0.9,
              snippet: "cached snippet",
              start_line: 5,
              end_line: 5,
              module: "conversation",
            },
          ],
        };
      }

      throw new Error("canonical read unsupported");
    },
  };

  const manager = new AgenticMemorySearchManager(client as never, createConfig());
  const hits = await manager.search("where did we leave off?");
  const document = await manager.readFile({ relPath: hits[0]?.path ?? "missing" });

  assert.equal(callCount, 2);
  assert.equal(hits[0]?.snippet, "cached snippet");
  assert.equal(document.text, "cached snippet");
});

test("context engine returns original messages in capture_only mode", async () => {
  const engine = new AgenticMemoryContextEngine({ post: async () => ({}) } as never, createConfig());
  const messages = [{ role: "user", content: "hello" }];

  const assembled = await engine.assemble({
    sessionId: "session-1",
    messages: messages as never,
  });

  assert.deepEqual(assembled.messages, messages);
  assert.equal(assembled.estimatedTokens, 0);
});

test("context engine prepends system memory context in augment_context mode", async () => {
  const engine = new AgenticMemoryContextEngine(
    {
      async post() {
        return {
          context_blocks: [
            {
              title: "Relevant memory",
              source: "conversation",
              content: "Remember the shared workspace note.",
            },
          ],
          system_prompt_addition: "Use shared memory first.",
        };
      },
    } as never,
    createConfig("augment_context"),
  );
  const messages = [{ role: "user", content: "hello" }];

  const assembled = await engine.assemble({
    sessionId: "session-1",
    messages: messages as never,
  });

  assert.equal(assembled.messages[0]?.role, "system");
  assert.match(String(assembled.messages[0]?.content), /Shared Agentic Memory context/);
  assert.equal(assembled.systemPromptAddition, "Use shared memory first.");
  assert.ok(assembled.estimatedTokens > 0);
});
