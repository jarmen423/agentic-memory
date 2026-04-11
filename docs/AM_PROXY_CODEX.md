# am-proxy and OpenAI Codex

This note aligns **Agentic Memory `am-proxy`** with the **OpenAI Codex CLI** as shipped from [openai/codex](https://github.com/openai/codex).

## Why not `--acp`?

Older internal sketches referred to a hypothetical `--acp` flag. The current Codex CLI does **not** expose that. For stdio-based integrations, Codex provides subcommands such as:

- **`codex app-server`** — Codex **App Server** protocol (JSON-RPC over newline-delimited JSON, default transport includes stdio).
- **`codex mcp-server`** — Codex as an **MCP** server (different wire format than App Server).

`am-proxy` defaults the **child process** to `app-server` when `--agent codex` is used and you do not pass further argv, so the proxy does not spawn the interactive TUI (which expects a real TTY and fails with “stdin is not a terminal” when stdin is a pipe).

## Passive ingest mapping

The proxy’s legacy path routes **ACP**-style methods (`threads/message`, `threads/update`, …).

For **Codex App Server**, `packages/am-proxy` additionally routes methods such as:

| Direction | Methods (examples) | Ingest role |
|-----------|-------------------|-------------|
| Client → Codex (stdin) | `turn/start`, `turn/steer` | `user` |
| Codex → Client (stdout) | `item/completed` (non-tool items) | `assistant` |
| Either | `thread/started` | Resets per-thread turn counter |

Exact JSON shapes evolve with Codex; helpers use defensive field extraction. See the [Codex App Server documentation](https://developers.openai.com/codex/app-server/).

## Configuration

Point **`am-proxy`** at your **`am-server`** base URL and bearer token (same secret as **`AM_SERVER_API_KEY`**). Default base URL in `am-proxy` is **`http://127.0.0.1:8765`** to match `am_server`’s default listen port.

## “It hangs” in a terminal

`am-proxy` **blocks on stdin** waiting for newline-delimited JSON-RPC from a **client** (usually the IDE). Running it alone in PowerShell or bash is not interactive: configure your editor to launch `am-proxy` as the Codex/agent command, or pipe a client process to stdin. On a TTY, `am-proxy` prints a short hint to **stderr** explaining this.

## Terminal Codex vs IDE Codex vs OpenClaw

Three different integration paths exist; pick the one that matches how you run the agent:

| Surface | Mechanism | Package / notes |
|--------|-----------|-----------------|
| **OpenClaw** | Native plugin hooks → `POST /openclaw/memory/ingest-turn` | [`packages/am-openclaw`](../packages/am-openclaw) — in-process; feels “background” once configured |
| **Codex in the IDE** | `codex app-server` JSON-RPC on stdio → proxy tees turns → `POST /ingest/conversation` | **`am-proxy`** (this doc) — requires an IDE/client speaking App Server on stdin |
| **Codex in a terminal (TUI)** | No stdio hook for our proxy; Codex writes **rollout JSONL** under `~/.codex/sessions` | **`am-codex-watch`** — [`packages/am-codex-watch`](../packages/am-codex-watch) tails those files and POSTs to `/ingest/conversation` with `source_key=chat_codex_rollout` |

Rollout file format is summarized in [CODEX_ROLLOUT_JSONL.md](CODEX_ROLLOUT_JSONL.md). The watcher uses a pluggable **session artifact adapter** registry so additional CLIs can be added without duplicating tail/HTTP logic; see [SESSION_ARTIFACT_ADAPTERS.md](SESSION_ARTIFACT_ADAPTERS.md).

## Related

- [SETUP_FULL_STACK.md](SETUP_FULL_STACK.md) — local stack including `am-server`
- [MCP_INTEGRATION.md](MCP_INTEGRATION.md) — MCP tools vs passive proxy ingest (different surfaces)
- [CODEX_ROLLOUT_JSONL.md](CODEX_ROLLOUT_JSONL.md) — Codex session JSONL schema (for `am-codex-watch`)
