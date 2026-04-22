# Exp 1B — End-to-End Clinical QA with Temporal Reasoning Design Notes

## Purpose

`Exp 1B` evaluates the full agentic-memory stack — retrieval + LLM answer
synthesis — on clinical questions that require temporal reasoning. It is
gated by `Exp 1A`: only run this if the retrieval layer can win on its own
at isolated temporal retrieval. Otherwise end-to-end numbers conflate LLM
quality with retrieval quality and the result cannot be attributed to the
temporal component.

See `../exp1_temporal_decay/ISSUES.md` for the critique motivating this
redesign and `../exp1A_temporal_retrieval/DESIGN.md` for the paired
retrieval-only study.

## Claim Under Test

> The full agentic-memory stack (graph + vector + temporal) answers
> temporally-sensitive clinical questions more correctly and with fewer
> anachronisms than simpler retrieval stacks feeding the same LLM.

## Falsifiability Statement

- If the full stack (arm 6) does not beat **SQL + LLM** (arm 2) by **≥ 10
  F1 points** on temporally-sensitive questions, the entire retrieval
  layer is not earning its complexity.
- If removing the temporal component (arm 7) does not drop accuracy by
  **≥ 5 points** relative to the full stack (arm 6), the temporal
  weighting specifically is not earning its place — independent of
  whatever else the retrieval layer is doing.

Both thresholds chosen so that statistical noise in an LLM judge cannot
flip the verdict.

## Design Principles

- **Paired comparison across arms.** Same patients, same questions, same
  snapshot dates, same LLM, same prompt template. Only the retrieval layer
  changes between arms. Use Wilcoxon signed-rank for the arm-6-vs-arm-7
  temporal-ablation comparison.
- **Anchor is the query's `as_of`, never the answer's `START`.** Inherited
  from `Exp 1A`.
- **Answer-shape-appropriate metrics.** Set answers → F1. Single answers →
  exact-match or LLM-judge. Yes/No → accuracy. Never a single metric across
  heterogeneous shapes.
- **LLM-as-judge discipline.** Different model family from the generator
  so the system does not grade its own homework. Judge gets access to the
  full patient record plus a structured rubric. Calibrate with at least
  100 human-graded tasks and report Cohen's κ.
- **Cost is part of the result.** Latency and token cost per answer are
  reported alongside correctness. Complexity must earn its keep.

## Task Families

Every family requires temporal reasoning. No family can be answered by
"pick the newest row for this patient" — that heuristic is the baseline
we are trying to beat.

| Family | Shape | Gold shape | Why it requires temporal reasoning |
|---|---|---|---|
| **Med reconciliation** | "What medications was patient X taking on [date]?" | Set of drug names | Point-in-time set membership; changes across dates |
| **Event-anchored list** | "What was patient X's medication list at the time of their [ER visit / admission]?" | Set | Anchor is an unrelated event's date |
| **Regimen timeline** | "What did patient X switch from when they started [drug]?" | Single drug name | Identifies the predecessor in the same indication |
| **Delta query** | "What medications changed between [date1] and [date2] for patient X?" | Two sets: added, removed | Pure differential reasoning |
| **Counterfactual timing** | "Was patient X on [drug] during [year]?" | Yes/No + overlapping entries | Interval-overlap logic |
| **First occurrence** | "When did patient X first show signs of [condition]?" | Date | Ordering across a timeline |
| **Active problem list** | "What are the active chronic conditions for patient X as of [date]?" | Set | Activity status + chronicity classification |

## Arms

Held constant across all arms: LLM, prompt template, patient set, question
set, snapshot sweep, K for retrieval, answer format.

