# Execution Registry

This directory currently holds the completed Phase 14 wave-execution registry
for the OpenClaw scaling + packaging work.

Why it exists:

- The OpenClaw GTM plan is the program/reference document, not the execution registry.
- Phase 13 is complete, so this registry preserved the next OpenClaw wave
  without losing the completed `w13-openclaw-dashboard-and-testing` handoffs
  and task state.
- Phase 14 spanned backend scale-path hardening, package/distribution work, and
  production deployment/release artifacts. Those write scopes are now fully
  closed.
- Phase 15 is now seeded separately, so this registry remains as the most
  recent completed execution snapshot for the scaling + packaging wave.

Most recent completed feature:

- Phase 14: OpenClaw Scaling + Packaging
- Completed wave: `w14-openclaw-scaling-and-packaging`

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad topic names.
2. `.planning/*` lock and registry rewrites remain orchestrator-owned.
3. Backend dashboard files under `src/am_server/**` stay isolated from
   `packages/am-dashboard/**` and the operational harnesses under `tests/**`.
4. The desktop shell boundary (`desktop_shell/**`) is owned by the dashboard
   implementation thread, not the backend or test-harness threads.
5. Every task writes a handoff under
   `.planning/execution/handoffs/w14-openclaw-scaling-and-packaging/` before
   the task is considered done.
6. Verification commands in `tasks.json` are merge gates, not optional notes.
