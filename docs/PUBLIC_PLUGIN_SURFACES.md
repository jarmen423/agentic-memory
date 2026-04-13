# Public Plugin Surfaces

Agentic Memory publishes one hosted remote-MCP backend behind multiple platform-facing surfaces. The public story is not "install a plugin directly from this repo"; it is:

- OpenAI / ChatGPT: submit and publish an OpenAI app
- Codex: derive distribution from the approved OpenAI app, using the local Codex package scaffold as a preflight artifact
- Claude: submit the hosted connector through Anthropic's directory flow

## Public strategy

- Shared hosted MCP backend through `am-server`
- Public/plugin surfaces mounted at:
  - `/mcp`
  - `/mcp-openai`
  - `/mcp-codex`
  - `/mcp-claude`
- Internal/self-hosted full surface mounted at:
  - `/mcp-full`

The public surfaces use the same bounded tool set so OpenAI Apps, Codex, and Claude can share one backend contract.

## Public tool set

The hosted public MCP surfaces expose:

- `search_codebase`
- `get_file_dependencies`
- `trace_execution_path`
- `search_all_memory`
- `search_web_memory`
- `memory_ingest_research`
- `search_conversations`
- `get_conversation_context`
- `add_message`

These are intentionally user-facing memory tools. The public surfaces do **not** expose local/admin operations such as indexing, watching, or repo maintenance.

## Auth model

`am-server` distinguishes between three bearer-token surfaces:

- REST API:
  - `AM_SERVER_API_KEYS`
  - `AM_SERVER_API_KEY`
- Public MCP:
  - `AM_SERVER_PUBLIC_MCP_API_KEYS`
  - `AM_SERVER_PUBLIC_MCP_API_KEY`
- Internal/full MCP:
  - `AM_SERVER_INTERNAL_MCP_API_KEYS`
  - `AM_SERVER_INTERNAL_MCP_API_KEY`

Hosted publication should use dedicated MCP credentials. Local deployments may fall back to the REST API key, but `AM_SERVER_STRICT_MCP_AUTH=1` disables that fallback for public MCP surfaces.

## Transport

The hosted MCP mounts use streamable HTTP by default. Compatibility SSE mounts remain available under:

- `/mcp/sse`
- `/mcp-sse`
- `/mcp-full/sse`

## Codex plugin packaging

This repo includes a Codex plugin package scaffold:

- `.codex-plugin/plugin.json`
- `.mcp.json`

The scaffold is for local validation and preflight packaging. Public Codex distribution still flows through the approved OpenAI app.

## Canonical publication URLs

The hosted publication/legal endpoints are:

- `https://api.agenticmemory.com/publication/agentic-memory`
- `https://api.agenticmemory.com/publication/privacy`
- `https://api.agenticmemory.com/publication/terms`
- `https://api.agenticmemory.com/publication/support`
- `https://api.agenticmemory.com/publication/dpa`

## Publication packets

- `docs/publication/openai`
- `docs/publication/anthropic`
- `docs/publication/shared`

## Platform intent

- OpenAI / ChatGPT:
  - use the hosted OpenAI-facing MCP surface at `/mcp-openai`
  - publish through OpenAI app review
- Codex:
  - use the hosted Codex-facing MCP surface at `/mcp-codex`
  - package locally with `.codex-plugin/plugin.json`
- Claude:
  - use the hosted Claude-facing MCP surface at `/mcp-claude`
  - submit through Anthropic's directory flow

All three surfaces currently share the same bounded public tool set. Platform-specific auth and submission metadata can be layered on top without forking the backend.
