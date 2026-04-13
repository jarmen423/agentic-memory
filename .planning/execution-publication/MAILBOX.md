# W15-PUB Central Mailbox

Deprecated:

- This file is no longer part of the active workflow.
- The source of truth is now `.planning/execution-publication/tasks.json` plus
  handoffs under
  `.planning/execution-publication/handoffs/w15-public-plugin-publication/`.
- Coordination is handled by a single orchestrator with subagents, not parallel
  peer sessions.

This is the shared coordination document for the publication wave:

- Wave: `w15-public-plugin-publication`
- Registry: `.planning/execution-publication/`
- Source plan: `docs/PLUGIN_GA_PLAN.md`

Use this file as the single mailbox between parallel sessions so both agents can
see:

- who currently owns which slice
- what is actively in progress
- what has already landed
- what is blocked
- what is safe to start next

## Mailbox Rules

- Keep official task ownership aligned to `tasks.json`.
- Use this mailbox to split work within a task only when the write scopes are truly disjoint.
- Do not silently edit another track's owned files.
- When you claim a track, update:
  - `Assigned session`
  - `State`
  - `Working on`
  - `Last update`
- When you finish a track, update:
  - `State`
  - `Done`
  - `Remaining blockers`
  - `Handoff path`

## Current Wave Snapshot

Completed official tasks:

- `W15-PUB-00`
- `W15-PUB-01`
- `W15-PUB-02`
- `W15-PUB-03`
- `W15-PUB-04`
- `W15-PUB-05`
- `W15-PUB-06`

Open official tasks:

- `W15-PUB-07`

Shared unresolved items:

- New publication pages are implemented in `am-server` but still need deployment to the live `api.agenticmemory.com` host.
- Public auth posture is now fixed to `OAuth 2.0 authorization code flow`, but OAuth is not yet implemented in `am-server`.
- Reviewer/demo account provisioning is still open.

## Parallelization Plan

Safe parallel work right now:

1. `W15-PUB-07` can continue on the status/evidence ledger and launch-gate closure record.

Not safe right now:

- no additional parallel track should reopen `W15-PUB-06` files unless a later packet change forces a deliberate reconciliation pass

## W15-PUB-03

Official task:

- `W15-PUB-03` Harden the Codex local/preflight plugin bundle and install checklist

Owned write scope:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `docs/publication/codex/**`

Assigned session:

- Completed in another session and confirmed locally

State:

- Complete

Working on:

- none

Done:

- `.codex-plugin/plugin.json` reconciled
- `.mcp.json` reconciled
- `docs/publication/codex/**` packet landed
- official task marked complete in `tasks.json`

Remaining blockers:

- none at the task level; only downstream launch blockers remain

Last update:

- 2026-04-12: confirmed complete from repo state and handoff

Handoff path:

- `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-03.md`

## W15-PUB-06 Split

Official task:

- `W15-PUB-06` Integrate publication assets into top-level docs without reopening parallel write scopes

This task is intentionally split into two mailbox tracks so two sessions can
parallelize the integration pass without touching the same files.

### Track 1: User-Facing Top-Level Docs

Owned write scope:

- `README.md`
- `docs/INSTALLATION.md`
- `docs/PUBLIC_PLUGIN_SURFACES.md`

Assigned session:

- Orchestrator delegated worker `06-track-1`

State:

- Complete

Working on:

- aligning `README.md`, `docs/INSTALLATION.md`, and `docs/PUBLIC_PLUGIN_SURFACES.md` to the completed publication packets

Done:

- `README.md` aligned to the real publication model and packet links
- `docs/INSTALLATION.md` aligned to the real publication model and packet links
- `docs/PUBLIC_PLUGIN_SURFACES.md` rewritten as the canonical hosted public surface contract page
- track handoff written

Remaining blockers:

- none at the task level; only later doc edits should reopen this deliberately

Last update:

- 2026-04-12: worker completed and orchestrator reviewed handoff

Handoff path:

- `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-06-TRACK-1.md`

