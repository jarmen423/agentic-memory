# Publication Execution Registry

This directory is a **separate wave-execution registry** for the public
publication work described in
[`docs/PLUGIN_GA_PLAN.md`](../../docs/PLUGIN_GA_PLAN.md).

Why it exists:

- The active `.planning/execution/` registry is already carrying the OpenClaw
  scaling + packaging wave.
- This publication work spans different write scopes, different release gates,
  and different external review loops than the active OpenClaw execution queue.
- Mixing the publication tasks into the active registry would create avoidable
  confusion around handoffs, task status, and merge gates.
- The publication plan now targets **real platform publication** for OpenAI and
  Anthropic, so it needs its own contract lock, submission package tasks, and
  approval-tracking surfaces.

Active feature:

- Program plan: `docs/PLUGIN_GA_PLAN.md`
- Active wave: `w15-public-plugin-publication`

Source of truth:

- task state: `.planning/execution-publication/tasks.json`
- task handoffs: `.planning/execution-publication/handoffs/w15-public-plugin-publication/`
- orchestration model: single orchestrator with subagents
- `.planning/execution-publication/MAILBOX.md` is historical only and is no longer
  part of the active workflow

Execution rules for this registry:

1. Split work by disjoint write scope, not by broad platform labels.
2. `.planning/execution-publication/**` is orchestrator-owned and stays separate
   from `.planning/execution/**`.
3. Public backend contract work under `src/am_server/**`,
   `src/agentic_memory/server/**`, and backend-facing tests must not overlap
   with submission-doc threads.
4. OpenAI submission docs, Codex preflight packaging, Anthropic submission
   docs, and shared legal/runbook assets each get separate write ownership.
5. Top-level product docs (`README.md`, `docs/INSTALLATION.md`,
   `docs/PUBLIC_PLUGIN_SURFACES.md`, `docs/PLUGIN_GA_PLAN.md`) stay reserved
   for the integration thread after the parallel tracks land.
6. Every task writes a handoff under
   `.planning/execution-publication/handoffs/w15-public-plugin-publication/`
   before the task is considered done.
7. Verification commands in `tasks.json` are merge gates, not optional notes.
