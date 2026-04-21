# Agent Prompts — Exp 1A and Exp 1B

This file contains copy-pasteable prompts for a sub-agent (or a fresh
Claude / Codex / Cursor session) that will implement and run the two
redesigned temporal experiments. Each phase is self-contained: a new agent
picking up phase N should be able to complete it by reading only the files
the phase references plus the design docs.

## How to Use This File

1. Start at **Phase 0**. Do not skip it — the orientation is the
   cheapest way to prevent the failures that killed the original `Exp 1`.
2. Execute phases in order. Each phase has a **gate** at the end: a set
   of checks the agent must pass before moving on.
3. **Hard gate between Phase 6 and Phase 7.** If `Exp 1A` does not meet
   the success criteria in `exp1A_temporal_retrieval/DESIGN.md`, stop
   and report. Do **not** start `Exp 1B`. End-to-end numbers cannot be
   attributed to temporal reasoning if the retrieval layer itself is not
   winning on isolated temporal retrieval.
4. Each prompt block is meant to be pasted into a subagent. Adjust model
   selection and working directory for your runtime.

## Shared Project Context (prepend to every phase prompt if the agent is stateless)

```text
You are working inside the `agentic-memory` repository at
D:\code\agentic-memory. The project is an agentic-memory system with a
temporal knowledge graph component. The `experiments/healthcare` directory
contains experiments against Synthea-generated clinical data.

Two new experiments are being built to replace the broken `Exp 1`:
- `Exp 1A` — isolated temporal retrieval; see
  `experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md`.
- `Exp 1B` — end-to-end clinical QA; see
  `experiments/healthcare/exp1B_e2e_clinical_qa/DESIGN.md`.

The detailed critique of the original `Exp 1` lives in
`experiments/healthcare/exp1_temporal_decay/ISSUES.md`. Treat its findings
as background constraints for the replacement.

Rules:
- Do NOT edit the original `experiments/healthcare/exp1_temporal_decay/`
  files except to add references back to the new experiments. The original
  must remain as the reference for what went wrong.
- Reuse `experiments/healthcare/qa_generator.py` and
  `experiments/healthcare/eval_runner.py` where possible. Add new
  functions; do not remove existing ones that other experiments depend on.
- Any new task fixture goes under `experiments/healthcare/tasks/` and
  follows the naming `exp1A_tasks_{family}_{dataset}.json` or
  `exp1B_tasks_{family}_{dataset}.json`.
- When in doubt about the retrieval internals, read
  `src/agentic_memory/temporal/bridge.py`,
  `packages/am-temporal-kg/src/procedures/retrieve.ts`, and
  `packages/am-temporal-kg/src/lib/time.ts` before guessing.
- Follow the teaching-through-code style: non-trivial new modules get
  module docstrings, public functions get structured docstrings, and
  non-obvious logic gets targeted comments that explain intent.

Infrastructure:
- Run every phase on the Hetzner VM, not on the local Windows host. The
  corrected export, graph databases, SpacetimeDB state, and production-like
  temporal retriever live on the VM, so local generation or preflight can
  produce misleading empty fixtures and irrelevant throughput.
- SSH alias: `ssh experiments`. If the alias is not configured on your
  system, the exact IP, username, and any non-default port are recorded
  at `C:\Users\jfrie\.codex\agents.md`. Read that file to recover the
  connection details. Do NOT copy the IP into any file that will be
  committed — keep it in your session only.
- Sync model: VM is the edit and run surface; GitHub and the local Windows
  clone must still be kept in sync so experiment code is not stranded on the
  VM. Workflow:
  1. `ssh experiments`.
  2. Work in the VM's clone at the agreed repo path (confirm the path on first
     connect; likely `~/agentic-memory`).
  3. Commit code changes on a feature branch in the VM clone.
  4. Push that branch to the GitHub remote from the VM.
  5. Pull or fetch that branch into the local Windows clone at
     `D:\code\agentic-memory` so the local workspace matches the runnable
     experiment code.
  6. Invoke every runner, smoke test, pilot, and full sweep on the VM. Use
     `tmux` or `screen` for anything that might outlive the SSH session.
  7. After the run, copy results back with
     `scp experiments:~/agentic-memory/experiments/healthcare/results/... ./experiments/healthcare/results/`
     or an equivalent `rsync`.
- Results must be written in an append-only JSONL format (one row per
  completed task) so partial results can be pulled while the run
  continues and so a crash loses at most the current in-flight task.
- Do NOT execute any phase on the local Windows host. Local use is limited to
  inspecting files and syncing code/results after VM runs.
```

---

## Execution Location per Phase

