# Exp 1A / Exp 1B Orientation Notes

## Bug Mapping

- **ISSUES.md section 2.1 - overlapping intervals neutralize decay.** `packages/am-temporal-kg/src/lib/time.ts:35-45` returns temporal distance `0` when `as_of` is inside an edge interval, and `packages/am-temporal-kg/src/procedures/retrieve.ts:102-106` converts that to `temporalWeight = 1.0`. The old generator selects active facts in `experiments/healthcare/qa_generator.py:423-466`, so many positives live in the no-decay regime.
- **ISSUES.md section 2.2 - half-life invariance.** The old half-life variants are configured in `experiments/healthcare/exp1_temporal_decay.py:68-73`, but if the relevant rows have temporal distance `0`, changing the half-life cannot change their edge weights. That explains why `24h` and `168h` can become identical.
- **ISSUES.md section 2.3 - predicate-filter survival problem.** The old runner calls `TemporalBridge.retrieve(...)` for top-K patient-neighborhood rows and only then filters rows to `DIAGNOSED_WITH`, `HAS_CONDITION`, or `PRESCRIBED` in `experiments/healthcare/exp1_temporal_decay.py:125-195`. The benchmark can therefore score empty candidate lists even when relevant facts exist outside the top-K.
- **ISSUES.md section 2.4 - set answers scored like single answers.** `experiments/healthcare/eval_runner.py:90-160` supports medication tasks with multiple ground-truth medications but still computes MRR and Hits@K from the first matching item. Precision, recall, and F1 exist, but the old headline path did not treat the set answer shape as primary.
- **ISSUES.md section 2.5 - brittle predicate proxy.** `experiments/healthcare/exp1_temporal_decay.py:73-78` hard-codes predicate strings and silently filters out anything else. A graph backfill that changes predicate names can look like retrieval failure instead of a schema mismatch.

## Reusable Helpers

- `SyntheaQAGenerator` in `experiments/healthcare/qa_generator.py` is still the right extension point for deterministic task generation.
- Reusable data loaders include `_iter_records_of_type`, `_load_conditions_by_patient`, `_load_medications_by_patient`, `_load_condition_patients_by_code`, `_load_medication_patients_by_code`, and `_load_encounter_providers_by_patient`.
- `SyntheaQAGenerator.save_tasks` and `SyntheaQAGenerator.load_tasks` should be reused for fixture persistence.
- `EvalResult`, `_percentile`, and result-writing helpers in `experiments/healthcare/eval_runner.py` can be reused, but new Exp 1A metric helpers should be pure functions rather than overloading the old `score_temporal_task` behavior.

## Open Assumptions

- Verify on the VM whether the full corrected export contains enough repeated same-family medication intervals for supersession and regimen-change tasks.
- Verify whether medication descriptions alone are enough for dose families, or whether the temporal graph carries better structured dose data.
- Verify graph predicate names against the live `synthea-scale-mid-fhirfix` project before long runs.
- Verify the canonical full export path on the VM before generating fixtures.

## Gate Check

When `temporalDistanceMicros` returns `0` for every candidate whose interval overlaps `as_of`, the decay formula multiplies each such edge by `1.0` no matter what half-life is configured. If all relevant candidates are currently active, a `30d` half-life and a `1095d` half-life produce the same relative weights for those candidates, so soft-decay variants become mathematically equivalent on the rows that matter. Exp 1A must therefore include tasks with same-family candidates outside the anchor interval and must preflight that half-life changes can actually move at least one top-1 result.
