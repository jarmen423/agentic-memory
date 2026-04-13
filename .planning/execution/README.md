# Execution Registry

This directory currently holds the latest completed wave-execution snapshot for
Phase 15 OpenClaw docs + private beta work.

Why it exists:

- The OpenClaw GTM plan is the program/reference document, not the execution registry.
- Phase 14 is complete, so the registry had to move forward without losing
  the completed `w14-openclaw-scaling-and-packaging` handoffs and task state.
- This phase spans three real parallel tracks from the GTM plan:
  - docs and committed OpenAPI output
  - package identity, marketplace, and publish-surface prep
  - private-beta onboarding/support operations artifacts
- The package identity is now resolved as `agentic-memory-openclaw`, and the
  completed snapshot captures the install, OpenAPI, beta-ops, and support
  surfaces that were locked for private beta.

Most recent completed feature:

- Phase 15: OpenClaw Docs + Private Beta
- Wave: `w15-openclaw-docs-and-private-beta`

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad topic names.
2. `.planning/*` lock and registry rewrites remain orchestrator-owned.
3. `docs/openclaw/guides/**` and `docs/openclaw/openapi/**` stay isolated from
   package-identity work in `packages/am-openclaw/**`.
4. Marketplace/publish-surface changes that touch package manifests or release
   workflows stay separate from private-beta onboarding/support docs.
5. Every task writes a handoff under
   `.planning/execution/handoffs/w15-openclaw-docs-and-private-beta/` before
   the task is considered done.
6. Verification commands in `tasks.json` are merge gates, not optional notes.