| Phase | Location | Reason |
|---|---|---|
| 0 — Orientation | **VM** | Keep artifacts in the same clone used for execution. |
| 1 — Task generator | **VM** | The full corrected export lives there; local samples are too sparse and misleading. |
| 2 — Preflight | **VM** | All assertions must run against real fixtures and the graph-backed retriever. |
| 3 — New metrics | **VM** | Unit tests should run in the same Python environment used by the runners. |
| 4 — Arms | **VM** | Arms 4–6 call TemporalBridge, which is expected to be backed by the VM's graph. |
| 5 — 1A pilot | **VM** | 25-patient × 5-family × 5-halflife × 4-snapshot × 6-arm ≈ 15k retrievals. |
| 6 — 1A full sweep | **VM, in `tmux`** | 50–80 hours. Checkpointing mandatory. |
| 7 — Judge calibration | **VM** | Keep calibration output next to generated fixtures and runner code. |
| 8 — 1B pilot | **VM** | 25-patient × 7-family × 4-snapshot × 7-arm with an LLM in the loop. |
| 9 — 1B full | **VM, in `tmux`** | Largest sweep; checkpointing mandatory. |
| 10 — Deprecation | **VM** | Update docs in the same clone and sync through GitHub/local clone. |

For every `run.py` invocation:
1. Launch inside `tmux new -s exp1X_full` (or similar) so it survives
   disconnects.
2. Append results to the configured JSONL path immediately after each
   task; never batch-write at the end of a run.
3. Print a heartbeat line every N tasks (e.g., `[123/15000] arm=6 hl=180d snap=2016 family=supersession task=EXP1A-00123 latency=3.4s`)
   so `tail -f` gives a useful progress signal over SSH.

---

## Phase 0 — Orientation

**Goal:** understand what failed in the original experiment and what the
replacement is trying to accomplish, so later phases don't recreate the
same bugs.

**Prerequisite:** none.

**Inputs to read, in order:**
1. `experiments/healthcare/exp1_temporal_decay/ISSUES.md` — full critique.
2. `experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md` — 1A spec.
3. `experiments/healthcare/exp1B_e2e_clinical_qa/DESIGN.md` — 1B spec.
4. `experiments/healthcare/exp1_temporal_decay.py` — the broken runner.
5. `experiments/healthcare/qa_generator.py` — focus on the existing
   `temporal_most_recent_active_condition` and
   `temporal_active_medications` generators to understand the current
   shape.
6. `experiments/healthcare/eval_runner.py` — focus on the scoring
   functions; note what metrics already exist.
7. `src/agentic_memory/temporal/bridge.py` and
   `packages/am-temporal-kg/src/procedures/retrieve.ts` — the retrieval
   path the new arms will exercise.

**Output:** a short report (200–400 words) written to
`experiments/healthcare/exp1A_temporal_retrieval/ORIENTATION_NOTES.md`
covering:
- Which specific lines of code implement the five bugs from `ISSUES.md`
  §2.1 through §2.5. (Cite `file:line-line` explicitly.)
- Which existing helpers in `qa_generator.py` and `eval_runner.py` can be
  reused in the new generators and metrics.
- Any assumptions that need to be verified before coding starts.

**Gate:** the agent must be able to explain, in one paragraph, why
`temporalDistanceMicros` returning 0 on overlapping intervals makes
soft-decay variants mathematically equivalent when all candidates are
currently active. If the agent cannot, do not advance.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 0: Orientation for the Exp 1A / Exp 1B redesign.

1. Read these files, in order:
   - experiments/healthcare/exp1_temporal_decay/ISSUES.md
   - experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md
   - experiments/healthcare/exp1B_e2e_clinical_qa/DESIGN.md
   - experiments/healthcare/exp1_temporal_decay.py
   - experiments/healthcare/qa_generator.py (skim; focus on the two
     temporal task generators)
   - experiments/healthcare/eval_runner.py (skim; focus on the scoring
     helpers)
   - src/agentic_memory/temporal/bridge.py
   - packages/am-temporal-kg/src/procedures/retrieve.ts
   - packages/am-temporal-kg/src/lib/time.ts

2. Write a 200–400-word orientation report to
   experiments/healthcare/exp1A_temporal_retrieval/ORIENTATION_NOTES.md
   with these sections:
   - Bug mapping: cite file:line-line for each of ISSUES.md §2.1 through
     §2.5. Include a one-sentence paraphrase per bug.
   - Reusable helpers: list the qa_generator.py and eval_runner.py
     functions that Phase 1 and Phase 3 will extend.
   - Open assumptions: things to verify in later phases (e.g., does the
     Synthea export include an ATC class for every prescription? Does the
     graph carry dose information as an edge property?).

