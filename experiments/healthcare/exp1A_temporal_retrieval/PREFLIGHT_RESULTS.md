# Exp 1A Preflight Results

- Project: `synthea-scale-mid-fhirfix`
- Repo root: `/root/agentic-memory-exp1ab-verify`
- Run date: `2026-04-22T08:00:04`
- Overall: `PASS`

## task_wellformed

- Status: `PASS`
- Summary: All 1000 tasks have at least two same-family candidates, gold overlaps as_of, and as_of is not on a gold boundary.

## distractor_gap_fraction

- Status: `PASS`
- Summary: The distractor-gap rule passes.
- Details:
  - gap_rate=1.000 (500/500)
  - A task counts as gapped only when at least one same-family distractor has valid_to < as_of or valid_from > as_of.

## predicate_presence

- Status: `PASS`
- Summary: All required temporal predicates are present.
- Details:
  - available_predicates=['DIAGNOSED_WITH', 'OBSERVED', 'PRESCRIBED', 'UNDERWENT']
  - missing_required_predicates=[]
  - optional_present_predicates=['OBSERVED', 'UNDERWENT']

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

