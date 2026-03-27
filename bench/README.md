# Phase 9 Benchmark Harness

This harness exists to compare the current baseline retrieval payload against temporal PPR retrieval on replayed traces.

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

## Input Format

The scripts accept a mixed JSONL file. The committed smoke fixture lives at:

- `bench/fixtures/smoke-traces.jsonl`

Supported row types:

- `conversation_relation`
- `research_claim`
- `research_relation`
- `query`

`build_temporal_kg.ts` ignores `query` rows.

## Commands

```bash
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

## Token Heuristic

Token estimation stays aligned with the repo convention:

- `int(words * 1.3)`

The measurement is taken on the final formatted retrieval payload text, not raw edge counts.

## Real Traces vs Smoke Fixture

The committed smoke fixture is only for local verification of the harness wiring.

Real benchmark conclusions should come from replayed real traces exported from conversation and research traffic, not from the smoke fixture.
