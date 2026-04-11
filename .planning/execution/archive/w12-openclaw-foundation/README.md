# Execution Registry

This directory is the active wave-execution registry for the current Phase 12
OpenClaw foundation work.

Why it exists:

- The OpenClaw GTM plan is the program/reference document, not the execution registry.
- The repo already had a live `w11-calls` registry, so Phase 12 must explicitly
  archive that state before starting new parallel work.
- OpenClaw foundation touches planning, backend API contracts, product-state
  persistence, the OpenClaw plugin package, and CI. Parallel execution is only
  safe if those write scopes are locked first.

Active feature:

- Phase 12: OpenClaw Foundation
- Active wave: `w12-openclaw-foundation`

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad topic names.
2. `.planning/*` lock and registry rewrites remain orchestrator-owned.
3. Backend contract files under `src/am_server/**` remain isolated from
   `packages/am-openclaw/**` and `src/agentic_memory/product/**`.
4. Every task writes a handoff under
   `.planning/execution/handoffs/w12-openclaw-foundation/` before the task is
   considered done.
5. Verification commands in `tasks.json` are merge gates, not optional notes.
