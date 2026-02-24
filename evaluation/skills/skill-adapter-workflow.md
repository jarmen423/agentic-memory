# Skill Adapter Workflow (Optional Path)

This document defines the optional `skill_adapter` workflow used in PR6 benchmark comparisons.

## Scope

The adapter path is shell/script-driven and should be measured against `mcp_native` for:

- Success rate
- Latency
- Token cost
- Retries
- Operator steps

## Expected Operation Set

- `status`
- `index`
- `search`
- `deps`
- `impact`
- `serve`
- `health`

## Usage Rules During Benchmarking

1. Run the same benchmark task prompts for both workflows.
2. Use the same repo snapshot and environment for both runs.
3. Record retries and manual interventions as operator steps.
4. Mark task `failed` when expected output cannot be produced.
5. Attach short evidence notes for each result row.

## Promotion Rule

The adapter becomes first-class only after parity evidence is captured in benchmark results and decision memo.
