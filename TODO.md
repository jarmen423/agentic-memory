# TODO: Shippable Product Checklist

> **Status:** 0.1.0-alpha (MVP) | **Last Updated:** 2025-02-09
>
> This document tracks all work needed before Agentic Memory can be considered a shippable, production-ready product.

---

## ✅ Completed (2025-02-09)

### Critical (Blocking Release)

- [x] **Complete Parser Implementation** - Ported Tree-sitter entity extraction from legacy scripts
  - [x] Function definition extraction (name, signature, docstring, parameters)
  - [x] Class definition extraction (name, methods, inheritance)
  - [x] Import statement extraction (module dependencies)
  - [x] Function call detection for CALLS relationships
  - [x] Chunk extraction with 4-pass hybrid strategy
  - [x] Contextual prefixing for embeddings
  - [x] Change detection via oHash

- [x] **Implement `get_file_dependencies` in MCP Server**
  - [x] Query graph for IMPORTS relationships (outgoing dependencies)
  - [x] Query graph for reverse IMPORTS (incoming callers)
  - [x] Format results in readable Markdown for LLM consumption
  - [x] Handle files not found in graph gracefully

- [x] **Implement `impact_analysis` Tool**
  - [x] Add `identify_impact()` MCP tool
  - [x] Cypher query for transitive dependencies (blast radius)
  - [x] Return depth-organized results
  - [x] Added `max_depth` parameter

- [x] **Enhanced CLI with Additional Commands**
  - [x] `codememory index <path>` - One-time full pipeline
  - [x] `codememory watch <path>` - Continuous ingestion with initial scan
  - [x] `codememory serve` - MCP server
  - [x] `codememory search <query>` - Test semantic search

### High Priority (User Experience)

- [x] **Environment Configuration Files**
  - [x] Create `.env.example` with all required variables documented
  - [x] Document Neo4j connection parameters with defaults
  - [x] Add OpenAI API key placeholder
  - [x] Include optional variables (logging level, etc.)

- [x] **Docker Deployment**
  - [x] Create `docker-compose.yml` with Neo4j service
  - [x] Create `Dockerfile` for the package
  - [x] Volume mounts for persistence
  - [x] Health checks for Neo4j

- [x] **Watcher Improvements**
  - [x] Incremental file updates (no full re-scans)
  - [x] Debounce for rapid file changes
  - [x] Handle file creation, modification, and deletion
  - [x] Re-parse entities on change
  - [x] Re-create embeddings on change

---

## Remaining Work

### Critical (Blocking Release)

### 1. Testing Infrastructure
**Current state:** No automated tests

- [ ] Add `pytest` configuration
- [ ] Unit tests for parser extraction accuracy
- [ ] Unit tests for Cypher query generation
- [ ] Integration tests with test Neo4j instance
- [ ] Mock OpenAI API for unit tests
- [ ] Test coverage reporting
- [ ] CI/CD pipeline (GitHub Actions or similar)

**Target:** 70%+ code coverage before v1.0

---

### High Priority (User Experience)

### 2. Documentation Completeness

- [ ] Add LICENSE file (currently placeholder text)
- [ ] Create installation troubleshooting guide
- [ ] Document required Neo4j version and configuration (5.18+)
- [ ] Add MCP client configuration examples for:
  - [ ] Claude Desktop
  - [ ] Cursor IDE
  - [ ] Windsurf
  - [ ] Generic HTTP clients
- [ ] Add example usage walkthrough with sample repository
- [ ] Document performance expectations (ingestion speed, query latency)
- [ ] Fix README: Update with actual repository URL

---

### Medium Priority (Reliability)

### 3. Error Handling & Logging

- [ ] Replace remaining bare `except Exception` with specific exception types
- [ ] Implement proper logging configuration (currently just `basicConfig`)
- [ ] Add structured logging with request IDs for MCP server
- [ ] Add retry logic for OpenAI API calls (rate limits, timeouts)
- [ ] Add circuit breaker for repeated Neo4j connection failures
- [ ] User-friendly error messages for common issues (e.g., Neo4j unavailable)

---

### 4. MCP Server Robustness

