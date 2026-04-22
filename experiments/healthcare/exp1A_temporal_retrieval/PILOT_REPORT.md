# Exp 1A Pilot Report

## Pilot Scope

- Dataset: `mid_fhirfix`
- Families: `supersession`, `regimen_change`, `recurring_condition`, `dose_escalation`
- Snapshot buckets: `2012-06-30`, `2016-06-30`
- Tasks per family/snapshot bucket: `25`
- Arms: `random_in_family`, `always_newest`, `hard_overlap`, `hard_overlap_decay_tiebreak`, `soft_decay_only`, `soft_decay_hard_overlap`
- Half-lives: `30d`, `90d`, `180d`, `1y`, `3y`

## Task Coverage

- `supersession` / `2012-06-30` sampled tasks: `25`
- `supersession` / `2016-06-30` sampled tasks: `25`
- `regimen_change` / `2012-06-30` sampled tasks: `25`
- `regimen_change` / `2016-06-30` sampled tasks: `25`
- `recurring_condition` / `2012-06-30` sampled tasks: `25`
- `recurring_condition` / `2016-06-30` sampled tasks: `25`
- `dose_escalation` / `2012-06-30` sampled tasks: `25`
- `dose_escalation` / `2016-06-30` sampled tasks: `25`

## Operational Findings

- No result rows returned zero candidates.
- `results.jsonl` was left VM-only because the authoritative file is about `25 MB`, which is larger than the review-artifact threshold for this branch update.
- Authoritative VM-only `results.jsonl` path:
  `/root/agentic-memory-exp1ab-phase5/experiments/healthcare/results/exp1A_pilot/results.jsonl`
- SHA-256 of the authoritative VM-only `results.jsonl`:
  `56daac0c9c9624db1d914df9688e898ef0e00e553b358b38eddce41aa2df438c`

## Half-Life Watchlist

- Record the earlier `halflife_sensitivity` preflight signal (`3/20` top-1 flips between `30d` and `1095d`) here once the authoritative VM pilot finishes so arm 6 vs arm 3 can be compared against that early warning.
- `hard_overlap_decay_tiebreak` Hits@1 range across configured half-lives: 0.0000 to 0.0000
- `soft_decay_only` Hits@1 range across configured half-lives: 0.0000 to 0.0000
- `soft_decay_hard_overlap` Hits@1 range across configured half-lives: 0.0000 to 0.0000

## Runtime Estimate

- Approximate wall-clock at current mean latency: `4.04` hours for the configured sweep.
