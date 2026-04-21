# Exp 1A — Isolated Temporal Retrieval Design Notes

## Purpose

`Exp 1A` replaces the broken `Exp 1` temporal-decay study with a design that
can actually exercise the temporal weighting mechanism. It tests one narrow
claim about the retrieval layer in isolation — no LLM, no answer synthesis,
no end-to-end product reasoning. That separation is deliberate: if temporal
retrieval is not helping at the retrieval layer, no amount of LLM polish at
the top of the stack can rescue it, and we should find that out cheaply.

See `../exp1_temporal_decay/ISSUES.md` for the detailed critique of the
original `Exp 1`. The short version is that the original experiment was
structurally incapable of distinguishing its variants: the decay math could
not fire on the ground-truth class, the scoring confused set answers with
single answers, the predicate filter returned zero candidates on ~37% of
tasks, and every task was anchored at one wall-clock date.

## Claim Under Test

> Temporal edge weighting helps retrieve the time-correct version of a fact
> when the patient's timeline contains multiple same-family candidates with
> non-overlapping validity intervals.

## Falsifiability Statement

Written before running, so we cannot drift after seeing results:

- If the soft-decay arms do not beat the hard-overlap arm by **≥ 8 points of
  time-sliced Hits@1** on supersession tasks, decay is not contributing
  beyond overlap logic.
- If the full-temporal arms do not beat the `always_newest` heuristic arm
  by **≥ 5 points of time-sliced Hits@1**, temporal retrieval is not
  beating a trivial baseline and does not justify its latency.

If either condition triggers, the honest finding is "temporal decay as
currently implemented does not earn its place," and the claim must be
retracted or the mechanism redesigned.

## Design Principles (inherited from the critique)

Every task must satisfy all five:

1. **The answer must change when the clock moves.** If gold is stable
   across `as_of` values, the task cannot test temporal reasoning.
2. **Distractors must be same-family, different-time.** Different-concept
   distractors can be separated by vector similarity alone — the temporal
   layer must be forced to discriminate along time.
3. **The anchor must come from outside the answer.** Calendar sweep or
   unrelated clinical event. Never the answer's own `START`.
4. **Metric shape matches answer shape.** Set answers → precision / recall /
   F1. Single answers → MRR, Hits@K.
5. **Preflight asserts the mechanism can mechanically fire.** If 100% of
   gold edges overlap the anchor, the temporal distance is 0, decay weight
   is 1.0, and half-life becomes a no-op. Catch this before the run.

## Task Families

All five families require multiple same-family candidates per patient. Gold
is selected by deterministic rules on the Synthea export.

| Family | Query shape | Gold | Distractors |
|---|---|---|---|
| **Supersession** | "Which [ATC class] medication was this patient on as of [date]?" | Same-class prescription whose interval overlaps `as_of` | Earlier and later same-class prescriptions in non-overlapping intervals |
| **Regimen change** | "What was the patient taking for [indication] at the time of their [event]?" | Drug active at the event's date | Same-indication alternatives from different time periods |
| **Recurring condition** | "Which episode of [recurring condition] was active on [date]?" | Condition episode whose interval overlaps `as_of` | Other episodes of the same condition at other times |
| **Dose escalation** | "What dose of [drug] was the patient on as of [date]?" | Dose active at `as_of` | Earlier and later doses of the same drug |
| **Retrospective state** | "Was the patient on [drug] during [year]?" | Yes/No + specific overlapping entries | Same drug's entries outside that year |

### Anchor Policy

For every task, `as_of_date` is drawn from one of two sources, never from
the gold edge itself:

- **Calendar sweep** — one of `2008-06-30`, `2012-06-30`, `2016-06-30`,
  `2020-06-30`. The same snapshot is reused across many patients so we can
  plot accuracy-vs-snapshot-age.
