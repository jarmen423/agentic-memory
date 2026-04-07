# OpenClaw Magic Integration Plan

## Summary

- Build a first-class OpenClaw package that ships both:
  - an `Agentic Memory` native memory plugin
  - an optional `Agentic Memory` context-engine plugin
- Default product behavior:
  - memory plugin `on`
  - context engine `off` by default
  - docs and setup position context-engine mode as an upgrade path when users do not already prefer another engine
- Shared memory scope is `per user workspace`, not per device. Devices can connect however they want; the backend treats them as one memory workspace with device-aware metadata.
- Keep all existing integrations intact. OpenClaw is an additive package and onboarding path, not a replacement for MCP, extension, proxy, or desktop-shell surfaces.
- This plan assumes OpenClaw’s current plugin model with separate `memory` and `contextEngine` slots and a built-in `legacy` context engine. Sources: [Plugins](https://docs.openclaw.ai/plugins), [Context Engine](https://docs.openclaw.ai/context-engine), [Context](https://docs.openclaw.ai/context/).

## Progress Snapshot

### Status as of 2026-04-07

- `Implemented`
  - OpenClaw backend routes and shared-memory identity contract
  - `chat_openclaw` conversation source plumbing
  - cross-device OpenClaw stress harness and tests
  - desktop shell OpenClaw setup/verify flow against real `/openclaw/*` routes
  - Python setup command: `agentic-memory openclaw-setup`
  - native `packages/am-openclaw/` runtime package with real memory/context wiring
- `In progress`
  - live host validation inside a real OpenClaw install
  - backend support for canonical memory reads instead of cache-backed snippet reads
- `Not started`
  - performance/failure benchmarking beyond targeted tests

### Implemented Commits

- `7a2b692` `feat: add openclaw shared memory wave`
  - added backend routes, identity fields, source registration, and OpenClaw stress tests
- `d558e4e` `feat: add openclaw setup shell and package scaffold`
  - added shell proxy routes, `openclaw-setup`, and the initial `am-openclaw` workspace package
- `pending in worktree`
  - real `am-openclaw` runtime implementation, native plugin manifest, and OpenClaw-native setup config output

### Where Progress Has Been Tracked

- This plan file:
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\docs\PLAN-openclaw-integration.md`
- Commit history:
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory` via `git log --oneline`
- The implementation surface itself:
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\src\am_server\routes\openclaw.py`
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\src\agentic_memory\cli.py`
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\desktop_shell\app.py`
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\packages\am-openclaw\src\index.ts`

## Key Changes

### 1. OpenClaw package

- Add a new package: `packages/am-openclaw/`
- `Status`
  - `Done:` package scaffold, workspace registration, native plugin manifest, README, typed bootstrap/config surface, real memory runtime, optional context-engine runtime
  - `Next:` validate against a live OpenClaw host install and close remaining read-path gaps
- Ship three deliverables from that package:
  - `memory` plugin for retrieval and memory persistence
  - `context-engine` plugin for assembly/compaction integration
  - `setup` CLI for “magic install” and config wiring
- Plugin package behavior:
  - installs as a normal OpenClaw plugin package
  - registers both plugin kinds in one package
  - exposes config flags so users can enable memory only or memory + context engine without reinstalling
- Default generated OpenClaw config:
  - `plugins.slots.memory = "agentic-memory"`
  - `plugins.slots.contextEngine` remains `legacy`
  - plugin entry includes backend URL, API key, workspace ID, device ID, and optional project mapping

### 2. Backend/API additions

- Extend conversation ingest to support OpenClaw as a first-class source:
  - add `chat_openclaw` source key
- Extend conversation ingest/search payloads to carry shared-workspace identity:
  - `workspace_id`
  - `device_id`
  - `agent_id`
  - optional `project_id` remains supported
- Add OpenClaw-specific API routes in `am-server`:
  - `POST /openclaw/memory/search`
    - input: query, workspace_id, device_id, agent_id, optional project_id, session_id, limit
    - output: ranked memory hits with provenance
  - `POST /openclaw/context/resolve`
    - input: current turn, workspace_id, device_id, agent_id, session_id, optional project_id, token budget hints
    - output: ordered context blocks plus optional `system_prompt_addition`
  - `POST /openclaw/session/register`
    - records device/workspace/session metadata and updates product-state integration health
- Keep existing generic routes intact. OpenClaw routes are thin adapters over current search/ingest primitives.
- `Status`
  - `Done:` all items in this section are implemented
  - backend routes live at:
    - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\src\am_server\routes\openclaw.py`

### 3. Memory and context behavior

- Memory plugin behavior:
  - writes new turns to Agentic Memory using `chat_openclaw`
  - retrieves from shared workspace memory across devices
  - boosts same-project and same-session results, but never hides cross-device workspace memory
- Context-engine behavior:
  - uses Agentic Memory retrieval during `assemble`
  - returns ordered context blocks and optional prompt guidance
  - delegates compaction to OpenClaw runtime in v1 unless memory-specific compaction is clearly needed
- Shipping behavior:
  - package both plugins together
  - recommend users start in memory-only mode
  - allow one config switch to turn the Agentic Memory context engine on for evaluation
- `Status`
  - `Done:` backend context resolution contract and shared-memory search contract
  - `Done:` desktop shell and CLI can configure memory-only vs context-engine mode
  - `Done:` the native OpenClaw runtime now calls `/openclaw/session/register`, `/openclaw/memory/search`, `/openclaw/context/resolve`, and `/ingest/conversation`
  - `Partial:` `readFile()` is still cache-backed because the backend does not yet expose a dedicated OpenClaw memory-read endpoint

### 4. Product and onboarding

- Add a dedicated OpenClaw setup command on the Python side:
  - `agentic-memory openclaw-setup`
- That command should:
  - verify `am-server` reachability
  - generate or patch OpenClaw plugin config
  - register `openclaw_memory` and `openclaw_context_engine` integration records in product state
  - emit a single “next command” or “done” experience for power users
- Extend desktop shell with an OpenClaw integration card:
  - status for memory plugin
  - status for context engine
  - workspace/device diagnostics
  - copyable setup commands
- Instrument product events:
  - `openclaw_setup_started`
  - `openclaw_setup_completed`
  - `openclaw_memory_connected`
  - `openclaw_context_enabled`
  - `openclaw_cross_device_recall_verified`
- `Status`
  - `Done:`
    - shell OpenClaw setup card
    - shell verification flow hitting `/openclaw/context/resolve`
    - `agentic-memory openclaw-setup`
    - `openclaw_setup_completed` event recording
  - `Partial:`
    - setup currently writes a deterministic config artifact instead of patching a live OpenClaw install
  - `Next:`
    - package-driven install that consumes the generated config and executes the real plugin flow

## Test Plan

### 1. Functional plugin tests

- Memory plugin can install, register, and retrieve memory from `am-server`
- Context-engine plugin can install and resolve context while `legacy` remains available as fallback config
- Setup command produces valid OpenClaw config for:
  - memory-only
  - memory + context engine
- `Status`
  - `Done:` setup command config generation test coverage
  - `Done:` native plugin package build/typecheck passes
  - `Partial:` runtime code exists and is wired to the backend, but host-installed end-to-end plugin tests are still missing

### 2. Cross-device hardening tests

- Simulate one workspace across at least:
  - 2 devices
  - 3 agents/sessions
- Verify:
  - memory written on device A is retrievable on device B
  - project-local recall beats unrelated workspace recall
  - same-session recall beats older cross-device recall when both are relevant
  - device metadata is preserved in provenance/debug output
- `Status`
  - `Done:` simulated workspace/device/agent harness and shared-memory tests
  - test files:
    - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\tests\openclaw_harness.py`
    - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\tests\test_openclaw_shared_memory.py`

### 3. Performance and failure scenarios

- Compare `memory only` vs `memory + context engine` on:
  - retrieval usefulness
  - latency
  - token impact
  - failure behavior under missing backend or API auth
- Validate context-engine safety:
  - if Agentic Memory context engine is selected but backend is unhealthy, diagnostics are explicit
  - setup docs tell users how to switch back to `legacy`
- `Status`
  - `Partial:` shell proxy layer now translates unreachable backend errors cleanly
  - `Not done:` formal latency/token/failure comparison matrix

### 4. Regression checks

- No regressions to:
  - MCP tool flow
  - browser extension ingestion
  - proxy ingestion
  - desktop shell product-status flow
- Existing chat ingest/search tests gain OpenClaw source coverage without changing old source behavior.
- `Status`
  - `Done:` OpenClaw source coverage added to conversation pipeline tests
  - `Done:` focused regression runs passed for product state, shell, API, and conversation pipeline

## Assumptions and Defaults

- OpenClaw integration is additive and must not weaken existing integrations.
- Shared memory identity is `workspace_id`; `device_id` is diagnostic/ranking metadata, not the ownership boundary.
- v1 context-engine mode is shipped in the same package, but not enabled by default.
- v1 compaction remains runtime-delegated unless implementation proves that custom compaction is required for acceptable results.
- GTM positioning is:
  - “best memory layer for OpenClaw power users”
  - “context-engine support included if you want deeper integration”

## Next Wave

- Validate the runtime package inside a real OpenClaw host install:
  - `C:\Users\jfrie\Documents\DEVDRIVE\code\agentic-memory\packages\am-openclaw\src\index.ts`
- Highest-value follow-up:
  - add a backend read contract so the plugin can serve canonical `readFile()` results
  - add host-level install and runtime tests instead of relying only on package build/typecheck
  - benchmark `memory only` vs `memory + context engine` latency and usefulness
- Keep the default shipping posture:
  - memory plugin on
  - context engine optional
