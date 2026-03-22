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
| **Quick run command** | `pytest tests/test_web_pipeline.py tests/test_web_tools.py tests/test_cli.py -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_web_pipeline.py tests/test_web_tools.py tests/test_cli.py -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | GraphWriter extensions + deps | unit | `pytest tests/test_web_pipeline.py -x -q` | W0 | pending |
| 2-01-02 | 01 | 1 | Web chunker + crawler | unit | `pytest tests/test_web_pipeline.py -x -q` | W0 | pending |
| 2-02-01 | 02 | 2 | ResearchIngestionPipeline | unit | `pytest tests/test_web_pipeline.py -x -q` | W0 | pending |
| 2-03-01 | 03 | 3 | MCP tools (ingest, search, brave) | unit | `pytest tests/test_web_tools.py -x -q` | W0 | pending |
| 2-03-02 | 03 | 3 | CLI web-init + web-ingest + PDF detection | unit | `pytest tests/test_cli.py -x -q` | exists | pending |
| 2-04-01 | 04 | 4 | FastAPI app + auth middleware + ASGI mount | unit | `pytest tests/test_rest_api.py -x -q` | ❌ W0 | pending |
| 2-04-02 | 04 | 4 | REST endpoints (ingest, search, selectors) | unit | `pytest tests/test_rest_api.py -x -q` | ❌ W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_web_pipeline.py` — GraphWriter extension methods (write_report_node, write_source_node, write_cites_relationship, write_has_chunk_relationship, write_part_of_relationship), chunker (_to_markdown dispatch, chunk_markdown header split + oversize fallback), crawler (crawl_url), ResearchIngestionPipeline (subclass contract, report/finding ingest, chunk dedup with session_id, finding dedup, :PART_OF wiring)
- [ ] `tests/test_web_tools.py` — memory_ingest_research MCP tool, search_web_memory MCP tool, brave_search MCP tool (no-ingest guard, response shape)
- [ ] All tests mock: Neo4j (mock_conn), EmbeddingService (mock_embedder), EntityExtractionService (mock_extractor), httpx.Client — no live connections required
- [ ] `tests/test_rest_api.py` — FastAPI TestClient tests: Bearer auth (403 no header, 200 valid, 401 wrong key), `POST /ingest/research` delegates to pipeline, `GET /search/research` returns results, `GET /ext/selectors.json` unauthenticated, `GET /health` unauthenticated, MCP SSE still reachable at `/mcp/sse`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `web-ingest <url>` ingests live page end-to-end | Success criteria | Requires live Crawl4AI + Neo4j | `docker-compose up && python -m codememory.cli web-ingest https://example.com` |
| `web-ingest <path>.pdf` ingests local PDF | Success criteria | Requires live Neo4j + PDF file | `python -m codememory.cli web-ingest /path/to/doc.pdf` |
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
