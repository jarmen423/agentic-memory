# Exp 1A Preflight Diagnostic

- Project: `synthea-scale-mid-fhirfix`
- Run date: `2026-04-22T06:24:51`
- Outcome: stop before Phase 3+ because at least one Phase 2 gate failed.

## Failed Assertions

### non_overlap_fraction

- Failure: Literal written non-overlap rule fails; the benchmark spec is internally inconsistent.
- Likely root cause:
  - The written Phase 2 assertion conflicts with the Exp 1A task design. A correct time-sliced gold answer must be active at `as_of`, but the current assertion asks for the opposite.
- Proposed fix:
  - Change the check to require non-boundary anchors or a material share of same-family distractors outside `as_of`, rather than requiring the gold interval itself to exclude `as_of`.
- Evidence:
  - literal_non_overlap_rate=0.000 (0/500)
  - design_consistent_non_boundary_rate=1.000 (500/500)
  - The generated fixtures intentionally make the gold fact active at as_of; otherwise time-sliced retrieval would not have a well-defined correct answer.
  - This failure indicates a written-spec contradiction, not a generator bug: the prompt/design text says gold should not contain as_of, while the task families and scoring rules require the gold fact to be active at as_of.

### predicate_presence

- Failure: Temporal predicate inventory does not match the written Exp 1A preflight contract.
- Likely root cause:
  - The temporal graph currently contains `PRESCRIBED`, `DIAGNOSED_WITH`, `OBSERVED`, and `UNDERWENT`, but not `HAS_CONDITION` and not a dedicated dose-change predicate. The Phase 2 expectation is ahead of the current data model.
- Proposed fix:
  - Either relax the assertion to the predicates that actually exist, or backfill/add the missing predicate semantics before continuing.
- Evidence:
  - available_predicates=['DIAGNOSED_WITH', 'OBSERVED', 'PRESCRIBED', 'UNDERWENT']
  - missing_core_predicates=['HAS_CONDITION']
  - present_dose_predicates=[]
  - Current temporal graph exposes PRESCRIBED/DIAGNOSED_WITH/OBSERVED/UNDERWENT, but not HAS_CONDITION and not any dedicated dose-change predicate. That means the written Phase 2 expectation is ahead of the current graph shape.