3. Gate check: at the bottom of ORIENTATION_NOTES.md, explain in one
   paragraph why temporalDistanceMicros returning 0 on overlapping
   intervals makes soft-decay variants mathematically equivalent when all
   candidates are currently active.

Do not modify any file except ORIENTATION_NOTES.md. Do not start any
coding task until you have completed this phase.
```

---

## Phase 1 — Shared Task-Family Generator

**Goal:** extend `qa_generator.py` with five deterministic task-family
generators (supersession, regimen-change, recurring, dose-escalation,
retrospective-state) that produce tasks meeting the design principles in
`exp1A_temporal_retrieval/DESIGN.md`.

**Prerequisite:** Phase 0 complete.

**Inputs to read:**
- `experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md` §Task Families and §Anchor Policy.
- `experiments/healthcare/qa_generator.py` — understand existing
  patient-record loading and fact extraction.
- `experiments/healthcare/tasks/exp1_tasks_mid_fhirfix.json` — one
  example existing task to match schema conventions.

**Outputs:**
1. New functions in `qa_generator.py`:
   - `generate_supersession_tasks(patients, atc_class_map) -> list[Task]`
   - `generate_regimen_change_tasks(patients, indication_map) -> list[Task]`
   - `generate_recurring_condition_tasks(patients) -> list[Task]`
   - `generate_dose_escalation_tasks(patients) -> list[Task]`
   - `generate_retrospective_state_tasks(patients) -> list[Task]`
2. A CLI entrypoint script
   `experiments/healthcare/exp1A_temporal_retrieval/generate_tasks.py`
   that writes `tasks/exp1A_tasks_*.json` for the `synthea-scale-mid-fhirfix`
   dataset. It must also tag each task with:
   - `category`, `family`, `anchor_source` (`calendar_sweep` or `clinical_event`),
   - `gold.valid_from`, `gold.valid_to` (nullable),
   - `distractors` — list of same-family alternatives with their intervals,
   - `concept_family` — the ATC class, indication, or condition key.
3. A small mapping table in
   `experiments/healthcare/exp1A_temporal_retrieval/concept_mappings.py`:
   - `ATC_CLASS_MAP` (medication name → ATC class),
   - `INDICATION_MAP` (medication → clinical indication),
   - `CHRONIC_CONDITION_SET` (ICD-like identifiers flagged chronic).
   If Synthea already exposes any of these, use the authoritative source
   instead of hand-rolling.

**Acceptance criteria:**
- At least 150 valid tasks per family generated from
  `synthea-scale-mid-fhirfix`. If a family can't hit 150, document why
  in a comment inside the generator function.
- ≥ 40% of supersession and regimen-change tasks have a gold interval
  whose `valid_to` precedes `as_of_date` OR whose `valid_from` follows
  `as_of_date`. (Enforced by the generator, asserted at the end.)
- Each task's distractor list has ≥ 1 entry.
- Task schema validates against a pydantic model or jsonschema you add
  next to the generator.

**Gate:** before calling Phase 1 complete, run the generator end-to-end
against the existing `synthea-scale-mid-fhirfix` export and produce five
JSON fixtures. Spot-check 10 tasks per family by hand and confirm the
gold and distractors are coherent.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 1: build the shared task-family generator for Exp 1A
and Exp 1B.

Read:
- experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md, focusing on
  §Task Families and §Anchor Policy.
- experiments/healthcare/qa_generator.py in full so you can reuse its
  patient-record loading.
- One existing task fixture such as
  experiments/healthcare/tasks/exp1_tasks_mid_fhirfix.json to match
  schema conventions.

Deliver:
1. Five new functions in qa_generator.py named exactly:
   generate_supersession_tasks,
   generate_regimen_change_tasks,
   generate_recurring_condition_tasks,
   generate_dose_escalation_tasks,
   generate_retrospective_state_tasks.
   Each returns a list of task dicts with the fields listed in the DESIGN.
   Each function gets a Google-style docstring explaining what the task
   family tests and why the gold and distractors are chosen the way they
   are.
2. A CLI at
   experiments/healthcare/exp1A_temporal_retrieval/generate_tasks.py that
   writes tasks/exp1A_tasks_{family}_mid_fhirfix.json for each of the five
   families.
3. A small concept_mappings.py module with ATC_CLASS_MAP, INDICATION_MAP,
   and CHRONIC_CONDITION_SET. If Synthea itself exposes these codes, use
   them and cite the source in the file's module docstring.
4. A jsonschema or pydantic schema for the task dict, placed at
   experiments/healthcare/exp1A_temporal_retrieval/task_schema.py.

Acceptance:
- ≥ 150 valid tasks per family on synthea-scale-mid-fhirfix. Document
  shortfalls in the generator docstring if any family can't reach 150.
- ≥ 40% of supersession and regimen-change tasks have a gold interval
  that does NOT contain as_of_date. Assert this in the generator.
- Each task has ≥ 1 distractor.
- Schema validation passes for every generated task.

Before declaring Phase 1 done, spot-check 10 tasks per family by hand
and record observations in
experiments/healthcare/exp1A_temporal_retrieval/TASK_SPOT_CHECK.md.

Do not edit files outside experiments/healthcare/. Do not delete or
rename existing functions in qa_generator.py — only add new ones.
```

