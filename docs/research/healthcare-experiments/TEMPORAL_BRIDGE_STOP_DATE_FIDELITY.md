# Temporal Bridge STOP-Date Fidelity

## Why This Note Exists

`Exp 1A` Phase 5 exposed a bridge-versus-fixture mismatch on medication stop
dates:

- the deterministic task fixture contains closed medication intervals for
  Exp 1A ranking tasks
- the temporal bridge can return the same underlying prescription with
  `valid_to=None`

That mismatch matters because the temporal weighting code interprets
`valid_to=None` as an open interval. For historical prescriptions, that can make
discontinued medications look active at later snapshot dates and can erase the
distance signal that the half-life sweep is supposed to measure.

This note is the working audit trail for that problem. Use it before drawing
claims from any retrieval or end-to-end experiment that depends on
point-in-time medication activity.

## What We Know So Far

### Forensic reproduction

The Phase 5 one-task forensic on branch commit `2f73303` showed a real bridge
candidate that matched the fixture gold on:

- answer text
- concept family
- `valid_from`

but differed on:

- `source_id`
- `valid_to` (`None` from the bridge vs `2017-04-02` in the fixture)

That confirmed two separate facts:

1. The earlier zero-score failure was partly a metric identity bug, because the
   scorer treated provenance-specific `source_id` differences as fact identity.
2. The bridge-backed retrieval path disagrees with the fixture on medication
   closure, but the later blast-radius audit showed the disagreement is
   upstream of graph lookup: the chunked export has no closed medication rows
   to preserve.

The metric bug was fixed in commit `9e80f9b`, but that fix does not repair the
underlying interval-source mismatch.

### Why this affects decay directly

The temporal weighting code in
`packages/am-temporal-kg/src/lib/time.ts` computes distance as:

```ts
export const temporalDistanceMicros = (
  queryUs: bigint,
  startUs: bigint,
  endUs?: bigint,
): number => {
  if (queryUs < startUs) {
    return Number(startUs - queryUs);
  }
  if (endUs !== undefined && queryUs > endUs) {
    return Number(queryUs - endUs);
  }
  return 0;
};
```

And the retrieval procedure in
`packages/am-temporal-kg/src/procedures/retrieve.ts` applies that distance to
the half-life weight:

```ts
const temporalDistance = temporalDistanceMicros(
  asOfUs,
  edge.validFromUs,
  edge.validToUs ?? undefined,
);
const temporalWeight = Math.pow(2, -temporalDistance / Math.max(halfLifeMicros, 1));
```

If `edge.validToUs` is missing, the call becomes `temporalDistanceMicros(asOfUs,
startUs, undefined)`. For any query date at or after `validFromUs`, the
distance becomes `0`, so the temporal weight is `1.0` for every configured
half-life. In that state, the half-life knob is mathematically disconnected
from the historical prescription rows it is supposed to separate.

## Investigation Steps

### Step 1: one-task forensic

Completed during Phase 5. The worktree has:

- `experiments/healthcare/exp1A_temporal_retrieval/diagnose_arm6.py`

That script was used to localize the original all-zero pilot result to metric
identity, while also capturing the STOP-date mismatch on a real task.

### Step 2: count the blast radius

Completed on 2026-04-24 with:

- script: `scripts/check_healthcare_stop_date_blast_radius.py`
- project: `synthea-scale-mid-fhirfix`
- input: `/root/embedded-exports`
- summary: `experiments/healthcare/results/stop_date_blast_radius_summary.json`
- mismatches: `experiments/healthcare/results/stop_date_blast_radius_mismatches.csv`

Result:

- chunks scanned: `145`
- medication rows seen: `59,799`
- medication rows with non-null `STOP`: `0`
- closed rows available for exact graph-edge inspection: `0`

This means the temporal graph cannot preserve medication STOP dates for this
dataset snapshot because the chunked export feeding the backfill does not carry
any medication STOP dates.

Local source sampling also supports this. The source directory named by the
manifest exists at:

`G:\My Drive\kubuntu\agentic-memory\big-healtcare-data\synthetic-data\fhir-output1`

In a 200-file sample from that directory, `612` `MedicationRequest` resources
had `authoredOn`, but `0` had `dispenseRequest.validityPeriod.end`, `0` had
`dispenseRequest.validityPeriod.start`, and `0` had dosage timing
`boundsPeriod.end`. The sampled resources use the STU3 shape already described
in `src/agentic_memory/healthcare/fhir_loader.py`: a standalone `Medication`
resource followed by a `MedicationRequest` with `status: active` and
`authoredOn`, but no explicit end date.

