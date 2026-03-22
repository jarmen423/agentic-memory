---
phase: 02-web-research-core
plan: 02
subsystem: web-research
tags: [pipeline, ingestion, neo4j, embeddings, entity-extraction, dedup, tdd]
dependency_graph:
  requires:
    - src/codememory/core/base.py
    - src/codememory/core/graph_writer.py
    - src/codememory/core/embedding.py
    - src/codememory/core/entity_extraction.py
    - src/codememory/core/registry.py
    - src/codememory/web/chunker.py
  provides:
    - ResearchIngestionPipeline
    - _ingest_report
    - _ingest_finding
    - _chunk_content_hash
    - source registration (deep_research_agent, web_crawl4ai)
  affects:
    - MCP tools (02-03)
    - CLI web-ingest (02-03)
    - REST API (02-04)
tech_stack:
  added: []
  patterns:
    - TDD red-green
    - MERGE on composite key (session-scoped chunk dedup)
    - Global content_hash for finding dedup
    - Entity-enriched embeddings via build_embed_text
    - Source registration at module import
key_files:
  created:
    - src/codememory/web/pipeline.py
  modified:
    - src/codememory/web/__init__.py
    - tests/test_web_pipeline.py
decisions:
  - "Chunk content_hash encodes (session_id:chunk_index:text) via sha256 so MERGE on (source_key, content_hash) implements CONTEXT.md Chunk dedup key of (session_id, chunk_index)"
  - "Finding content_hash is sha256(text) alone — global dedup, not session-scoped"
  - "Report parent has embedding_model=None and no embedding field per CONTEXT.md (metadata-only)"
  - "Entity extraction called once per document; entities propagated to all chunks/findings"
metrics:
  duration_minutes: 8
  completed_date: 2026-03-21
  tasks_completed: 1
  files_changed: 3
---

# Phase 02 Plan 02: ResearchIngestionPipeline Summary

ResearchIngestionPipeline with two-branch ingest routing: Report parent + embedded Chunk children with session-scoped dedup; Finding nodes with global content-hash dedup, Source MERGE, and CITES relationships.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for ResearchIngestionPipeline | 4f25454 | tests/test_web_pipeline.py |
| 1 (GREEN) | ResearchIngestionPipeline implementation | 0033b7a | pipeline.py, web/__init__.py |

## What Was Built

### ResearchIngestionPipeline (src/codememory/web/pipeline.py)

`ResearchIngestionPipeline` subclasses `BaseIngestionPipeline` with `DOMAIN_LABEL = "Research"`.

**Constructor:** Takes `ConnectionManager`, `EmbeddingService`, `EntityExtractionService`. Builds a `GraphWriter` internally.

**`ingest(source)`:** Routes on `source["type"]` to `_ingest_report` or `_ingest_finding`. Raises `ValueError` on unknown type.

**`_ingest_report(source)`:**
1. Extract entities from full content (one LLM call via `EntityExtractionService.extract()`)
2. Write Report parent node via `write_report_node()` — no text, no embedding (`embedding_model=None`)
3. Normalize to markdown via `_to_markdown(RawContent(...))`, chunk via `chunk_markdown()`
4. For each chunk: compute `_chunk_content_hash(session_id, chunk_index, text)` → `build_embed_text` → `embed` → `write_memory_node(["Memory","Research","Chunk"], props)`
5. Wire `write_has_chunk_relationship()` (Report → Chunk) and `write_part_of_relationship()` (Chunk → Report)
6. Wire entity relationships (`ABOUT`/`MENTIONS`) on all chunks
7. Recursively call `_ingest_finding()` for any inline findings in `source["findings"]`

**`_ingest_finding(source)`:**
1. Extract entities
2. Compute `content_hash = sha256(text)` — text-only, global dedup
3. `build_embed_text` → `embed`
4. `write_memory_node(["Memory","Research","Finding"], props)`
5. For each citation: `write_source_node(url)` then `write_cites_relationship(...)`
6. Wire entity relationships

**`_chunk_content_hash(session_id, chunk_index, text)`:** `sha256(f"{session_id}:{chunk_index}:{text}")` — session-scoped so same text from different sessions produces different Chunk nodes.

**`_content_hash(text)`:** `sha256(text)` — text-only, global dedup so the same finding found in multiple sessions is stored once.

**Source registration at import:** `register_source("deep_research_agent", ["Memory","Research","Finding"])` and `register_source("web_crawl4ai", ["Memory","Research","Chunk"])` called at module level.

### Updated __init__.py (src/codememory/web/__init__.py)

Added `ResearchIngestionPipeline` import and export to `__all__`.

### Tests (tests/test_web_pipeline.py)

11 new tests added (31 total, all pass):
- `test_pipeline_subclass_contract` — ABC inheritance + DOMAIN_LABEL
- `test_ingest_unknown_type_raises_value_error` — ValueError on bad type
- `test_ingest_report_flow` — write_report_node + write_memory_node + HAS_CHUNK + PART_OF counts
- `test_ingest_report_no_embedding_on_parent` — embedding_model=None, no "embedding" key on report props
- `test_ingest_report_writes_part_of` — PART_OF called N times with correct project/session IDs
- `test_chunk_content_hash_includes_session_id` — different session_ids → different chunk hashes
- `test_finding_content_hash_is_text_only` — same text, different sessions → identical content_hash
- `test_finding_content_hash_deterministic` — sha256(text) matches expected hash
- `test_ingest_finding_flow` — Finding labels, write_source_node, write_cites_relationship, matching content_hash
- `test_ingest_finding_no_citations` — empty citations → no source/cites calls
- `test_source_registration` — SOURCE_REGISTRY has both entries

## Deviations from Plan

None — plan executed exactly as written. The TDD tests and implementation in the plan spec were followed precisely. All behavior, dedup semantics, and relationship patterns match CONTEXT.md locked decisions.

## Self-Check: PASSED

Files exist:
- FOUND: src/codememory/web/pipeline.py (365 lines, >= 120 minimum)
- FOUND: tests/test_web_pipeline.py

Commits exist:
- FOUND: 4f25454 (RED tests)
- FOUND: 0033b7a (GREEN implementation)

All 31 tests pass in tests/test_web_pipeline.py.
Acceptance criteria verified: subclass contract, source registration, grep patterns all confirmed.
