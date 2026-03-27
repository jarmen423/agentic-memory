# 09-03 Summary: Benchmark Harness and Reporting

**Date:** 2026-03-26  
**Status:** Complete

## Delivered

- Updated root `package.json` with benchmark entrypoints:
  - `bench:build-temporal`
  - `bench:run-queries`
  - `bench:tokens`
  - `bench:report`
- Added benchmark scripts:
  - `bench/build_temporal_kg.ts`
  - `bench/run_queries.ts`
  - `bench/measure_tokens.ts`
  - `bench/report_results.ts`
- Added docs:
  - `bench/README.md`
- Added a committed smoke fixture:
  - `bench/fixtures/smoke-traces.jsonl`

## Behavior

- `build_temporal_kg.ts` replays mixed JSONL traces into SpacetimeDB using the same helper introduced in `09-01`.
- `run_queries.ts` executes a baseline replay query pass and a temporal PPR query pass for the same query corpus.
- Token estimation remains aligned with the repo heuristic:
  - `int(words * 1.3)`
- `report_results.ts` writes:
  - `bench/results/phase-09-report.md`
  - `bench/results/phase-09-report.json`

## Verification

- `npm run typecheck`
- `npx tsx bench/build_temporal_kg.ts --help`
- `npx tsx bench/run_queries.ts --help`
- `npx tsx bench/measure_tokens.ts --help`
- `npx tsx bench/report_results.ts --help`

Notes:

- Workspace typecheck passed.
- The `tsx` help-path verification had to be run from WSL because this checkout currently has Linux `esbuild` binaries in `node_modules`, so Windows `tsx` execution fails with an `@esbuild/linux-x64` vs `@esbuild/win32-x64` mismatch.
- No real trace benchmark was run yet; the committed smoke fixture is for harness verification only.