- **Unrelated clinical event** — an ER visit, hospitalization, or procedure
  date that is *not* the start or stop of the gold fact. This produces
  anchors that are semantically meaningful to the query text ("at the time
  of their 2014 admission…") but independent of the answer.

**Hard requirement:** at least **40% of supersession and regimen-change
tasks** must have a gold interval whose `valid_from` ≠ `as_of` and whose
`valid_to` ≠ `as_of`. Otherwise the decay math is a no-op on that task
(temporal distance = 0 → weight = 1.0 regardless of half-life). This is
enforced by preflight (see below).

## Arms (from floor to ceiling)

| # | Arm | Graph | Vector | Temporal | Purpose |
|---|---|---|---|---|---|
| 1 | `random_in_family` | — | — | — | Random floor among same-family candidates |
| 2 | `always_newest` | patient-scoped | — | — | "Just pick the newest" heuristic baseline |
| 3 | `hard_overlap` | patient-scoped + family filter | — | interval-overlap hard filter, random tiebreak | Simple temporal logic, no decay |
| 4 | `hard_overlap + decay_tiebreak` | same as #3 | — | overlap filter + decay breaks ties | Decay as a minor discriminator |
| 5 | `soft_decay_only` | PPR from patient seed | embedding similarity | decay weights on edges | Original `Exp 1` mechanism |
| 6 | `soft_decay + hard_overlap` | PPR + family filter | embedding similarity | decay + overlap | Target configuration |

Arm 1 is the floor. Arm 2 is the "dumb heuristic" that the temporal system
must beat to earn its complexity. Arm 3 is the honest non-ML baseline. Arm
6 is what the project claims to ship.

## Hyperparameter Sweeps

- **Half-life:** `30d`, `90d`, `180d`, `365d`, `1095d` (3 years).
  - 24h and 168h from the original `Exp 1` are dropped. They are clinically
    meaningless for longitudinal chart data and waste compute.
- **Snapshot date:** `2008-06-30`, `2012-06-30`, `2016-06-30`, `2020-06-30`.
- **Anchor-to-event distance buckets** (computed per task, not swept):
  `same_year`, `1–3y`, `3–10y`, `>10y`. Used to plot graceful degradation.

Grid size: `5 half-lives × 4 snapshots × 6 arms ≈ 120 runs` per task. Keep
the task count modest (≈ 200 per family → 1000 tasks total) until the
signal stabilizes, then scale.

## Metrics

**Primary (ranking quality):**

- **Time-sliced Hits@1** — top-1 retrieved edge must match the target
  concept family AND its validity interval must overlap `as_of`.
- **In-family MRR** — mean reciprocal rank computed only over same-family
  candidates. Strips noise from the predicate filter surviving or not.
- **Interval precision@K** (K = 5) — of the top-K candidates returned,
  what fraction have intervals overlapping `as_of`? Diagnoses whether the
  temporal layer is ordering correctly vs. just retrieving the right
  family at all.

**Diagnostic:**

- **Temporal error (days)** — when the top-1 pick is wrong, compute
  `|as_of − midpoint(picked.valid_interval)|` in days. The distribution
  tells us whether failures are "close misses" (days–weeks off) or
  "decades off" catastrophes.
- **Same-family retention rate** — fraction of top-20 that are in the
  target family. Separates "decay is working" from "predicate filter is
  working."

**Operational:**

- Latency p50 / p95, candidate counts, edge counts per retrieval.

## Preflight Assertions

Run before every sweep. Fail fast if any assertion breaks.

1. Every task has **≥ 2 same-family candidates** in the graph for the
   target patient. (Ensures distractors exist.)
2. **≥ 40% of supersession and regimen-change tasks** have gold intervals
   that do NOT contain the anchor. (Ensures soft decay can mechanically
   fire on a material fraction of the test set.)
3. The expected predicates (`PRESCRIBED`, `DIAGNOSED_WITH`, `HAS_CONDITION`,
   dose-change predicate) exist for the `project_id`. Catches silent
   predicate renames during backfill.
4. **At least one task** shows different top-1 rankings between
   `half_life=30d` and `half_life=1095d` on arm 5. Catches the `Exp 1`
   §2.2 invariance bug before the full sweep runs.

## Data Flow

1. Load deterministic task JSON from the new generator (see agent
   prompts — covers five families, sweeps snapshots, tags anchor source).
2. For each task, resolve `as_of_us` from the task's `as_of_date`, never
   from the gold fact's `START`.
3. For each arm, invoke the retrieval path with that arm's settings:
   - Arms 1–3 bypass PPR entirely (trivial code paths).
   - Arms 4–6 call `TemporalBridge.retrieve(...)` with the arm's
     half-life and optional hard-overlap post-filter.
4. Score against the gold fact's `(description, valid_from, valid_to)`
   tuple using time-sliced Hits@1, in-family MRR, interval precision@K,
   and temporal error.
5. Aggregate per `(arm, half_life, snapshot, family)` cell. Emit a
   heatmap-ready JSON.

## Success Criteria and Decision Rules

| Outcome | Finding | Next step |
|---|---|---|
| Arm 6 beats arm 3 by ≥ 8 Hits@1 AND beats arm 2 by ≥ 5 Hits@1 | Temporal decay earns its place | Proceed to `Exp 1B` |
| Arm 6 beats arm 3 by ≥ 8 but NOT arm 2 | Decay helps over overlap alone but not over "newest" | Investigate: does "newest" hide because chronic conditions dominate the population? Rescope before shipping |
| Arm 6 does not beat arm 3 | Decay is a no-op vs. hard overlap | Replace soft decay with hard overlap filter; do not claim temporal retrieval |
| Preflight fails | Tasks or graph broken | Stop, fix, rerun |

## Important Files (to be created / modified)

### New
- `experiments/healthcare/exp1A_temporal_retrieval/run.py` — arm dispatcher, sweep driver.
- `experiments/healthcare/exp1A_temporal_retrieval/arms.py` — six arm implementations.
- `experiments/healthcare/exp1A_temporal_retrieval/preflight.py` — the four assertions above.
- `experiments/healthcare/tasks/exp1A_tasks_*.json` — generated task fixtures.

### Modified
- `experiments/healthcare/qa_generator.py` — add the five task-family generators (supersession, regimen-change, recurring, dose-escalation, retrospective-state).
- `experiments/healthcare/eval_runner.py` — add time-sliced Hits@1, in-family MRR, interval precision@K, temporal-error helpers. Keep existing metrics for backward compatibility.

### Read-only
- `src/agentic_memory/temporal/bridge.py`
- `packages/am-temporal-kg/src/procedures/retrieve.ts`
- `packages/am-temporal-kg/src/lib/time.ts`

## Known Caveats

- `Exp 1A` does not evaluate the full memory system. It is a component
  test. See `../exp1B_e2e_clinical_qa/DESIGN.md` for the end-to-end claim.
- The "right answer" under the corrected clinical prior (old ≠ dim for
  chronic conditions) may turn out to be "hard overlap filter with no soft
  decay." Arm 3 winning is a legitimate, publishable outcome. The design
  does not presume decay must win.
- Set-answer variants ("all active medications on date X") are deferred
  to `Exp 1B` where F1 can be scored end-to-end. `Exp 1A` is strictly
  single-answer ranking.