### Track 2: Plan + Publication Index

Owned write scope:

- `docs/PLUGIN_GA_PLAN.md`
- `docs/publication/INDEX.md`

Assigned session:

- Orchestrator delegated worker `06-track-2`

State:

- Complete

Working on:

- aligning `docs/PLUGIN_GA_PLAN.md` and creating `docs/publication/INDEX.md`

Done:

- `docs/PLUGIN_GA_PLAN.md` aligned with packet work, canonical URLs, and OAuth auth posture
- `docs/publication/INDEX.md` created as the publication entrypoint
- track handoff written

Remaining blockers:

- none at the task level; only later doc edits should reopen this deliberately

Last update:

- 2026-04-12: worker completed and orchestrator reviewed handoff

Handoff path:

- `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-06-TRACK-2.md`

### W15-PUB-06 Merge Rule

`W15-PUB-06` is only considered complete when:

- Track 1 is complete
- Track 2 is complete
- cross-links are consistent across both tracks
- no file outside the declared track scopes was touched

Current status:

- complete

## W15-PUB-07

Official task:

- `W15-PUB-07` Track external review, approval evidence, and launch-gate closure

Owned write scope:

- `.planning/execution-publication/tasks.json`
- `docs/publication/status/**`

Assigned session:

- Orchestrator local follow-through

State:

- In progress

Working on:

- status docs, evidence ledger, and launch-gate tracking scaffolding

Done:

- `docs/publication/status/OPENAI_REVIEW.md`
- `docs/publication/status/ANTHROPIC_REVIEW.md`
- `docs/publication/status/LAUNCH_GATE.md`
- `docs/publication/status/README.md`
- `docs/publication/status/EVIDENCE.md`
- `docs/publication/status/REVISION_RESPONSE_CHECKLIST.md`
- `W15-PUB-07` handoff written

Remaining blockers:

- real submission evidence is still missing
- publication/legal URLs are implemented but not yet confirmed live on the public host
- OAuth is chosen but not implemented
- reviewer/demo/test account provisioning is still open

Last update:

- 2026-04-12: registry reconciled after confirming `W15-PUB-03` and `W15-PUB-06` complete

Handoff path:

- `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-07.md`

## Cross-Track Notes

- The new canonical planned publication URLs are:
  - `https://api.agenticmemory.com/publication/agentic-memory`
  - `https://api.agenticmemory.com/publication/privacy`
  - `https://api.agenticmemory.com/publication/terms`
  - `https://api.agenticmemory.com/publication/support`
  - `https://api.agenticmemory.com/publication/dpa`
- Those URLs are implemented in code, but not confirmed live yet.
- Public auth/network choice is no longer ambiguous:
  - chosen model is `OAuth 2.0 authorization code flow`
- That decision does not mean OAuth is done; it means future integration work should stop describing auth as undecided.
- `W15-PUB-03` is already complete, so any future Codex wording drift should be handled as an explicit follow-up rather than by reopening old track assumptions.

## Recent Handoffs

- `W15-PUB-01`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-01.md`
- `W15-PUB-02`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-02.md`
- `W15-PUB-03`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-03.md`
- `W15-PUB-04`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-04.md`
- `W15-PUB-05`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-05.md`
- `W15-PUB-06`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-06.md`
- `W15-PUB-07`: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-07.md`
- URLs/Auth follow-up: `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-BLOCKERS-URLS-AUTH.md`

## Next Recommended Sequence

1. Keep `W15-PUB-07` as the active official task.
2. Record real OpenAI and Anthropic submission evidence as soon as submissions start.
3. Close `G3`, `G4`, and `G5` only after live URLs, auth, and reviewer-account evidence are attached.

## Update Log

- 2026-04-12: mailbox created and seeded with current wave state.
- 2026-04-12: mailbox restructured so `W15-PUB-06` is split into Track 1 and Track 2 with disjoint file ownership.
- 2026-04-12: mailbox reconciled after confirming `W15-PUB-03` complete and `W15-PUB-06` closed.
