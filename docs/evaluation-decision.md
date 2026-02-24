# Integration Decision Memo (PR6/PR7)

## Status

- Date: 2026-02-24
- Decision state: Interim (no fresh benchmark run completed yet)
- Recommended default: `mcp_native`
- Optional path: `skill_adapter` (pending parity evidence)

## Decision

Until benchmark parity evidence exists, Agentic Memory documentation should
recommend **MCP-native integration by default**. The skill-adapter workflow is
documented as an optional path for teams that prefer shell/script-driven
operations, but it is not first-class yet.

## Evidence Available Today

No new benchmark execution results were produced in this PR. This PR adds the
evaluation harness required to run that comparison and record a decision.

- Benchmark task set: [evaluation/tasks/benchmark_tasks.json](../evaluation/tasks/benchmark_tasks.json)
- Metrics schema: [evaluation/schemas/benchmark_results.schema.json](../evaluation/schemas/benchmark_results.schema.json)
- Run scaffold script: [evaluation/scripts/create_run_scaffold.py](../evaluation/scripts/create_run_scaffold.py)
- Summary script: [evaluation/scripts/summarize_results.py](../evaluation/scripts/summarize_results.py)
- Decision template: [evaluation/templates/decision_memo_template.md](../evaluation/templates/decision_memo_template.md)
- Skill-adapter workflow doc: [evaluation/skills/skill-adapter-workflow.md](../evaluation/skills/skill-adapter-workflow.md)

## Promotion Criteria

Promote `skill_adapter` to first-class only after benchmark runs show parity
against `mcp_native` on:

1. Success rate
2. Latency
3. Token cost
4. Retries
5. Operator steps

If parity is not met, keep `mcp_native` as recommended default and keep
`skill_adapter` optional.
