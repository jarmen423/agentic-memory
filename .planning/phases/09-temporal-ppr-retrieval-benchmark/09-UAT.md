---
status: complete
phase: 09-temporal-ppr-retrieval-benchmark
source: 09-01-SUMMARY.md, 09-02-SUMMARY.md, 09-03-SUMMARY.md
started: 2026-03-26T23:59:00Z
updated: 2026-04-01T14:35:00Z
---

## Current Test

number: 5
name: Deterministic Fallback When Temporal Path Is Unavailable
expected: |
  With the temporal bridge disabled or misconfigured, conversation and web retrieval
  still return baseline results instead of failing or changing their top-level response shape.
awaiting: none

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
result: pass
reported: "After ingesting a conversation turn for `proj-smoke` with a valid registered `source_key` (`chat_mcp`), `GET /search/conversations?q=phase%208&project_id=proj-smoke` returned the expected `{\"results\":[...]}` payload with the matching turn. During this verification a guard was added so unknown conversation `source_key` values now fail fast instead of silently writing nodes without the `:Turn` label."

### 5. Deterministic Fallback When Temporal Path Is Unavailable
expected: With the temporal bridge disabled or misconfigured, conversation and web retrieval still return baseline results instead of failing or changing their top-level response shape
result: pass
reported: "Added explicit bridge-unavailable coverage alongside existing temporal-failure tests. `tests/test_web_tools.py::test_search_web_memory_falls_back_when_temporal_bridge_unavailable` and `tests/test_am_server.py::test_search_conversations_bridge_unavailable_falls_back` both passed, alongside the existing failure-path fallback tests."

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