| # | Arm | Retrieval | Temporal | Purpose |
|---|---|---|---|---|
| 1 | `full_dump + LLM` | Dump every patient fact into context | n/a | Ceiling if context fits; tests whether retrieval is even needed |
| 2 | `sql + LLM` | `WHERE patient=X AND type=Y` | — | Honest baseline: no graph, no vector, no decay |
| 3 | `vector + LLM` | Embedding similarity only | — | Floor for semantic retrieval |
| 4 | `graph_cypher + LLM` | Cypher on `PRESCRIBED` / `DIAGNOSED_WITH` + patient filter | — | Graph without temporal weighting |
| 5 | `hybrid + LLM` | Graph + vector fusion | — | Hybrid without temporal |
| 6 | `full_stack + LLM` | Graph + vector + temporal decay + overlap filter | soft decay + overlap | **The claim** |
| 7 | `full_stack_temporal_ablated + LLM` | Same as arm 6 with decay disabled | — | Isolates the temporal contribution from the rest of the stack |

Arms 6 and 7 are paired and the key comparison. Arm 2 is the "do we even
need retrieval" sanity check.

## Hyperparameter Sweeps

- **Snapshot date:** `2008-06-30`, `2012-06-30`, `2016-06-30`, `2020-06-30`.
- **Same patient cohort reused across all snapshots** so we can plot
  correctness vs. `|now − as_of|` per patient.
- **K for retrieval:** fixed at 20 across all arms. Not swept. (K-sensitivity
  is a separate study.)

Task count: target ≈ 100 patients × 7 families × 4 snapshots ≈ 2800 tasks.
This is enough for paired-task statistics at α = 0.05 with Wilcoxon. Start
with 25 patients for a pilot.

## Metrics

**Correctness (per answer shape):**

- **F1** — set answers (med reconciliation, delta sets, active list).
- **Exact match** — single-string answers (regimen-timeline predecessor).
- **LLM-judge score** — free-form or mixed. Structured rubric, not
  "is this good."
- **Accuracy** — Yes/No answers (counterfactual timing).
- **Date error in days** — for "when did X first happen?" answers.

**Temporal-correctness (specific to this experiment):**

- **Anachronism rate** — fraction of fact references in the answer whose
  validity interval does NOT overlap the query's `as_of`. This is the
  temporal-reasoning-specific error mode. Answers with high correctness
  but high anachronism rate indicate the LLM is papering over bad
  retrieval.
- **Hallucination rate** — fraction of fact references in the answer that
  do not appear in the patient's record at all.

**Graceful degradation:**

