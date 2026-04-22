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

Exp 1A intentionally covers four ranking families only. The original
`retrospective_state` use case was removed because it is yes/no
classification, not ranking: negative cases correctly have no overlapping
interval and therefore cannot satisfy Exp 1A's load-bearing overlap
invariant. That query shape now lives in Exp 1B as
`counterfactual_timing`, which reuses the existing
`generate_retrospective_state_tasks()` output verbatim.

All four ranking families require multiple same-family candidates per patient.
Gold is selected by deterministic rules on the Synthea export.

| Family | Query shape | Gold | Distractors |
|---|---|---|---|
| **Supersession** | "Which [ATC class] medication was this patient on as of [date]?" | Same-class prescription whose interval overlaps `as_of` | Earlier and later same-class prescriptions in non-overlapping intervals |
| **Regimen change** | "What was the patient taking for [indication] at the time of their [event]?" | Drug active at the event's date | Same-indication alternatives from different time periods |
| **Recurring condition** | "Which episode of [recurring condition] was active on [date]?" | Condition episode whose interval overlaps `as_of` | Other episodes of the same condition at other times |
| **Dose escalation** | "What dose of [drug] was the patient on as of [date]?" | Dose active at `as_of` | Earlier and later doses of the same drug |

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

**Hard requirements (enforced by preflight):**

- **Gold must overlap `as_of_date`.** The fact is active at the query
  time — that is the semantic meaning of "what was the patient on as of
  [date]?" so the gold interval `[valid_from, valid_to]` must contain
  `as_of_date`. At the gold, temporal distance is 0 and decay weight is
  1.0, which is correct: the right answer should be at full strength.
- **`as_of_date` must not equal `gold.valid_from` or `gold.valid_to`.**
  This avoids degenerate boundary cases where `as_of` lands exactly on
  the start or stop of the gold interval. Such boundary anchoring is a
  bookkeeping artifact, not a meaningful temporal test.
- **At least 40% of supersession and regimen-change tasks must have
  ≥ 1 same-family distractor whose interval lies entirely outside
  `as_of_date`** (the distractor's `valid_to` precedes `as_of_date`, or
  its `valid_from` follows `as_of_date`). This is where soft decay
  can mechanically fire: the gold stays at weight 1.0 (distance = 0)
  while out-of-interval distractors get weight < 1.0 (distance > 0).
  Without out-of-interval distractors on a material fraction of tasks,
  every candidate sits at weight 1.0 and the half-life axis becomes a
  no-op — the `Exp 1` §2.1 failure mode.

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

1. **Every task is well-formed**: ≥ 2 same-family candidates exist for
   the target patient; `gold.valid_from` ≤ `as_of` ≤ `gold.valid_to`
   (gold is active at `as_of`); `as_of` ≠ `gold.valid_from` and
   `as_of` ≠ `gold.valid_to` (no boundary anchoring). Catches
   malformed tasks — distractor-less, gold-not-active, or boundary-
   anchored — before any arm runs.
2. **≥ 40% of supersession and regimen-change tasks** have at least one
   same-family distractor whose interval lies entirely outside `as_of`
   (distractor's `valid_to` precedes `as_of`, or distractor's `valid_from`
   follows `as_of`). Ensures soft decay can mechanically fire on the
   distractor class — the only class where it can affect ranking since
   the gold always sits at distance 0.
3. The **required** predicates (`PRESCRIBED`, `DIAGNOSED_WITH`) exist for
   the `project_id`. Catches silent predicate renames during backfill.
   Notes on what the graph should NOT be expected to have:
   - `HAS_CONDITION` is **not required**. It was a legacy synonym for
     `DIAGNOSED_WITH` in earlier ingestion eras. Current backfills (e.g.
     `synthea-scale-mid-fhirfix`) emit only `DIAGNOSED_WITH`, and that is
     sufficient for the supersession and active-problem families.
   - There is **no dedicated dose-change predicate**. Dose escalation is
     detected as multiple `PRESCRIBED` edges for the same drug base
     (same RxNorm/ingredient) whose description / strength string differs
     across validity intervals. The task generator must read dose from
     the edge's description string, not from a relationship type.
   - `OBSERVED` (labs / observations) and `UNDERWENT` (procedures) may
     also exist in the graph. Exp 1A does not require them, but they are
     available for future task families in Exp 1B.
4. **At least one task** shows different top-1 rankings between
   `half_life=30d` and `half_life=1095d` on arm 5. Catches the `Exp 1`
   §2.2 invariance bug end-to-end — if this fires, something earlier
   in the chain (probably assertion #2) was satisfied vacuously.

## Data Flow

1. Load deterministic task JSON from the new generator (see agent
   prompts — covers four ranking families, sweeps snapshots, tags anchor
   source).
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
- `experiments/healthcare/qa_generator.py` — add the Exp 1A ranking-family generators (supersession, regimen-change, recurring, dose-escalation) and keep `generate_retrospective_state_tasks()` available for Exp 1B reuse.
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
- The Phase 5 arm-6 forensic captured a bridge/fixture reporting mismatch for
  medication STOP dates: the task fixture preserved Synthea's closed
  `valid_to`, while the bridge returned `valid_to=None` for the same
  prescription (see forensic evidence commit `2f73303`). `Exp 1A` is not
  sensitive to that mismatch because ranking-at-a-point-in-time only needs the
  overlap rule `valid_from <= as_of` when `valid_to` is missing, which is the
  correct semantics for this experiment. `Exp 1B` is more exposed: before
  trusting counterfactual or active-state conclusions, confirm ingestion
  preserves STOP dates end-to-end.
