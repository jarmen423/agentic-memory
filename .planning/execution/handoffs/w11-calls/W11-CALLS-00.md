# W11-CALLS-00 Handoff

## What changed

- Added a new Phase 11 execution plan:
  - `.planning/phases/11-code-graph-foundation-and-code-ppr/11-02-PLAN.md`
- Added a wave-execution registry:
  - `.planning/execution/README.md`
  - `.planning/execution/ROADMAP.md`
  - `.planning/execution/tasks.json`
- Updated Phase 11 context, UAT, and task registry to reflect the remaining
  semantic `CALLS` generalization work.

## Verified

- Planning artifacts load cleanly from disk.
- Task registry contains explicit write ownership and merge gates.

## Risks / notes

- `graph.py` remains the merge boundary and must stay orchestrator-owned.
- Python semantic analysis is still unimplemented at this point.
- TS/JS analyzer output still needs better drop visibility before real-repo
  indexing can be trusted.
