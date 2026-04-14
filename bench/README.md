# Retrieval Benchmark Harness

This harness exists to compare replayed retrieval quality and latency across
multiple retrieval modes:

- baseline first-stage retrieval
- temporal / structural retrieval
- baseline + learned rerank
- temporal / structural + learned rerank

The current fixture is still conversation/research-oriented because it grew out
of the phase 9 temporal retrieval work, but the reporting now captures the
rerank-oriented metrics needed for the shared retrieval layer.

## Python Retrieval Eval

The repo now has a separate Python gold-query evaluation harness:

- `python bench/run_eval.py --backend smoke --profile smoke --smoke-gate`
- `python bench/run_eval.py --backend live --profile gold`

Use this for real retrieval metrics against labeled queries:

- `Recall@10`
- `Recall@Pool`
- `MRR@10`
- `NDCG@10`
- `Success@5`
- p50 / p95 latency
- rerank applied / fallback / abstention rates

Fixture roots:

- `bench/fixtures/eval/`
- `bench/results/eval/`

The older TypeScript harness below remains the temporal replay benchmark.

## Required Environment

- `STDB_BINDINGS_MODULE`
- `STDB_URI`
- `STDB_MODULE_NAME`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`

Optional:

- `STDB_TOKEN`
- `STDB_CONFIRMED_READS`
- `AM_RERANK_ENABLED`
- `AM_RERANK_MODEL`
- `AM_RERANK_TIMEOUT_MS`
- `AM_RERANK_MAX_TOKENS_PER_DOC`
- `AM_RERANK_ABSTAIN_THRESHOLD`
- `AM_RERANK_CLIENT_NAME`
- `COHERE_API_KEY`

## Input Format

The scripts accept a mixed JSONL file. The committed smoke fixture lives at:

- `bench/fixtures/smoke-traces.jsonl`

Supported row types:

- `conversation_relation`
- `research_claim`
- `research_relation`
- `query`

`build_temporal_kg.ts` ignores `query` rows.

Optional `query` fields:

- `high_stakes`: when `true`, rerank evaluation records an abstention when the
  top rerank score falls below `AM_RERANK_ABSTAIN_THRESHOLD`

## Commands

```bash
python bench/run_eval.py --backend smoke --profile smoke --smoke-gate
python bench/run_eval.py --backend live --profile gold
npm run bench:build-temporal -- --input bench/fixtures/smoke-traces.jsonl
npm run bench:run-queries -- --input bench/fixtures/smoke-traces.jsonl
npm run bench:report -- --input bench/results/phase-09-raw.jsonl
```

If this checkout's `node_modules` were installed under WSL/Linux, run the benchmark entrypoints from WSL as well. A mixed-platform `esbuild` install will fail under native Windows `tsx`.

## Reports

The report generator writes:

- `bench/results/phase-09-report.md`
- `bench/results/phase-09-report.json`

The raw query-runner rows are written to:

- `bench/results/phase-09-raw.jsonl`

## Reported Metrics

The raw query runner now emits per-query metrics for:

- latency and token estimates per mode
- hit rank, `MRR@10`, `NDCG@10`, `Success@5`, and `Recall@10`
- temporal fallback usage
- rerank applied / fallback / abstention state

The report generator aggregates those metrics across the replay set.

## Token Heuristic

Token estimation stays aligned with the repo convention:

- `int(words * 1.3)`

The measurement is taken on the final formatted retrieval payload text, not raw edge counts.

## Real Traces vs Smoke Fixture

The committed smoke fixture is only for local verification of the harness wiring.

Real benchmark conclusions should come from replayed real traces exported from conversation and research traffic, not from the smoke fixture.
