# Exp 1A Preflight Diagnostic

- Project: `synthea-scale-mid-fhirfix`
- Run date: `2026-04-22T06:58:22`
- Outcome: stop before Phase 3+ because at least one Phase 2 gate failed.

## Failed Assertions

### task_wellformed

- Failure: 61 well-formedness violations were found across 1250 tasks.
- Likely root cause:
  - The failure is localized to the `retrospective_state` family: those tasks encode a year-level yes/no answer, but the current Phase 2 contract requires every gold interval to overlap `as_of`. Negative retrospective tasks therefore fail by design, not because the interval-valued families are malformed.
- Proposed fix:
  - Treat this as a Phase 1 design repair for `retrospective_state`: either regenerate that family so its gold representation overlaps `as_of`, or remove/defer the family until it has an evaluation contract that matches its yes/no semantics.
- Evidence:
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

