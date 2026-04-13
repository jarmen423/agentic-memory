# Execution Registry

This directory is the active wave-execution registry for the current Phase 16
OpenClaw whole-stack onboarding work.

Why it exists:

- The OpenClaw GTM plan is the program/reference document, not the execution registry.
- Phase 15 is complete, so the active registry must move forward without losing
  the completed `w15-openclaw-docs-and-private-beta` handoffs and task state.
- This wave exists because the current repo still leaks operator-only local
  assumptions into the user path:
  - plugin setup writes config but does not yet behave like a whole-stack doctor
  - temporal scripts and docs still rely on saved aliases or hardcoded port defaults
  - local services such as SpacetimeDB and Grafana can collide unless the user
    reverse-engineers the correct target
- The goal is to turn the current private-beta-prepped stack into one supported
  onboarding path for the whole local stack, not to continue GTM collateral work.

Active feature:

- Phase 16: OpenClaw Whole-Stack Onboarding
- Active wave: `w16-openclaw-whole-stack-onboarding`

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad topic names.
2. `.planning/*` lock and registry rewrites remain orchestrator-owned.
3. Onboarding contract work lands before parallel implementation threads touch
   plugin UX, stack bootstrap, or docs.
4. Plugin UX, stack/bootstrap code, and docs must stay in disjoint write scopes
   unless the contract task explicitly freezes a shared boundary first.
5. Every task writes a handoff under
   `.planning/execution/handoffs/w16-openclaw-whole-stack-onboarding/` before
   the task is considered done.
6. Verification commands in `tasks.json` are merge gates, not optional notes.
