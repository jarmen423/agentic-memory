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
- `readFile()` is still cache-backed because the backend does not yet expose a
  dedicated OpenClaw memory-read endpoint

That means the next hardening step is to add a backend read contract so the
runtime can serve canonical file/note reads instead of only cached snippets from
recent search results.
