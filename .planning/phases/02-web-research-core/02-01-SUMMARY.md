---
phase: 02-web-research-core
plan: 01
subsystem: web-research
tags: [graph-writer, chunker, crawler, neo4j, crawl4ai, markdownify, pymupdf4llm]
dependency_graph:
  requires: [src/codememory/core/graph_writer.py, src/codememory/core/connection.py]
  provides: [write_report_node, write_source_node, write_cites_relationship, write_has_chunk_relationship, write_part_of_relationship, chunk_markdown, crawl_url]
  affects: [ResearchIngestionPipeline (02-02), MCP tools (02-03), CLI web-ingest (02-03)]
tech_stack:
  added: [crawl4ai>=0.8.0, markdownify>=1.2.0, pymupdf4llm>=1.27.0, httpx>=0.27.0]
  patterns: [MERGE on composite key, lazy import with module-level fallback, TDD red-green]
key_files:
  created:
    - src/codememory/web/chunker.py
    - src/codememory/web/crawler.py
    - tests/test_web_pipeline.py
  modified:
    - src/codememory/core/graph_writer.py
    - src/codememory/web/__init__.py
    - pyproject.toml
decisions:
  - "Module-level imports (try/except) for markdownify and pymupdf4llm so patch() works in tests"
  - "crawl4ai installed at >=0.8.0 (latest 0.8.5 used); CrawlerRunConfig wait_until=networkidle, page_timeout=30000ms"
  - "Overlap implemented as word-count based (overlap_words = int(overlap_tokens / 1.3)) for consistency with _token_count"
metrics:
  duration_minutes: 7
  completed_date: 2026-03-22
  tasks_completed: 2
  files_changed: 6
---

# Phase 02 Plan 01: GraphWriter Extensions and Web Building Blocks Summary

GraphWriter extended with 5 Research schema write methods; content chunker with header-split + recursive fallback; Crawl4AI async wrapper with hard error on failure.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | GraphWriter extensions + package deps | a5378ba | graph_writer.py, pyproject.toml |
| 2 | Content chunker + Crawl4AI wrapper | c3c301e | chunker.py, crawler.py, web/__init__.py |

## What Was Built

### GraphWriter Extensions (src/codememory/core/graph_writer.py)

Five new methods added to the existing `GraphWriter` class:

- `write_report_node(properties)` — MERGE on `(project_id, session_id)` for metadata-only Report parent nodes
- `write_source_node(url, title)` — MERGE on `url` for `Entity:Source` reference nodes
- `write_cites_relationship(finding_source_key, finding_content_hash, source_url, rel_props)` — MERGE `(f)-[r:CITES]->(s)` with ON CREATE SET
- `write_has_chunk_relationship(report_project_id, report_session_id, chunk_source_key, chunk_content_hash, order)` — MERGE `:HAS_CHUNK {order}` from Report to Chunk
- `write_part_of_relationship(chunk_source_key, chunk_content_hash, report_project_id, report_session_id)` — MERGE `(c)-[:PART_OF]->(r)` reverse relationship

### Content Chunker (src/codememory/web/chunker.py)

- `RawContent` dataclass — text, format hint ("markdown"|"html"|"pdf"|"text"), optional path
- `Chunk` dataclass — text, index, total
- `_token_count(text)` — fast approximation: `int(word_count * 1.3)`
- `_to_markdown(content)` — dispatches: markdown/text pass-through, html via markdownify (ATX headings), pdf via pymupdf4llm
- `_split_on_headers(markdown)` — splits on `##` and `###` header boundaries
- `_recursive_split(text, max_tokens=512, overlap_tokens=50)` — word-boundary chunking with overlap
- `chunk_markdown(markdown, max_tokens=512, overlap_tokens=50)` — header-first split with recursive fallback for over-size sections

### Crawl4AI Wrapper (src/codememory/web/crawler.py)

- `crawl_url(url, timeout_ms=30000)` — async, uses `AsyncWebCrawler` with `CrawlerRunConfig(wait_until="networkidle")`
- Handles `MarkdownGenerationResult` object or string return from Crawl4AI
- Raises `RuntimeError` on failure (hard error, no fallback per CONTEXT.md)

### Package Dependencies (pyproject.toml)

Added to project dependencies: `crawl4ai>=0.8.0`, `markdownify>=1.2.0`, `pymupdf4llm>=1.27.0`, `httpx>=0.27.0`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Module-level imports for markdownify and pymupdf4llm**
- **Found during:** Task 2 GREEN phase
- **Issue:** Tests patch `codememory.web.chunker.markdownify` and `codememory.web.chunker.pymupdf4llm` as module-level attributes. The plan specified lazy imports inside the function body which would not be interceptable by the test patches.
- **Fix:** Added module-level `try/except ImportError` imports for both libraries, keeping lazy fallback behavior for production environments where they may not be installed. The function body then uses the module-level names directly.
- **Files modified:** src/codememory/web/chunker.py
- **Commit:** c3c301e

## Decisions Made

1. **Module-level imports with try/except** — markdownify and pymupdf4llm imported at module level with `try/except ImportError` so pytest `patch()` can intercept them. The fallback `None` values are type-ignored since they're only accessed when the format matches.

2. **crawl4ai 0.8.5 used** — installed `crawl4ai>=0.8.0`, resolved to 0.8.5. `CrawlerRunConfig` accepts `wait_until` and `page_timeout` parameters as specified.

3. **Word-count based overlap** — `overlap_words = int(overlap_tokens / 1.3)` mirrors the `_token_count` approximation for consistency. This means the actual word overlap is ~38 words for 50 token overlap setting.

## Self-Check: PASSED

Files exist:
- FOUND: src/codememory/web/chunker.py
- FOUND: src/codememory/web/crawler.py
- FOUND: tests/test_web_pipeline.py

Commits exist:
- FOUND: a5378ba (GraphWriter extensions)
- FOUND: c3c301e (chunker + crawler)

All 20 tests pass in test_web_pipeline.py. All 21 Phase 1 regression tests pass.
