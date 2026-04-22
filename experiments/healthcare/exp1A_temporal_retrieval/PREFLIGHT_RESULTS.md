# Exp 1A Preflight Results

- Project: `synthea-scale-mid-fhirfix`
- Repo root: `/root/agentic-memory`
- Run date: `2026-04-22T06:58:22`
- Overall: `FAIL`

## task_wellformed

- Status: `FAIL`
- Summary: 61 well-formedness violations were found across 1250 tasks.
- Details:
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00000 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00001 gold does not overlap as_of=2012-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00018 gold does not overlap as_of=1963-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00020 gold does not overlap as_of=1981-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00022 gold does not overlap as_of=2006-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00027 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00037 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00038 gold does not overlap as_of=2012-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00041 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00042 gold does not overlap as_of=2012-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00043 gold does not overlap as_of=2013-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00046 gold does not overlap as_of=1999-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00055 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00056 gold does not overlap as_of=2012-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00062 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00063 gold does not overlap as_of=2010-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00067 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00070 gold does not overlap as_of=2008-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00071 gold does not overlap as_of=2012-06-30
  - retrospective_state:EXP1A-RETROSPECTIVE-STATE-00073 gold does not overlap as_of=2015-06-30

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

