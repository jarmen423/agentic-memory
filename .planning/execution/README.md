# Execution Registry

This directory is the active wave-execution snapshot for Phase 17 OpenClaw
hosted beta platform + dual-mode deployment.

Why it exists:

- The OpenClaw GTM plan is the program/reference document, not the execution registry.
- Phase 16 closed the whole-stack onboarding gap, but it still assumed an
  operator-managed backend.
- Phase 17 exists because the product direction is now clearer:
  - managed hosted beta should be the default path
  - self-hosted should remain a supported full-stack fallback
  - the backend must expose which mode it is in instead of making the plugin guess
  - hosted auth and metering need to exist before a real managed beta story is honest
- The goal is to turn the current GCP VM deployment into the first truthful
  managed beta target while preserving self-hosted verification.

Active feature:

- Active phase: Phase 17 OpenClaw Hosted Beta Platform + Dual-Mode Deployment
- Active wave: `w17-openclaw-hosted-beta-and-dual-mode`
- Latest completed wave: `w16-openclaw-whole-stack-onboarding`

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad topic names.
2. `.planning/*` lock and registry rewrites remain orchestrator-owned.
3. Managed-vs-self-hosted contract work lands before backend auth, plugin UX,
   or hosted deployment threads touch shared seams.
4. Backend auth/control-plane work, plugin UX, and docs/runbooks must stay in
   disjoint write scopes unless the contract task explicitly freezes a shared boundary first.
5. Every task writes a handoff under
   `.planning/execution/handoffs/w17-openclaw-hosted-beta-and-dual-mode/` before
   the task is considered done.
6. Verification commands in `tasks.json` are merge gates, not optional notes.