---

## Phase 2 — Preflight & Mechanism Sanity Check

**Goal:** build and pass the four preflight assertions from
`exp1A_temporal_retrieval/DESIGN.md` §Preflight Assertions. This catches
the `Exp 1` §2.1 and §2.2 bugs before any arm runs.

**Prerequisite:** Phase 1 complete.

**Outputs:**
- `experiments/healthcare/exp1A_temporal_retrieval/preflight.py` with four
  functions, one per assertion, and a `main()` that runs all four against
  the generated fixtures.
- A report `experiments/healthcare/exp1A_temporal_retrieval/PREFLIGHT_RESULTS.md`
  summarizing the assertions' outcomes.

**Gate:** all four assertions must pass. If any fail, the agent must stop
and produce a diagnostic report rather than monkey-patching around the
failure.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 2: build the preflight harness for Exp 1A.

Read experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md
§Preflight Assertions.

Write experiments/healthcare/exp1A_temporal_retrieval/preflight.py with:
- assert_distractor_counts(tasks) — every task has ≥ 2 same-family
  candidates in the graph.
- assert_non_overlap_fraction(tasks) — ≥ 40% of supersession and
  regimen-change tasks have gold intervals not containing as_of.
- assert_predicate_presence(project_id) — PRESCRIBED, DIAGNOSED_WITH,
  HAS_CONDITION, and the dose-change predicate all exist in the graph.
- assert_halflife_sensitivity(sample_tasks) — run a tiny pilot on 20
  supersession tasks with half_life=30d and half_life=1095d; assert at
  least one task produces different top-1 rankings.

Add a main() that runs all four and exits nonzero on any failure.

Run the harness against the Phase 1 fixtures and produce a report at
experiments/healthcare/exp1A_temporal_retrieval/PREFLIGHT_RESULTS.md.

If any assertion fails, do NOT patch around it. Stop and write a
diagnostic report at
experiments/healthcare/exp1A_temporal_retrieval/PREFLIGHT_DIAGNOSTIC.md
with (a) which assertion failed, (b) the likely root cause in Phase 1 or
the graph, and (c) proposed fix. Then stop.
```

---

## Phase 3 — New Metrics in eval_runner.py

**Goal:** add time-sliced Hits@1, in-family MRR, interval precision@K,
temporal error in days, and same-family retention rate as helpers in
`eval_runner.py` without breaking existing metrics that other experiments
depend on.

**Prerequisite:** Phase 2 green.

**Outputs:**
- New pure functions in `eval_runner.py`, each with a structured
  docstring and unit-level doctest examples.
- Unit tests in
  `experiments/healthcare/exp1A_temporal_retrieval/test_metrics.py` that
  cover: perfect prediction, completely wrong prediction, close-miss,
  mixed family top-K.

**Gate:** doctests and unit tests both pass. Existing `eval_runner.py`
tests (if any) still pass.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 3: extend eval_runner.py with the five new metrics.

Read:
- experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md §Metrics.
- experiments/healthcare/eval_runner.py in full.

Add these functions to eval_runner.py (pure, no global state):
- time_sliced_hits_at_1(retrieved, gold, as_of) -> float in {0, 1}
- in_family_mrr(retrieved, gold, family_of_fn) -> float in [0, 1]
- interval_precision_at_k(retrieved, as_of, k) -> float in [0, 1]
- temporal_error_days(picked, as_of) -> float ≥ 0
- same_family_retention(retrieved, target_family, family_of_fn, k=20) -> float in [0, 1]

Each function gets a Google-style docstring with Args, Returns, and at
least one doctest example.

Add unit tests at
experiments/healthcare/exp1A_temporal_retrieval/test_metrics.py with
pytest cases for:
- perfect top-1 in-family, overlapping as_of → Hits@1 = 1, MRR = 1.
- wrong family top-1 → Hits@1 = 0.
- close-miss (off by 7 days) → temporal_error_days ≈ 7.
- mixed top-K (3 in family, 2 out of family) → same_family_retention at K=5 = 0.6.

Run pytest. Do not advance to Phase 4 until it's green.

Do not remove or rename any existing function in eval_runner.py.
```

---

## Phase 4 — Exp 1A Arms

