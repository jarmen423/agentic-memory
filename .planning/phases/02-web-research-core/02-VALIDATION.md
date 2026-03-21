---
phase: 2
slug: web-research-core
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-21
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio + pytest-mock |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `pytest tests/test_web_pipeline.py tests/test_web_tools.py -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_web_pipeline.py tests/test_web_tools.py -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 0 | GraphWriter extensions | unit | `pytest tests/test_web_pipeline.py -x -q` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 0 | Web pipeline + chunker | unit | `pytest tests/test_web_pipeline.py -x -q` | ❌ W0 | ⬜ pending |
| 2-02-01 | 02 | 0 | MCP tools | unit | `pytest tests/test_web_tools.py -x -q` | ❌ W0 | ⬜ pending |
| 2-02-02 | 02 | 1 | EmbeddingService + memory_ingest | unit | `pytest tests/test_web_pipeline.py tests/test_web_tools.py -x -q` | ❌ W0 | ⬜ pending |
| 2-03-01 | 03 | 1 | Crawl4AI integration | unit | `pytest tests/test_web_pipeline.py::test_to_markdown_dispatch -x -q` | ❌ W0 | ⬜ pending |
| 2-03-02 | 03 | 1 | Dedup logic | unit | `pytest tests/test_web_pipeline.py::test_finding_dedup -x -q` | ❌ W0 | ⬜ pending |
| 2-04-01 | 04 | 1 | brave_search MCP tool | unit | `pytest tests/test_web_tools.py::test_brave_search_response tests/test_web_tools.py::test_brave_search_no_ingest -x -q` | ❌ W0 | ⬜ pending |
| 2-04-02 | 04 | 1 | search_web_memory MCP tool | unit | `pytest tests/test_web_tools.py::test_search_web_memory -x -q` | ❌ W0 | ⬜ pending |
| 2-05-01 | 05 | 2 | CLI web-init + web-ingest | unit | `pytest tests/test_cli.py::test_web_init_cmd tests/test_cli.py::test_web_ingest_cmd -x -q` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_web_pipeline.py` — `ResearchIngestionPipeline` subclass contract, report/finding/chunk ingest, `_to_markdown` dispatch, `_chunk_markdown` header split + oversize fallback, dedup logic, `GraphWriter` extension methods (`write_report_node`, `write_cites_relationship`, `write_has_chunk_relationship`, `write_source_node`)
- [ ] `tests/test_web_tools.py` — `memory_ingest_research` MCP tool, `search_web_memory` MCP tool, `brave_search` MCP tool (no-ingest guard, response shape)
- [ ] All tests mock: Neo4j (`mock_conn`), `EmbeddingService` (`mock_embedder`), `EntityExtractionService` (`mock_extractor`), `httpx.AsyncClient` — no live connections required

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `web-ingest <url>` ingests live page end-to-end | Success criteria | Requires live Crawl4AI + Neo4j | `docker-compose up && python -m codememory.cli web-ingest https://example.com` |
| `search_web_memory "query"` returns relevant results | Success criteria | Requires seeded data in Neo4j | After web-ingest, run MCP tool call, verify similarity > 0.7 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
