# agentic-memory

Native OpenClaw plugin package for Agentic Memory.

This package now contains a real OpenClaw-native runtime surface:

- `openclaw.plugin.json` declares the plugin id `agentic-memory`
- `src/index.ts` registers:
  - the Agentic Memory shared-memory runtime
  - the optional `agentic-memory` context engine
  - the OpenClaw-native CLI command `openclaw agentic-memory setup`
- `package.json` exposes the native plugin entry through `openclaw.extensions`

## How OpenClaw Uses Agentic Memory

OpenClaw uses this package through two different host plugin surfaces that do
different jobs:

- `plugins.slots.memory = "agentic-memory"`
  - this is the actual memory runtime
  - OpenClaw uses it for memory search, canonical reads, and memory-facing
    status behavior
- `plugins.slots.contextEngine = "agentic-memory"`
  - this is currently the lifecycle hook surface we use to observe turns as
    they happen
  - in `capture_only` mode it does **not** add custom context to prompts
  - in `augment_context` mode it both captures turns and assembles custom
    context through the backend

That split matters because the product model is:

- memory owns capture, storage, retrieval, and canonical reads
- context augmentation is optional and sits downstream of memory

However, the current OpenClaw host lifecycle callbacks we need for turn capture
arrive through the context-engine interface. So this package still occupies the
OpenClaw `contextEngine` slot even when the user only wants memory capture.

In other words:

- `capture_only`
  - memory is on
  - context augmentation is off
  - the context-engine slot is still used under the hood as the turn-capture
    event tap
- `augment_context`
  - memory is on
  - context augmentation is on

This is a host-integration constraint, not the intended long-term conceptual
model.

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
  - `--device-id`
  - `--agent-id`
  - `--mode`
  - `--enable-context-augmentation`

Example:

```bash
openclaw agentic-memory setup
```

Normal setup no longer asks for workspace unless you explicitly override it.
Instead, Agentic Memory resolves workspace in this order:

- explicit `--workspace` / `--workspace-id`
- existing configured `workspaceId`
- a stable default derived from the resolved `agentId`

That keeps the default path focused on "memory just works" while still
allowing an operator to pin a different workspace when needed.

That command writes the plugin's live OpenClaw config under:

- `plugins.entries.agentic-memory.config`
- `plugins.slots.memory`
- `plugins.slots.contextEngine`

Project scoping is now a runtime concern, not a setup-time identity. After
setup, use:

```bash
openclaw agentic-memory project init <project-id> --session-id <session-id>
openclaw agentic-memory project use <project-id> --session-id <session-id>
openclaw agentic-memory project status --session-id <session-id>
openclaw agentic-memory project stop --session-id <session-id>
```

Command intent:

- `project init`
  - create or activate a project for the current session
- `project use`
  - switch the current session into an existing project
- `project start`
  - legacy alias retained for compatibility

The active project is resolved server-side for that specific
`workspace_id + agent_id + session_id` tuple, so one agent can work on a
project temporarily without tagging every future memory forever.

## What this package does today

- turns OpenClaw memory lookups into `POST /openclaw/memory/search`
- turns OpenClaw context assembly into `POST /openclaw/context/resolve`
- registers sessions through `POST /openclaw/session/register`
- writes new turns through `POST /openclaw/memory/ingest-turn`
- activates/deactivates per-session projects through:
  - `POST /openclaw/project/activate`
  - `POST /openclaw/project/deactivate`
  - `POST /openclaw/project/status`
  - `POST /openclaw/project/automation`

## Important current limitation

The runtime is backend-first and intentionally conservative:

- memory search is real
- conversation ingestion is real
- canonical `readFile()` is now real for conversation-turn hits
- context resolution is real only when the plugin runs in `augment_context`
  mode
- non-conversation hits still fall back to the cached snippet from search

That means the next hardening step is to expand canonical read support beyond
conversation turns so code and research hits can also be re-opened without
depending on the cached search snippet.
