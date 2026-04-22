# Exp 1A Phase 5 Handoff — 2026-04-22

## Current Branch State

- Local feature branch: `codex/exp1ab-phase1`
- Local worktree:
  `D:\code\agentic-memory-exp1ab-work`
- Latest pushed commit on `public/codex/exp1ab-phase1`:
  `fec6db3` — `Make Exp 1A pilot config portable across local and VM runs`

## What Was Just Implemented

- Added the Exp 1A Phase 5 runner:
  `D:\code\agentic-memory-exp1ab-work\experiments\healthcare\exp1A_temporal_retrieval\run.py`
- Added the pilot config:
  `D:\code\agentic-memory-exp1ab-work\experiments\healthcare\exp1A_temporal_retrieval\config.pilot.yaml`
- Updated the Phase 4 arms so each call records retrieval metadata for the runner:
  `D:\code\agentic-memory-exp1ab-work\experiments\healthcare\exp1A_temporal_retrieval\arms.py`
- Corrected stale Phase 5 docs so they match the four-family Exp 1A scope:
  - `D:\code\agentic-memory-exp1ab-work\experiments\healthcare\exp1A_temporal_retrieval\DESIGN.md`
  - `D:\code\agentic-memory-exp1ab-work\experiments\healthcare\EXP1AB_AGENT_PROMPTS.md`

## Pilot Configuration That Actually Ran

- Dataset: `mid_fhirfix`
- Families:
  - `supersession`
  - `regimen_change`
  - `recurring_condition`
  - `dose_escalation`
- Snapshot buckets used:
  - `2012-06-30`
  - `2016-06-30`
- Tasks per `(family, snapshot bucket)`: `25`
- Half-lives:
  - `30d`
  - `90d`
  - `180d`
  - `1y`
  - `3y`
- Arms:
  - `random_in_family`
  - `always_newest`
  - `hard_overlap`
  - `hard_overlap_decay_tiebreak`
  - `soft_decay_only`
  - `soft_decay_hard_overlap`
- Total cells: `25 x 4 x 5 x 2 x 6 = 6000`

## Authoritative VM Execution Surface

- Canonical healthcare host note:
  `G:\My Drive\kubuntu\Tangent\agentic-memory-private\healthcare-experiment-host.md`
- Authoritative scratch worktree used for the pilot:
  `/root/agentic-memory-exp1ab-phase5`
- Authoritative pilot outputs:
  - `/root/agentic-memory-exp1ab-phase5/experiments/healthcare/results/exp1A_pilot/results.jsonl`
  - `/root/agentic-memory-exp1ab-phase5/experiments/healthcare/results/exp1A_pilot/heatmap.json`
  - `/root/agentic-memory-exp1ab-phase5/experiments/healthcare/results/exp1A_pilot/pilot.log`
  - `/root/agentic-memory-exp1ab-phase5/experiments/healthcare/exp1A_temporal_retrieval/PILOT_REPORT.md`

## Pilot Outcome

- The pilot completed successfully:
  - `6000 / 6000` rows written
  - `240` heatmap cells written
  - no empty-candidate rows
- The runner pipeline itself is valid:
  - append-only JSONL worked
  - aggregation worked
  - report generation worked

## Important Experimental Finding

The pilot exposed a real retrieval problem, not a runner problem.

- `random_in_family` mean Hits@1: `0.465`
- `always_newest` mean Hits@1: `0.635`
- `hard_overlap` mean Hits@1: `1.000`
- `hard_overlap_decay_tiebreak` mean Hits@1: `0.000`
- `soft_decay_only` mean Hits@1: `0.000`
- `soft_decay_hard_overlap` mean Hits@1: `0.000`

Interpretation:

- The bridge-backed arms are returning candidates, but they are ranking the
  wrong overlapping candidate above the gold.
- This is not an empty-retrieval failure.
- Example observed in pilot rows: dose-escalation tasks where the bridge arms
  rank `10 MG` above the gold `23 MG` despite both candidates overlapping the
  anchor and belonging to the same family.

This means:

- Do **not** advance to Phase 6 yet.
- The next technical task after reconciliation is diagnosis of the bridge-arm
  ranking/scoring path.

## VM Main Clone Drift Status

The VM main clone was intentionally not used for the pilot because it was
already dirty.

- Dirty main clone path:
  `/root/agentic-memory`
- Branch there at inspection time:
  `codex/exp1ab-phase1`
- Local HEAD there:
  `57a4d35eae21b49dd907e5dd086fe9ad816cce7b`
- Remote branch head at inspection time:
  `fec6db3f3cb2fd029fb6b28a9908f6518690c89f`
- Main clone was behind remote by `7` commits.

Observed drift types in `/root/agentic-memory`:

- tracked edits in healthcare docs/code
- untracked healthcare docs/prototypes
- untracked generated results under `experiments/healthcare/results/`
- untracked environment noise under `.venv-agentic-memory/`

## Drift Backup / Inventory

Before reconciliation, the dirty VM main clone was inventoried here:

- `/root/agentic-memory-vm-backups/dirty-main-2026-04-22/SUMMARY.md`
- `/root/agentic-memory-vm-backups/dirty-main-2026-04-22/status.txt`
- `/root/agentic-memory-vm-backups/dirty-main-2026-04-22/tracked.diff`
- `/root/agentic-memory-vm-backups/dirty-main-2026-04-22/untracked.txt`
- `/root/agentic-memory-vm-backups/dirty-main-2026-04-22/untracked-nonvenv.txt`

The intent of reconciliation is:

1. preserve local-only VM work intentionally
2. separate code/docs/prototypes from generated output and environment noise
3. return `/root/agentic-memory` to an organized state aligned with the
   current feature branch

## Reconciliation Outcome

The VM main clone was reconciled after the pilot completed.

- Preserved VM-only local work on branch:
  `vm/healthcare-dirty-snapshot-2026-04-22`
- Snapshot commit on that branch:
  `5658230` — `Snapshot VM healthcare WIP before branch reconciliation`
- Local-only ignore entries added in `/root/agentic-memory/.git/info/exclude`:
  - `.venv-agentic-memory/`
  - `experiments/healthcare/results/`
- Main VM clone after reconciliation:
  - path: `/root/agentic-memory`
  - branch: `codex/exp1ab-phase1`
  - HEAD: `fec6db3f3cb2fd029fb6b28a9908f6518690c89f`
  - status: clean

This means the VM now has:

- one organized main clone aligned with the feature branch
- one preserved VM-only WIP branch holding the previous local state
- one scratch worktree holding the completed Phase 5 pilot outputs

## Immediate Next Steps

1. Use this note as the starting context instead of reconstructing state from
   chat or ad hoc VM inspection.
2. Diagnose why bridge-backed arms score `0.0` Hits@1 while `hard_overlap`
   scores `1.0` on the same pilot corpus.
3. Do **not** advance to Phase 6 until the bridge-arm ranking failure is
   explained and fixed.