- Plot correctness and anachronism vs. `|now − as_of|` (where "now" is the
  snapshot's ingestion date). A healthy stack's correctness curve should
  be flatter than the baseline's.

**Operational:**

- Latency p50 / p95 per answer.
- Token cost (input + output) per answer.
- Retrieval edges hydrated per query.

## LLM-Judge Design

- **Different model family from the generator.** If the generator is
  GPT-family, the judge is Claude-family (or vice versa). Never self-grade.
- **Calibration set.** At least 100 tasks hand-labeled by a human. Report
  Cohen's κ between judge and human. If κ < 0.6, the judge is unreliable
  and must be re-prompted or replaced before the main run.
- **Judge prompt supplies the full patient record and a structured rubric,
  not the arm identity.** The judge does not know which arm produced the
  answer. This blinds the judge to the treatment.
- **Rubric fields, scored independently:** factual correctness, temporal
  correctness (anachronism check), completeness (for set answers),
  hallucination check.

## Preflight Assertions

1. For each task, the required fields exist in the graph for the patient:
   predicate, validity interval, embedding. Fail fast otherwise.
2. Validity intervals are populated on **≥ 95% of candidate edges** across
   the retrieval universe. Report the miss rate.
3. Spot-check 20 tasks manually to verify gold is right before spending
   GPU hours on LLM inference.
4. Each arm returns **≥ 1 candidate** for **≥ 90% of tasks**. If an arm
   cannot return candidates, it cannot be fairly compared — fix or
   document the exclusion.

## Data Flow

1. Load deterministic task JSON (reuses the same task generator as
   `Exp 1A`, extended with the three additional families that don't
   appear in 1A: delta, first-occurrence, active-problem-list).
2. For each task × arm:
   a. Retrieve K candidates per the arm's retrieval policy.
   b. Format retrieved context into the shared prompt template.
   c. Generate answer with the fixed LLM.
   d. Score answer against gold and against the patient record.
3. Aggregate per `(arm, family, snapshot)` cell.
4. Run paired statistical tests: arm 6 vs. arm 7 per family (Wilcoxon),
   arm 6 vs. arm 2 per family (Wilcoxon).

## Success Criteria and Decision Rules

| Outcome | Finding | Next step |
|---|---|---|
| Arm 6 beats arm 2 by ≥ 10 F1 AND beats arm 7 by ≥ 5 F1 | Full stack earns its place; temporal component contributes | Ship the claim |
| Arm 6 beats arm 2 by ≥ 10 F1 but NOT arm 7 | Retrieval layer is helping but temporal decay is not the reason | Attribute wins to graph + vector, drop temporal claim |
| Arm 6 does not beat arm 2 | Full retrieval stack is not earning its complexity | Rescope product claim, investigate whether LLM is fitting around bad retrieval |
| Arm 6 correctness is high but anachronism rate is also high | LLM is hallucinating correct-sounding wrong facts | Prompt engineering problem, not retrieval problem; different fix path |
| Preflight fails | Tasks, graph, or embedding coverage broken | Stop, fix, rerun |

## Important Files (to be created / modified)

### New
- `experiments/healthcare/exp1B_e2e_clinical_qa/run.py` — arm dispatcher, sweep driver.
- `experiments/healthcare/exp1B_e2e_clinical_qa/arms.py` — seven arm implementations.
- `experiments/healthcare/exp1B_e2e_clinical_qa/judge.py` — LLM-judge wrapper + rubric + calibration harness.
- `experiments/healthcare/exp1B_e2e_clinical_qa/preflight.py` — four assertions above.
- `experiments/healthcare/tasks/exp1B_tasks_*.json` — generated task fixtures (extends `exp1A_tasks_*`).
- `experiments/healthcare/exp1B_e2e_clinical_qa/calibration_set.jsonl` — 100 human-labeled tasks for judge calibration.

### Modified
- `experiments/healthcare/qa_generator.py` — add generators for the three families unique to 1B (delta, first-occurrence, active-problem-list).
- `experiments/healthcare/eval_runner.py` — add F1, anachronism-rate, hallucination-rate helpers. Keep `Exp 1A`'s additions intact.

### Read-only
- `src/agentic_memory/temporal/bridge.py`
- `src/agentic_memory/server/tools.py`
- Any existing LLM client wiring used by prior experiments.

## Known Caveats

- LLM-judge noise is the largest threat to this experiment's internal
  validity. If calibration κ is weak, the experiment cannot produce a
  trustworthy verdict no matter how clean the retrieval layer is.
- The comparison is **paired within patient/question**, not independent
  samples. Reporting must use paired tests, not two-sample tests.
- `Exp 1B` does not benchmark reranking layers (Cohere, etc.). Those are
  a separate study. The "full stack" here is specifically retrieval +
  temporal + LLM, not every possible ranking component.
- The task generator's "indication" mapping (for regimen-timeline and
  active-problem-list families) is an approximation. Document the mapping
  tables alongside results so they can be audited.
- The Phase 5 Exp 1A forensic (commit `2f73303`) found that the temporal
  bridge can return `valid_to=None` for historically closed prescriptions that
  the Synthea-derived fixture records with a STOP date. That mismatch does not
  invalidate Exp 1A's point-in-time ranking metric, but it would bias Exp 1B's
  `counterfactual_timing` and `active_problem_list` families: a model that sees
  a discontinued drug as open-ended may treat it as currently active and answer
  the question anachronistically. Before trusting those family results, verify
  ingestion preserves STOP dates through the bridge payload actually shown to
  the model.
