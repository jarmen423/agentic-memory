# OpenClaw Dreaming Compatibility

## Status

- Deferred follow-up plan.
- Captured on 2026-04-19 while investigating the Agentic Memory OpenClaw plugin.
- Not part of the current implementation wave. The current wave is focused on:
  - restoring `openclaw memory ...` compatibility for the custom memory plugin
  - exposing Agentic Memory search/codebase tools inside OpenClaw sessions

## Why This Exists

OpenClaw is pushing Dreaming as a core part of its memory story. Agentic Memory
already has pieces that can support a strong Dreaming implementation:

- temporal retrieval and time-aware ranking
- project/session aware memory state
- graph-backed search and relationship analysis
- a backend that can own scheduled and asynchronous work

What Agentic Memory does **not** currently provide is a Dreaming feature that
matches OpenClaw's current expectations around:

- Dreaming status and control surfaces
- REM and deep promotion flows
- diary/report style outputs
- compatibility with `openclaw memory promote`, `promote-explain`, and
  `rem-harness`

## Product Direction

Implement Dreaming as a first-class Agentic Memory backend capability instead
of trying to mimic `memory-core`'s private file layout.

That means:

- Agentic Memory backend owns Dreaming state and scheduling
- the OpenClaw plugin exposes Dreaming as plugin/runtime/tool surfaces
- OpenClaw host should consume Dreaming from the **active memory plugin**
  instead of assuming `memory-core`

## Proposed Scope

### Backend

- Add a Dreaming service with phase execution:
  - light
  - REM
  - deep
- Reuse temporal features for ranking and reinforcement:
  - temporal recurrence
  - recency
  - cross-session/query reinforcement
- Add offline graph algorithms for deeper consolidation:
  - theme clustering
  - co-occurrence grouping
  - centrality/ranking passes for durable promotion candidates
- Persist Dreaming state in backend-native storage rather than local
  `memory-core` markdown files.

### Plugin

- Add Dreaming config under
  `plugins.entries.agentic-memory.config.dreaming`
- Add plugin-owned CLI surfaces:
  - `openclaw agentic-memory dreaming status`
  - `openclaw agentic-memory dreaming on`
  - `openclaw agentic-memory dreaming off`
  - `openclaw agentic-memory dreaming run`
  - `openclaw agentic-memory promote`
  - `openclaw agentic-memory promote-explain`
  - `openclaw agentic-memory rem-harness`
- Export Dreaming-related public artifacts once the backend has stable outputs.

### Host Compatibility

- OpenClaw should route Dreaming-related `openclaw memory ...` surfaces through
  the active memory plugin instead of hardcoding `memory-core`.
- Dreaming UI/doctor flows should be gated by active-plugin capability support.

## Suggested Implementation Order

1. Finish the current OpenClaw plugin integration wave:
   - tool bridge
   - `memory` CLI compatibility shim
   - backend bridge routes
2. Add Dreaming backend contracts and state model.
3. Add plugin-owned Dreaming CLI and status surface.
4. Add public artifacts for bridge/companion consumers.
5. Patch OpenClaw host expectations upstream if needed.

## Acceptance Criteria For A Future Wave

- Agentic Memory can report Dreaming status for an OpenClaw workspace/agent.
- Agentic Memory can run a manual Dreaming sweep and return structured results.
- Deep phase can auto-promote durable memory candidates.
- OpenClaw can expose Dreaming controls without depending on `memory-core`.
- Dreaming-derived outputs become searchable through Agentic Memory retrieval.

## Explicitly Deferred For Now

- Grounded historical replay and rollback compatibility with
  `memory-core`-style file workflows
- Full `DREAMS.md` / local vault file emulation
- Any host patch outside this repository
