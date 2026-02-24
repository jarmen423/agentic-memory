# Evaluation Harness

This package contains PR6 benchmark artifacts for comparing `mcp_native` and
`skill_adapter` integration workflows.

## Files

- `tasks/benchmark_tasks.json`: benchmark dataset (16 representative tasks).
- `schemas/benchmark_results.schema.json`: metrics capture schema.
- `templates/decision_memo_template.md`: decision memo template.
- `skills/skill-adapter-workflow.md`: optional skill-adapter workflow doc.
- `scripts/create_run_scaffold.py`: generates a runnable benchmark results file.
- `scripts/summarize_results.py`: computes aggregates and recommendation signals.

## Metrics Captured

- Success rate
- Latency (ms)
- Token cost (USD)
- Retries
- Operator steps

## Quick Start

```bash
# 1) Create a run scaffold with all task/workflow pairs
python3 evaluation/scripts/create_run_scaffold.py

# 2) Fill in each result entry after executing tasks
#    (status, success, latency_ms, token_cost_usd, retries, operator_steps)

# 3) Compute aggregate metrics and decision signal
python3 evaluation/scripts/summarize_results.py \
  --input evaluation/results/latest-run.json \
  --output-md evaluation/results/latest-run-summary.md
```

## Current Recommendation

Current policy is documented in [docs/evaluation-decision.md](../docs/evaluation-decision.md):
use `mcp_native` as default until parity evidence promotes `skill_adapter`.