**Goal:** implement the six arms from
`exp1A_temporal_retrieval/DESIGN.md` §Arms behind a shared interface
that the Phase 5 runner will dispatch to.

**Prerequisite:** Phase 3 green.

**Outputs:**
- `experiments/healthcare/exp1A_temporal_retrieval/arms.py` with a
  `BaseArm` abstract class and six concrete implementations:
  `RandomInFamilyArm`, `AlwaysNewestArm`, `HardOverlapArm`,
  `HardOverlapDecayTiebreakArm`, `SoftDecayOnlyArm`,
  `SoftDecayHardOverlapArm`.
- Each arm exposes `retrieve(task, k, half_life) -> list[Candidate]`.
  Arms 1–3 ignore `half_life`.
- A tiny smoke script `arms_smoke.py` that runs each arm against 5
  random tasks and prints the top-5 for each. Used for manual verification.

**Gate:** smoke script runs clean for all six arms on all five task
families.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 4: implement the six retrieval arms for Exp 1A.

Read experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md §Arms
and src/agentic_memory/temporal/bridge.py so you understand how arms 4–6
invoke TemporalBridge.retrieve.

Create experiments/healthcare/exp1A_temporal_retrieval/arms.py with:
- BaseArm abstract class exposing retrieve(task, k, half_life) -> list of
  Candidate objects (description, valid_from, valid_to, score).
- Six concrete subclasses named:
  RandomInFamilyArm,
  AlwaysNewestArm,
  HardOverlapArm,
  HardOverlapDecayTiebreakArm,
  SoftDecayOnlyArm,
  SoftDecayHardOverlapArm.
- Each subclass gets a class-level docstring explaining its retrieval
  policy and which arm row in DESIGN.md it corresponds to.

Arms 1–3 do not call TemporalBridge — they implement the retrieval in
plain Python against the task's distractor+gold list (plus patient
record lookups if needed).

Arms 4–6 call TemporalBridge.retrieve with the right half-life and apply
any additional post-filter in Python.