The closed medication intervals in Exp 1A fixtures therefore come from
`SyntheaQAGenerator._infer_sequential_medication_intervals()`, not from raw
FHIR STOP dates. That inference treats a later same-family medication start as
superseding the previous open-ended row for benchmark construction only.

### Step 3: closure-confirmed subset

Only do this after deciding how to repair the temporal input. The current
export has no closed medication claims, so there is no full-corpus
closure-confirmed subset to sample from yet.

Subset rule:

- gold has closed `valid_to` in both fixture and graph
- at least one historical distractor has confirmed `valid_to < as_of` in the
  graph

If that subset shows real half-life separation after repair, the missing
closure data was swallowing the decay signal. If it remains flat after repair,
then decay itself is the more likely weak link.

## Appendix A: Quantitative Evidence From Exp 1A Phase 5 Rerun

This appendix records the post-fix rerun that followed commit `9e80f9b`
(`Fix Exp 1A metric identity; drop valid_to from fact identity and record
bridge-ingestion STOP-date caveat`).

### Rerun scope

- experiment: `Exp 1A`
- family: `supersession`
- tasks: `100` total
- snapshots: `2012-06-30`, `2016-06-30`
- arms: `hard_overlap`, `hard_overlap_decay_tiebreak`, `soft_decay_only`,
  `soft_decay_hard_overlap`
- half-lives: `30d`, `90d`, `180d`, `1y`, `3y`
- authoritative output directory:
  `/root/agentic-memory-exp1ab-phase5/experiments/healthcare/results/exp1A_supersession_gate`

### Hits@1 by arm and half-life

| Arm | 30d | 90d | 180d | 1y | 3y |
|---|---:|---:|---:|---:|---:|
| `hard_overlap` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `hard_overlap_decay_tiebreak` | 0.22 | 0.22 | 0.22 | 0.22 | 0.22 |
| `soft_decay_only` | 0.13 | 0.13 | 0.12 | 0.11 | 0.11 |
| `soft_decay_hard_overlap` | 0.22 | 0.22 | 0.21 | 0.20 | 0.20 |

Equivalent hit counts out of `100` tasks:

- `hard_overlap`: `100/100` at every half-life
- `hard_overlap_decay_tiebreak`: `22/100` at every half-life
- `soft_decay_only`: `13/100`, `13/100`, `12/100`, `11/100`, `11/100`
- `soft_decay_hard_overlap`: `22/100`, `22/100`, `21/100`, `20/100`, `20/100`

### Interpretation

Three separate signals matter here:

1. `hard_overlap = 1.00` confirms the fixture, scorer, and point-in-time
   overlap logic are now behaving coherently after the metric fix.
2. `soft_decay_only ≈ 0.12` is near-random ordering, so decay without an
   overlap gate is not surfacing the gold reliably on this rerun slice.
3. `hard_overlap_decay_tiebreak` and `soft_decay_hard_overlap` are both flat
   across the full `30d` to `3y` sweep. That flatness is exactly what we would
   expect if the bridge is presenting many historical prescriptions as
   open-ended, because the temporal distance for those rows collapses to `0`
   regardless of half-life.

The important conclusion is not "decay is weak." The stronger and more
defensible conclusion is: **until STOP-date fidelity is verified, the half-life
sweep is not an interpretable measurement of decay behavior.**

### Why the flatness is a signature

Given the code above:

- missing `validToUs` means the row is treated as open-ended
- any `as_of >= valid_from` then yields temporal distance `0`
- temporal weight becomes `1.0` for all half-lives

So a nearly flat `30d` vs `3y` table is not just compatible with missing STOP
dates; it is a predicted signature of that failure mode.

### Current decision

Do not treat the current Exp 1A bridge-backed half-life sweep as a verdict on
decay quality. The immediate fix is not a graph-edge lookup fix; it is an
interval-source decision. Either:

- teach the export/backfill path to apply the same family-local supersession
  inference used by the Exp 1A fixture, then regenerate `/root/embedded-exports`
  and rerun temporal backfill
- or explicitly keep that inference out of the temporal graph and limit Exp 1A
  claims to the hard-overlap fixture/arm behavior until a clinically stronger
  medication-closure source is available

For the current Exp 1A decay question, the first option is the only path that
makes the bridge-backed half-life sweep interpretable on the existing synthetic
dataset.
