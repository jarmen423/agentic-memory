# am-openclaw

Native OpenClaw plugin package for Agentic Memory.

This package now contains a real OpenClaw-native runtime surface:

- `openclaw.plugin.json` declares the plugin id `agentic-memory`
- `src/index.ts` registers:
  - the Agentic Memory shared-memory runtime
  - the optional `agentic-memory` context engine
- `package.json` exposes the native plugin entry through `openclaw.extensions`

## What this package does today

- turns OpenClaw memory lookups into `POST /openclaw/memory/search`
- turns OpenClaw context assembly into `POST /openclaw/context/resolve`
- registers sessions through `POST /openclaw/session/register`
- writes new turns back through `POST /ingest/conversation` with `source_key = chat_openclaw`

## Important current limitation

The runtime is backend-first and intentionally conservative:

- memory search is real
- context resolution is real
- conversation ingestion is real
- canonical `readFile()` is now real for conversation-turn hits
- non-conversation hits still fall back to the cached snippet from search

That means the next hardening step is to expand canonical read support beyond
conversation turns so code and research hits can also be re-opened without
depending on the cached search snippet.
