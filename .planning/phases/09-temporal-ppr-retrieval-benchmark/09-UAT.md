---
status: testing
phase: 09-temporal-ppr-retrieval-benchmark
source: 09-01-SUMMARY.md, 09-02-SUMMARY.md, 09-03-SUMMARY.md
started: 2026-03-26T23:59:00Z
updated: 2026-03-27T06:10:00Z
---

## Current Test

number: 5
name: Deterministic Fallback When Temporal Path Is Unavailable
expected: |
  With the temporal bridge disabled or misconfigured, conversation and web retrieval
  still return baseline results instead of failing or changing their top-level response shape.
awaiting: user response

## Tests

### 1. Build Temporal KG From Smoke Fixture
expected: From WSL, `npm run bench:build-temporal -- --input bench/fixtures/smoke-traces.jsonl` succeeds against the local SpacetimeDB module and prints non-zero temporal write counts
result: pass
reported: "Replay succeeded against the server on 3333 and printed nodes_written=8, edges_written=4, evidence_written=4."

### 2. Run Temporal Query Pass on Smoke Fixture
expected: From WSL, `npm run bench:run-queries -- --input bench/fixtures/smoke-traces.jsonl` writes `bench/results/phase-09-raw.jsonl` and includes rows where the temporal path returns non-empty results without crashing
result: pass
reported: "After fixing `withTx` table access and the edge scoring path, the smoke query runner completed with `fallback_count: 0`, `temporal_result_count: 4` on both queries, and `temporal_consistent: true`."

### 3. Generate Benchmark Report
expected: From WSL, `npm run bench:report -- --input bench/results/phase-09-raw.jsonl` writes both `bench/results/phase-09-report.md` and `bench/results/phase-09-report.json`
result: pass
reported: "Report generation succeeded and wrote both phase-09-report.md and phase-09-report.json."

### 4. Temporal-First Conversation Retrieval
expected: With `am-server` running against a populated local SpacetimeDB module, `GET /search/conversations` still returns `{\"results\": [...]}` while honoring an `as_of` query parameter and using the temporal path when seeds exist
result: blocked
blocked_by: prior-phase
reason: "After Neo4j came up, the live route returned `{\"results\":[]}` for `proj-smoke`. The benchmark smoke fixture populated SpacetimeDB, but there are no corresponding conversation turns in Neo4j for hydration, so this did not validate live temporal-ranked conversation retrieval."

### 5. Deterministic Fallback When Temporal Path Is Unavailable
expected: With the temporal bridge disabled or misconfigured, conversation and web retrieval still return baseline results instead of failing or changing their top-level response shape
result: pending

## Summary

total: 5
passed: 3
issues: 0
pending: 1
skipped: 0
blocked: 1

## Gaps
