# Execution Registry

This directory currently holds the completed Phase 13 wave-execution registry for
the OpenClaw testing + dashboard work.

Why it exists:

- The OpenClaw GTM plan is the program/reference document, not the execution registry.
- Phase 12 is complete, so this registry preserved the next OpenClaw wave
  without losing the completed `w12-openclaw-foundation` handoffs and task
  state.
- Phase 13 spanned three real parallel tracks: backend dashboard APIs,
  dashboard shell/frontend replacement, and operational test harnesses. The
  write scopes were kept disjoint through execution and are now fully closed.
- No next wave is locked yet. This registry remains as the latest completed
  execution snapshot until the next phase is seeded.

Most recent completed feature:

- Phase 13: OpenClaw Testing + Dashboard
- Completed wave: `w13-openclaw-dashboard-and-testing`

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad topic names.
2. `.planning/*` lock and registry rewrites remain orchestrator-owned.
3. Backend dashboard files under `src/am_server/**` stay isolated from
   `packages/am-dashboard/**` and the operational harnesses under `tests/**`.
4. The desktop shell boundary (`desktop_shell/**`) is owned by the dashboard
   implementation thread, not the backend or test-harness threads.
5. Every task writes a handoff under
   `.planning/execution/handoffs/w13-openclaw-dashboard-and-testing/` before
   the task is considered done.
6. Verification commands in `tasks.json` are merge gates, not optional notes.
