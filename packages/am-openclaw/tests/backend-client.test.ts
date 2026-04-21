import assert from "node:assert/strict";
import test from "node:test";

import { AgenticMemoryBackendClient, AgenticMemoryBackendError } from "../src/backend-client.js";
import { resolveAgenticMemoryPluginConfig } from "../src/shared.js";

function createClient() {
  return new AgenticMemoryBackendClient(
    resolveAgenticMemoryPluginConfig(
      {
        backendUrl: "http://127.0.0.1:8765",
        apiKey: "test-key",
        workspaceId: "workspace-1",
        deviceId: "device-1",
        agentId: "agent-1",
      },
      "agent-1",
    ),
  );
}

test("backend client retries transient 503 responses and eventually succeeds", async () => {
  const client = createClient();
  const originalFetch = globalThis.fetch;
  let callCount = 0;

  globalThis.fetch = async () => {
    callCount += 1;
    if (callCount < 3) {
      return new Response(
        JSON.stringify({
          error: {
            code: "service_unavailable",
            message: "Temporary backend outage.",
            request_id: `req-${callCount}`,
            status: 503,
          },
        }),
        {
          status: 503,
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const response = await client.post<{ status: string }>("/openclaw/session/register", {
      session_id: "session-1",
    });

    assert.equal(response.status, "ok");
    assert.equal(callCount, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("backend client does not retry non-transient 404 responses", async () => {
  const client = createClient();
  const originalFetch = globalThis.fetch;
  let callCount = 0;

  globalThis.fetch = async () => {
    callCount += 1;
    return new Response(
      JSON.stringify({
        error: {
          code: "not_found",
          message: "Unsupported canonical path.",
          request_id: "req-404",
          status: 404,
        },
      }),
      {
        status: 404,
        headers: { "Content-Type": "application/json" },
      },
    );
  };

  try {
    await assert.rejects(
      client.post("/openclaw/memory/read", { rel_path: "missing" }),
      (error: unknown) => {
        assert.ok(error instanceof AgenticMemoryBackendError);
        assert.equal(error.status, 404);
        assert.equal(error.code, "not_found");
        assert.equal(error.requestId, "req-404");
        return true;
      },
    );
    assert.equal(callCount, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("backend client retries transient network failures", async () => {
  const client = createClient();
  const originalFetch = globalThis.fetch;
  let callCount = 0;

  globalThis.fetch = async () => {
    callCount += 1;
    if (callCount === 1) {
      throw new TypeError("fetch failed");
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const response = await client.post<{ ok: boolean }>("/openclaw/memory/search", {
      query: "memory",
    });

    assert.equal(response.ok, true);
    assert.equal(callCount, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("backend client supports doctor-style GET requests", async () => {
  const client = createClient();
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://127.0.0.1:8765/health/onboarding");
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const response = await client.get<{ status: string }>("/health/onboarding");
    assert.equal(response.status, "ok");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
