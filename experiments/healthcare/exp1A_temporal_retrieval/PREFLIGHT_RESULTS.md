# Exp 1A Preflight Results

- Project: `synthea-scale-mid-fhirfix`
- Repo root: `/root/agentic-memory`
- Run date: `2026-04-22T06:24:51`
- Overall: `FAIL`

## distractor_counts

- Status: `PASS`
- Summary: All 1250 tasks expose at least two same-family options via gold+distractors.

## non_overlap_fraction

- Status: `FAIL`
- Summary: Literal written non-overlap rule fails; the benchmark spec is internally inconsistent.
- Details:
  - literal_non_overlap_rate=0.000 (0/500)
  - design_consistent_non_boundary_rate=1.000 (500/500)
  - The generated fixtures intentionally make the gold fact active at as_of; otherwise time-sliced retrieval would not have a well-defined correct answer.
  - This failure indicates a written-spec contradiction, not a generator bug: the prompt/design text says gold should not contain as_of, while the task families and scoring rules require the gold fact to be active at as_of.

## predicate_presence

- Status: `FAIL`
- Summary: Temporal predicate inventory does not match the written Exp 1A preflight contract.
- Details:
  - available_predicates=['DIAGNOSED_WITH', 'OBSERVED', 'PRESCRIBED', 'UNDERWENT']
  - missing_core_predicates=['HAS_CONDITION']
  - present_dose_predicates=[]
  - Current temporal graph exposes PRESCRIBED/DIAGNOSED_WITH/OBSERVED/UNDERWENT, but not HAS_CONDITION and not any dedicated dose-change predicate. That means the written Phase 2 expectation is ahead of the current graph shape.

## halflife_sensitivity

- Status: `PASS`
- Summary: At least one sampled supersession task changes top-1 between 30d and 1095d.
- Details:
  - sample_size=20
  - changed_top1_count=3
  - unchanged_top1_count=17
  - EXP1A-SUPERSESSION-00004: 30d=('Simvastatin 20 MG Oral Tablet', 664243200000000, None) vs 1095d=None
  - EXP1A-SUPERSESSION-00005: 30d=('Clopidogrel 75 MG Oral Tablet', 864000000000000, None) vs 1095d=None
  - EXP1A-SUPERSESSION-00019: 30d=None vs 1095d=('Acetaminophen 325 MG Oral Tablet', 1306627200000000, None)

