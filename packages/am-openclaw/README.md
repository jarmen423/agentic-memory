# am-openclaw

Native OpenClaw plugin package for Agentic Memory.

This package now contains a real OpenClaw-native runtime surface:

- `openclaw.plugin.json` declares the plugin id `agentic-memory`
- `src/index.ts` registers:
  - the Agentic Memory shared-memory runtime
  - the optional `agentic-memory` context engine
  - the OpenClaw-native CLI command `openclaw agentic-memory setup`
- `package.json` exposes the native plugin entry through `openclaw.extensions`

## Current setup flow

After installing the plugin into OpenClaw, configure it from the OpenClaw CLI:

```bash
openclaw agentic-memory setup
```

The setup command can run as:

- an interactive wizard when you omit flags
- a non-interactive command when you pass flags such as:
  - `--backend-url`
  - `--api-key`
  - `--workspace-id`
  - `--device-id`
  - `--agent-id`
  - `--project-id`
  - `--enable-context-engine`

That command writes the plugin's live OpenClaw config under:

- `plugins.entries.agentic-memory.config`
- `plugins.slots.memory`
- `plugins.slots.contextEngine`

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
