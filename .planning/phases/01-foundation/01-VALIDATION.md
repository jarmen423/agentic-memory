---
phase: 1
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-20
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.0+ (configured in pyproject.toml) |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `pytest tests/ -m unit -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -m unit -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | Embedding ABC | unit | `pytest tests/test_embedding.py -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 0 | EntityExtraction | unit | `pytest tests/test_entity_extraction.py -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 0 | Config validation | unit | `pytest tests/test_config_validator.py -x` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 0 | Source registry | unit | `pytest tests/test_registry.py -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 0 | Base ABC | unit | `pytest tests/test_base.py -x` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | EmbeddingService dispatch | unit | `pytest tests/test_embedding.py -x` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | Dimensions per provider | unit | `pytest tests/test_embedding.py -x` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 1 | Config validator raises | unit | `pytest tests/test_config_validator.py -x` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 1 | SOURCE_REGISTRY labels | unit | `pytest tests/test_registry.py -x` | ❌ W0 | ⬜ pending |
| 1-03-02 | 03 | 1 | build_embed_text prefix | unit | `pytest tests/test_base.py::test_build_embed_text -x` | ❌ W0 | ⬜ pending |
| 1-03-03 | 03 | 1 | ABC enforcement | unit | `pytest tests/test_base.py::test_abc_enforcement -x` | ❌ W0 | ⬜ pending |
| 1-04-01 | 04 | 1 | KnowledgeGraphBuilder compat | unit | `pytest tests/test_graph.py -x` | ✅ | ⬜ pending |
| 1-05-01 | 05 | 1 | CLI commands registered | unit | `pytest tests/test_cli.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_embedding.py` — EmbeddingService unit tests (mock all API clients)
- [ ] `tests/test_entity_extraction.py` — EntityExtractionService unit tests (mock Groq)
- [ ] `tests/test_config_validator.py` — dimension mismatch validation tests
- [ ] `tests/test_registry.py` — source registry label resolution tests
- [ ] `tests/test_base.py` — ABC enforcement, `build_embed_text`, `node_labels()` method tests

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All three Neo4j vector indexes created cleanly | Foundation goal | Requires running Neo4j instance | Run `pytest tests/integration/` after `docker-compose up` |
| Existing `code` module ingestion still works | Backward compat | Integration — touches live DB | Run `python -m codememory.cli code-ingest --dry-run` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
