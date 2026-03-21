---
phase: "01"
plan: "01"
subsystem: core
tags: [registry, connection, neo4j, config, pydantic]
dependency_graph:
  requires: []
  provides:
    - codememory.core.registry (SOURCE_REGISTRY, register_source)
    - codememory.core.connection (ConnectionManager)
    - codememory.config (modules, extraction_llm, entity_types, gemini, nemotron sections)
  affects:
    - all future ingestion pipelines (use register_source + ConnectionManager)
    - all future embedding services (read modules config)
    - all future entity extraction (read extraction_llm config)
tech_stack:
  added:
    - pydantic>=2.0.0
    - google-genai>=1.0.0
    - groq>=0.10.0
  patterns:
    - TDD (RED/GREEN)
    - Leaf module (no internal imports)
    - Context manager for Neo4j sessions
    - Env var priority hierarchy (env vars > config > defaults)
key_files:
  created:
    - src/codememory/core/__init__.py
    - src/codememory/core/registry.py
    - src/codememory/core/connection.py
    - tests/test_registry.py
    - tests/test_connection.py
  modified:
    - src/codememory/config.py
    - pyproject.toml
decisions:
  - "SOURCE_REGISTRY is a module-level dict (leaf module, zero internal imports) — all other modules import from here"
  - "ConnectionManager pool settings match existing KnowledgeGraphBuilder (max_connection_pool_size=50, timeouts 30/60)"
  - "setup_database() runs all 4 DDL statements in one session — 3 vector indexes + entity_unique constraint"
  - "from_config() env var fallbacks mirror existing Config.get_neo4j_config() pattern"
  - "test_from_config uses monkeypatch.delenv() to unset NEO4J_* vars before testing config fallback (env contamination from test_cli.py)"
metrics:
  duration_seconds: 378
  completed_date: "2026-03-21"
  tasks_completed: 2
  files_created: 5
  files_modified: 2
---

# Phase 01 Plan 01: Source Registry, Connection Manager, and Config Extension Summary

Core package foundation with leaf-module source registry, Neo4j connection manager with pool settings and DDL setup, and config extended with modules/extraction_llm/entity_types/gemini/nemotron sections.

## What Was Built

### Task 1: Core package with source registry and connection manager (TDD)

Created the `codememory/core/` subpackage with two leaf modules:

**`src/codememory/core/registry.py`** — Zero-import leaf module. `SOURCE_REGISTRY: dict[str, list[str]] = {}` and `register_source(source_key, labels)`. All ingestion pipelines call `register_source` at import time. Universal label resolution for any registered source.

**`src/codememory/core/connection.py`** — `ConnectionManager` with:
- `__init__` creates `neo4j.GraphDatabase.driver` with pool settings (max_connection_pool_size=50, connection_acquisition_timeout=60, connection_timeout=30, max_transaction_retry_time=30.0)
- `session()` context manager via `with self.driver.session()`
- `setup_database()` runs all 4 DDL statements: code_embeddings, research_embeddings, chat_embeddings vector indexes + entity_unique uniqueness constraint
- `from_config(config)` classmethod with NEO4J_URI/NEO4J_USER/NEO4J_USERNAME/NEO4J_PASSWORD env var overrides
- Module logger via `logging.getLogger(__name__)`

**`src/codememory/core/__init__.py`** — Empty package init; exports added as modules grow.

### Task 2: Config extension and pydantic dependency

Extended `DEFAULT_CONFIG` in `src/codememory/config.py` with:
- `modules`: per-module embedding provider/model/dimensions for code (OpenAI 3072d), web (Gemini 3072d), chat (Gemini 3072d)
- `extraction_llm`: Groq llama-3.3-70b-versatile with GROQ_API_KEY env var fallback
- `entity_types`: ["project", "person", "business", "technology", "concept"]
- `gemini`: api_key with GEMINI_API_KEY env var fallback
- `nemotron`: api_key (NVIDIA_API_KEY) + base_url (https://integrate.api.nvidia.com/v1)

Added to `Config` class: `get_module_config()`, `get_extraction_llm_config()`, `get_gemini_key()`, `get_entity_types()`.

Added to `pyproject.toml` dependencies: `pydantic>=2.0.0`, `google-genai>=1.0.0`, `groq>=0.10.0`.

## Test Results

- 10 new unit tests written and passing (4 registry, 6 connection)
- 18 existing CLI tests still passing
- 59 total unit tests pass (excluding future RED tests for plans 01-02)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed env var contamination in test_from_config**
- **Found during:** Task 1 verification (running all unit tests together)
- **Issue:** `test_cli.py` loads a `.env` file via `python-dotenv` that sets `NEO4J_URI=bolt://from-dotenv:7687`. This env var persisted into `test_from_config`, causing it to use the env var value instead of the config dict value.
- **Fix:** Added `monkeypatch.delenv("NEO4J_URI", raising=False)` and similar for NEO4J_USER/USERNAME/PASSWORD at the start of `test_from_config`.
- **Files modified:** `tests/test_connection.py`
- **Commit:** 1084cae

## Self-Check

- [x] `src/codememory/core/__init__.py` exists
- [x] `src/codememory/core/registry.py` exists with SOURCE_REGISTRY and register_source
- [x] `src/codememory/core/connection.py` exists with ConnectionManager, setup_database, from_config
- [x] `src/codememory/config.py` has modules/extraction_llm/entity_types/gemini/nemotron
- [x] `pyproject.toml` has pydantic, google-genai, groq
- [x] All 10 new unit tests pass
- [x] All 18 existing CLI tests pass

## Commits

| Hash | Message |
|------|---------|
| 1f7c410 | test(01-01): add failing tests for source registry and connection manager |
| 1084cae | feat(01-01): implement source registry and connection manager |
| d4f5657 | feat(01-01): extend config with new sections and add pydantic/google-genai/groq deps |