Write experiments/healthcare/exp1A_temporal_retrieval/arms_smoke.py that
runs each arm against 5 random tasks per family and prints top-5 results.
Verify manually that:
- RandomInFamilyArm results differ between runs (it's random).
- AlwaysNewestArm always returns the same candidate regardless of as_of.
- HardOverlapArm returns only overlapping candidates.
- Soft-decay arms return something non-trivial.

Do not advance to Phase 5 until the smoke run is sane by inspection.
```

---

## Phase 5 — Exp 1A Runner & Pilot

**Goal:** run a pilot of Exp 1A on 25 patients × all families × all
arms × all half-lives × all snapshots to verify the pipeline end-to-end
before committing to the full sweep.

**Prerequisite:** Phase 4 smoke complete.

**Execution location:** Hetzner VM via `ssh experiments`. Implement and run
from the VM clone, push the phase branch to GitHub, and then fetch/pull that
branch into the local Windows clone so the runnable experiment code is synced.
Run the pilot inside `tmux`. See the Infrastructure and Execution-Location
sections at the top of this file.

**Outputs:**
- `experiments/healthcare/exp1A_temporal_retrieval/run.py` — sweep driver,
  reads tasks + arms + config, writes per-task results JSONL and an
  aggregate heatmap JSON.
- `experiments/healthcare/exp1A_temporal_retrieval/config.pilot.yaml` —
  pilot config.
- `experiments/healthcare/results/exp1A_pilot/` — pilot results
  directory.

**Gate:** pilot completes without errors, produces a valid heatmap JSON,
and each `(arm, half_life, snapshot)` cell has ≥ 10 tasks.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 5: build the Exp 1A runner and execute a 25-patient
pilot.

Create experiments/healthcare/exp1A_temporal_retrieval/run.py that:
- Reads a YAML config (patient count, families, half-lives, snapshots,
  arms).
- For each (task, arm, half_life, snapshot) cell, calls the arm's
  retrieve(), scores with Phase 3 metrics, and writes one result row
  to results/exp1A_pilot/results.jsonl (or the directory from config).
- After all cells run, aggregates per (arm, half_life, snapshot, family)
  into results/exp1A_pilot/heatmap.json with mean metrics and Wilson
  95% confidence intervals.
- Logs operational metrics per cell: latency p50/p95, candidate count,
  edge count.

Write experiments/healthcare/exp1A_temporal_retrieval/config.pilot.yaml
that selects 25 patients, all five families, all five half-lives, all
four snapshots, all six arms. Grid size ≈ 25 × 5 × 5 × 4 × 6 = 15000
retrievals; expect ~8 hours at 3s/retrieval. If that's too slow, reduce
the snapshot sweep to 2 snapshots for the pilot.

Run the pilot. Write a short report at
experiments/healthcare/exp1A_temporal_retrieval/PILOT_REPORT.md covering:
- Any cells that failed or produced empty candidates.
- Whether the heatmap shows any signal at all.
- Whether the half-life axis moves the needle on arms 4–6 (sanity).
- Estimated wall-clock for the full sweep.

Do not advance to Phase 6 until the pilot runs clean.
```

---

## Phase 6 — Exp 1A Full Sweep & Decision Gate

**Goal:** run the full Exp 1A sweep, produce the headline heatmap, and
apply the decision rule from `exp1A_temporal_retrieval/DESIGN.md`
§Success Criteria.

**Prerequisite:** Phase 5 pilot clean.

**Execution location:** Hetzner VM via `ssh experiments`, inside a
long-lived `tmux` session (50–80 hours wall-clock). Checkpointing is
mandatory. Pull partial results back to local periodically via `scp` or
`rsync` so an analysis can be prototyped while the sweep continues. See
the Infrastructure and Execution-Location sections at the top of this
file.

**Outputs:**
- `experiments/healthcare/results/exp1A_full/` with full results.
- `experiments/healthcare/exp1A_temporal_retrieval/RESULTS.md` — the
  headline write-up. Must include the heatmap, the falsifiability
  statement, and an explicit verdict.

**Gate:** this is the critical gate between Exp 1A and Exp 1B.

- If arm 6 beats arm 3 by ≥ 8 Hits@1 **and** beats arm 2 by ≥ 5 Hits@1,
  advance to Phase 7.
- Otherwise, **stop**. Write a "do not run 1B" diagnostic to
  `exp1A_temporal_retrieval/GATE_FAILURE.md` and return to the user for
  a direction call.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 6: run the full Exp 1A sweep and apply the decision
gate.

Using experiments/healthcare/exp1A_temporal_retrieval/run.py from Phase 5,
create config.full.yaml with:
- 200 patients per family (1000 total tasks minimum).
- All five half-lives: 30d, 90d, 180d, 365d, 1095d.
- All four snapshots: 2008-06-30, 2012-06-30, 2016-06-30, 2020-06-30.
- All six arms.

Expect ~50-80 hours wall-clock. Plan for checkpointing: run.py should
resume from results.jsonl if interrupted.

Write experiments/healthcare/exp1A_temporal_retrieval/RESULTS.md with:
- The full heatmap rendered as markdown tables: one table per
  (family, metric) cell.
- Arm-vs-arm comparison tables with Wilson 95% CIs.
- Temporal-error distributions per arm (histogram as ASCII or linked
  image).
- Graceful-degradation plot: correctness vs. |now − as_of| per arm.
- Operational metrics: latency p50/p95 per arm.

Then apply the decision rule from DESIGN.md §Success Criteria:

Case 1: arm 6 beats arm 3 by ≥ 8 Hits@1 on supersession tasks AND arm 6
beats arm 2 by ≥ 5 Hits@1 overall → write "GATE PASS" at the top of
RESULTS.md and advance to Phase 7.

Case 2: any other outcome → do NOT advance. Write
experiments/healthcare/exp1A_temporal_retrieval/GATE_FAILURE.md with:
- Which threshold failed.
- Whether arm 3 (hard overlap without decay) is the actual winner.
- Recommended rescope (e.g., "ship hard-overlap filter, drop decay
  claim" or "investigate whether chronic conditions mask the signal").
- Stop. Do not start Phase 7 without an explicit direction from the user.
```

---

## Phase 7 — [GATED] Exp 1B Additional Families & Judge Harness

**Goal:** extend the task generator with the three families unique to
Exp 1B (delta, first-occurrence, active-problem-list), and build the
LLM-judge harness with calibration.

**Prerequisite:** Phase 6 gate passed.

**Outputs:**
- Three new task-family generators in `qa_generator.py`:
  `generate_delta_tasks`, `generate_first_occurrence_tasks`,
  `generate_active_problem_list_tasks`.
- `experiments/healthcare/exp1B_e2e_clinical_qa/judge.py` — LLM-judge
  wrapper with rubric and calibration harness.
- `experiments/healthcare/exp1B_e2e_clinical_qa/calibration_set.jsonl` —
  100 tasks hand-labeled from the 1A fixture plus the new families.
- `experiments/healthcare/exp1B_e2e_clinical_qa/CALIBRATION_REPORT.md` —
  reports judge-human Cohen's κ, per-family breakdown.

**Gate:** Cohen's κ ≥ 0.6. Otherwise re-prompt or switch judge model.

### Copy-pasteable prompt

```text
[Shared project context above]

Exp 1A passed its gate. Your task is Phase 7: extend the task generator
and build the LLM-judge harness.

Step 1 — New task families. Add to qa_generator.py:
- generate_delta_tasks(patients) — "what medications changed between
  date1 and date2 for patient X?" (answer: two sets, added+removed).
- generate_first_occurrence_tasks(patients) — "when did patient X first
  show signs of [condition]?" (answer: date).
- generate_active_problem_list_tasks(patients) — "what are the active
  chronic conditions for patient X as of [date]?" (answer: set).

Each function follows the same conventions as Phase 1 (docstring,
schema, preflight-friendly, anchor independent of answer). Target ≥ 150
tasks per family.

Step 2 — Hand-label calibration set. Randomly sample 100 tasks across
all 8 families (5 from 1A, 3 from 1B). For each, produce the gold
answer manually by reading the patient's Synthea record, and write to
experiments/healthcare/exp1B_e2e_clinical_qa/calibration_set.jsonl
with fields: task_id, gold_answer, human_rubric_scores.

Step 3 — LLM-judge harness. Build
experiments/healthcare/exp1B_e2e_clinical_qa/judge.py with:
- A structured rubric function that takes (task, retrieved_context,
  candidate_answer) and returns rubric scores on factual_correctness,
  temporal_correctness, completeness, hallucination.
- A different model family from the generator (if generator is GPT,
  judge is Claude, etc.).
- A calibration runner that scores the 100 hand-labeled tasks with
  the judge and reports Cohen's κ per rubric field.

Write CALIBRATION_REPORT.md with per-field κ. If any field has
κ < 0.6, re-prompt the judge or switch model, and document the change.

Do not advance until κ ≥ 0.6 on every rubric field.
```

---

## Phase 8 — [GATED] Exp 1B Arms & Runner

**Goal:** implement the seven Exp 1B arms and the end-to-end runner that
retrieves, prompts the generator LLM, and scores with the calibrated judge.

**Prerequisite:** Phase 7 calibrated κ ≥ 0.6.

**Execution location:** implement and run on the Hetzner VM via
`ssh experiments`. Arms 4–6 depend on the graph being hot on the VM; running
anything locally will either fail or run at an irrelevant throughput. Push the
phase branch to GitHub and fetch/pull it into the local Windows clone after
the VM run so code stays synced. See the Infrastructure and Execution-Location
sections at the top of this file.

**Outputs:**
- `experiments/healthcare/exp1B_e2e_clinical_qa/arms.py` — seven
  retrieval-stack arms per DESIGN §Arms.
- `experiments/healthcare/exp1B_e2e_clinical_qa/run.py` — sweep driver
  that runs retrieval → generator LLM → judge per task.
- `experiments/healthcare/exp1B_e2e_clinical_qa/config.pilot.yaml` —
  pilot on 25 patients × 7 families × 4 snapshots × 7 arms.

**Gate:** pilot produces results for ≥ 90% of (arm, task) cells. Cells
with < 1 candidate from retrieval are logged and skipped, not retried.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 8: build the Exp 1B arms and runner, then execute a
25-patient pilot.

Read experiments/healthcare/exp1B_e2e_clinical_qa/DESIGN.md §Arms.

Create arms.py with seven classes:
- FullDumpArm (dumps every patient fact into context)
- SqlArm (WHERE patient=X AND type=Y)
- VectorArm (embedding similarity only)
- GraphCypherArm (Cypher on predicate + patient)
- HybridArm (graph + vector fusion)
- FullStackArm (graph + vector + temporal with decay + overlap)
- FullStackAblatedArm (FullStack with decay disabled)

Each arm exposes retrieve(task, k) -> list[Fact] and must be deterministic
given the same seed and config.

Create run.py that for each (task, arm):
1. Calls arm.retrieve() to get retrieved context.
2. Formats context into the shared prompt template.
3. Calls the fixed generator LLM.
4. Calls the Phase 7 judge with task + retrieved context + candidate
   answer, gets rubric scores.
5. Writes a result row with retrieval metadata, answer, rubric scores,
   latency, token cost.

Write config.pilot.yaml for 25 patients × 7 families × 4 snapshots × 7
arms. Log any retrieval-empty cells; skip them in scoring.

Run the pilot. Write PILOT_REPORT.md covering:
- % cells completed per arm.
- Empty-retrieval cells per arm.
- Aggregate F1 and anachronism rate per arm on the pilot set.
- Extrapolated wall-clock and cost for the full run.

Do not advance to Phase 9 until the pilot is clean and ≥ 90% cells
completed.
```

---

## Phase 9 — [GATED] Exp 1B Full Run & Decision

**Goal:** run the full Exp 1B sweep, produce the headline results, and
apply the decision rule from `exp1B_e2e_clinical_qa/DESIGN.md` §Success
Criteria.

**Prerequisite:** Phase 8 pilot clean.

**Execution location:** Hetzner VM via `ssh experiments`, inside a
long-lived `tmux` session. This is the largest sweep (100 patients × 7
families × 4 snapshots × 7 arms ≈ 19600 cells, each with an LLM
generation and a judge call — significant token cost). Checkpointing and
heartbeat logging are mandatory. See the Infrastructure and
Execution-Location sections at the top of this file.

**Outputs:**
- `experiments/healthcare/results/exp1B_full/` with full results.
- `experiments/healthcare/exp1B_e2e_clinical_qa/RESULTS.md` — headline
  write-up with verdict.

**Gate:** apply the three-way decision rule from DESIGN.md and record
the verdict.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 9: run the full Exp 1B sweep and publish the verdict.

Using the Phase 8 runner, create config.full.yaml with:
- 100 patients × 7 families × 4 snapshots × 7 arms (~19600 cells).
- The same generator LLM and judge as the pilot.
- Checkpointing on.

Expect significant wall-clock and token cost. Estimate from the pilot
first and warn the user if it exceeds the previously-approved budget.

Produce experiments/healthcare/exp1B_e2e_clinical_qa/RESULTS.md with:
- Per-family F1, anachronism rate, hallucination rate per arm.
- Paired Wilcoxon tests: arm 6 vs. arm 7, arm 6 vs. arm 2, per family.
- Graceful-degradation plot: correctness vs. |now − as_of| per arm.
- Latency and token cost per arm.
- Sample failure modes: 5 tasks per family where arm 6 got it right and
  arm 5 didn't (and vice versa).

Apply the decision rule:
- Arm 6 beats arm 2 by ≥ 10 F1 AND arm 6 beats arm 7 by ≥ 5 F1 →
  "SHIP": write "VERDICT: SHIP" at the top of RESULTS.md with the
  exact deltas and CIs.
- Arm 6 beats arm 2 but not arm 7 → "VERDICT: PARTIAL — attribute
  wins to graph+vector, drop temporal-weighting claim."
- Arm 6 does not beat arm 2 → "VERDICT: RESCOPE — full retrieval
  stack is not earning its complexity."
- High correctness, high anachronism → "VERDICT: INVESTIGATE — LLM
  is papering over bad retrieval."

Always record the verdict at the top of RESULTS.md and cite the
specific metric values that drove it. End of task.
```

---

## Optional Phase 10 — Deprecation of Original Exp 1

**Goal:** once `Exp 1A` has produced a verdict (pass or fail), update
`experiments/healthcare/exp1_temporal_decay/README.md` to point to the
replacement and mark the original as "superseded for methodology reasons —
retained for provenance."

**Prerequisite:** Phase 6 complete, regardless of gate outcome.

### Copy-pasteable prompt

```text
[Shared project context above]

Your task is Phase 10: mark the original Exp 1 as superseded.

Read experiments/healthcare/exp1_temporal_decay/README.md in full.

Prepend a superseded notice with:
- A one-paragraph summary of why it was superseded (cite ISSUES.md §2.1
  and §2.2).
- Links to the replacements at
  experiments/healthcare/exp1A_temporal_retrieval/DESIGN.md and
  experiments/healthcare/exp1B_e2e_clinical_qa/DESIGN.md.
- A link to the verdict at
  experiments/healthcare/exp1A_temporal_retrieval/RESULTS.md.

Do NOT delete any existing content in the original README — this is an
addition at the top only. The original experiment stays on disk as a
reference for the failure modes.

Commit only after user review.
```

---

## Appendix — Failure Recovery Playbook

If a phase fails unexpectedly, the agent should:

1. **Stop.** Do not improvise around a failure. The original `Exp 1`
   died from unreported improvisation.
2. **Write a diagnostic.** `{phase}_DIAGNOSTIC.md` in the relevant
   experiment directory, covering: what failed, what was expected, what
   the logs show, the most likely root cause, and a proposed fix.
3. **Return to the user** with the diagnostic rather than self-healing.

The failures that matter most to catch:
- Preflight failures in Phase 2 — indicates a generator bug.
- Half-life invariance in Phase 2 §4 — indicates the soft-decay arm is
  operating in the same zero-distance regime as the original `Exp 1`.
  Redesign tasks before proceeding.
- Calibration κ < 0.6 in Phase 7 — the judge is unreliable. No
  end-to-end verdict is trustworthy until this is fixed.
- Empty-retrieval cells > 10% in Phase 8 — an arm cannot return
  candidates for too many tasks. Fix the arm or exclude those tasks
  explicitly from scoring with justification.
