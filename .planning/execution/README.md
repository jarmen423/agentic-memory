# Execution Registry

This directory is the active wave-execution registry for the current Phase 11
semantic `CALLS` hardening work.

Why it exists:

- Phase 11 already has roadmap and plan artifacts.
- The remaining work now benefits from parallel execution.
- That parallelism is only safe if write ownership is locked before any worker
  starts making code changes.

Active feature:

- Phase 11: Code Graph Foundation + Code PPR
- Active sub-problem: generalizable semantic `CALLS` support for Python,
  JavaScript, and TypeScript

Execution rules for this registry:

1. Split work by disjoint file ownership, not by vague topic labels.
2. `src/agentic_memory/ingestion/graph.py` stays orchestration-owned because it
   is the shared merge boundary for Python and JS/TS analyzer work.
3. Every worker writes a handoff under `.planning/execution/handoffs/w11-calls/`
   before the task is considered done.
4. Verification commands in `tasks.json` are merge gates, not optional notes.