- [ ] Add connection pooling for Neo4j (currently single global connection)
- [ ] Implement proper server shutdown handling (cleanup resources)
- [ ] Add rate limiting to prevent API abuse
- [ ] Add request/response logging for debugging
- [ ] Implement tool output validation (ensure LLM-readable format)
- [ ] Add OpenAPI/Swagger documentation for HTTP endpoints

---

### 5. Additional Language Support

Current: Python, JavaScript, TypeScript

- [ ] Go support
- [ ] Rust support
- [ ] Java support
- [ ] C/C++ support

---

### Lower Priority (Polish)

### 6. CLI UX Improvements

- [ ] Add progress bars for ingestion (e.g., `tqdm` or `rich`)
- [ ] Better error messages with actionable suggestions
- [ ] Add `codememory status` command to show repository health
- [ ] Add `--verbose` flag for debug output
- [ ] Add `--dry-run` flag to preview changes

---

### 7. Performance Optimization

- [ ] Batch embedding API calls (currently 1-by-1)
- [ ] Implement async ingestion for concurrent file processing
- [ ] Add caching layer for frequently accessed queries
- [ ] Optimize Cypher queries (EXPLAIN/ANALYZE and profile)
- [ ] Add configurable embedding model (small/large tradeoff)
- [ ] Benchmark and document expected performance

---

### 8. Developer Experience

- [ ] Add pre-commit hooks (formatting, linting)
- [ ] Add `ruff` or `black` for code formatting
- [ ] Add `mypy` strict type checking configuration
- [ ] Create contributing guide
- [ ] Add architecture decision records (ADRs) for major choices
- [ ] Create issue and PR templates

---

### 9. Legacy Code Cleanup

- [ ] Remove or move legacy scripts to `legacy/` directory:
  - [ ] `4_pass_ingestion_with_prep_hybridgraphRAG.py`
  - [ ] `5_continuous_ingestion.py`
  - [ ] `5_continuous_ingestion_jina.py`
- [ ] Remove `graphrag_requirements.txt` if no longer needed
- [ ] Consolidate duplicate documentation (AGENTS.md vs README.md)

---

## Release Checklist (v1.0)

### Pre-Release

- [ ] All Critical items complete
- [ ] All High Priority items complete
- [ ] Test on fresh machine (clean install)
- [ ] Test with Docker Compose end-to-end
- [ ] Security audit (check for API key leakage, SQL injection, etc.)
- [ ] Performance testing with repository of 10K+ LOC
- [ ] Documentation review (all examples tested)

### Release

- [ ] Tag version in git (e.g., `v1.0.0`)
- [ ] Build and publish to PyPI
- [ ] Create GitHub release with changelog
- [ ] Announce to relevant communities (MCP, Neo4j, AI agents)

---

## Summary

### What's Now Working (as of 2025-02-09)

| Feature | Status |
|---------|--------|
| Full 4-pass ingestion pipeline | ✅ Complete |
| Tree-sitter parsing (Python, JS, TS) | ✅ Complete |
| Contextual prefixing for embeddings | ✅ Complete |
| Change detection via oHash | ✅ Complete |
| Import graph resolution | ✅ Complete |
| Call graph construction | ✅ Complete |
| Semantic search (vector + keyword) | ✅ Complete |
| File dependency analysis | ✅ Complete |
| Impact analysis (blast radius) | ✅ Complete |
| MCP server with 4 tools | ✅ Complete |
| File watcher (incremental updates) | ✅ Complete |
| CLI with 4 commands | ✅ Complete |
| Docker Compose setup | ✅ Complete |
| Environment configuration | ✅ Complete |

### Remaining Effort

| Priority | Items | Est. Complexity |
|----------|-------|-----------------|
| Critical | 1 (Tests) | High |
| High | 1 (Docs) | Medium-High |
| Medium | 4 (Error handling, more languages, etc.) | Medium |
| Low | 4 (Polish, cleanup) | Low-Medium |

---

## Quick Start (for testing now that core is complete)

```bash
# 1. Start Neo4j
docker-compose up -d neo4j

# 2. Configure environment
cp .env.example .env
# Edit .env with your values

# 3. Install and run
pip install -e .
codememory index /path/to/your/repo

# 4. Start MCP server
codememory serve

# 5. Or watch for changes
codememory watch /path/to/your/repo
```
