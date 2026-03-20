# Codebase Concerns

**Analysis Date:** 2026-03-20

## Tech Debt

**GitHub API Enrichment Not Implemented:**
- Issue: The git graph module has a TODO for GitHub API enrichment features (pull requests, issue metadata)
- Files: `src/codememory/ingestion/git_graph.py` (line 444)
- Impact: Git graph feature is incomplete; missing PR/issue metadata that could enhance context tracking
- Fix approach: Implement GitHub API client integration when GitHub credentials available; add feature flag to gate incomplete feature

**Weak OpenAI API Error Recovery:**
- Issue: OpenAI API failures silently return zero-vector embeddings, masking failures
- Files: `src/codememory/ingestion/graph.py` (line 362-364)
- Impact: Semantic search degrades silently without clear warning; users may not notice embedding generation failures
- Fix approach: Add explicit logging when fallback occurs; consider tracking failure metrics; expose in status command

**Embedded Credentials in Interactive Prompts:**
- Issue: CLI interactively prompts users to enter Neo4j and OpenAI credentials which could be logged in shell history
- Files: `src/codememory/cli.py` (lines 183-226)
- Impact: Credentials may leak to shell history, `.bash_history`, or process logs
- Fix approach: Use getpass module for password input; warn users; prefer env var approach; document secure setup patterns

**Session Management Pattern Not Enforced:**
- Issue: Neo4j sessions are sometimes reused across multiple operations within a single `with` block
- Files: `src/codememory/ingestion/graph.py` (multiple locations where session.run is called repeatedly in loops)
- Impact: Connection pool exhaustion if operations are slow; fewer connections available for concurrent operations
- Fix approach: Consider session per operation or connection pooling tuning; profile under load

**Text Truncation Silent Failure:**
- Issue: Code text longer than 24,000 chars is silently truncated with "...[TRUNCATED]" suffix
- Files: `src/codememory/ingestion/graph.py` (lines 337-343)
- Impact: Large files lose content without user awareness; embeddings are incomplete; truncated code fragments may be semantically broken
- Fix approach: Log warnings at INFO level; split large files into chunks; consider recursive chunking for large functions

## Known Bugs

**Debounce Cache Memory Leak in Watcher:**
- Symptoms: Continuous watch may accumulate file paths in `_debounce_cache` indefinitely
- Files: `src/codememory/ingestion/watcher.py` (lines 43, 74-77)
- Trigger: Watch many files for extended period (days/weeks); paths remain in cache forever
- Workaround: Restart watcher periodically; cache only stores timestamps so memory footprint is modest (~100 bytes per file)
- Fix approach: Add time-based cache expiration; remove entries older than 1 hour

**Circuit Breaker May Stay Open Indefinitely:**
- Symptoms: If Neo4j connection fails 5+ times, circuit stays open for 30s even if connection recovers mid-window
- Files: `src/codememory/ingestion/graph.py` (lines 32-77)
- Trigger: Database restart during indexing or watch; connection test fails but DB comes back online
- Workaround: Manually restart codememory watch/index command
- Fix approach: Add health check on each operation before attempting; consider resetting on successful partial operations

**Partial Annotation Application Loss:**
- Symptoms: Manual annotation may update some tool calls but others could be lost if DB constraint violated
- Files: `src/codememory/telemetry.py` (lines 253-307)
- Trigger: Race condition if annotation applied during concurrent tool usage
- Workaround: None apparent
- Fix approach: Use transaction isolation; wrap apply_annotation in serializable transaction

## Security Considerations

**Plaintext Credential Storage in Config:**
- Risk: OpenAI API key and Neo4j password stored in `.codememory/config.json` in plaintext
- Files: `src/codememory/config.py` (lines 87-98)
- Current mitigation: File permissions on `.codememory/` directory (not enforced by code)
- Recommendations:
  - Make plaintext storage explicit with warning in init wizard
  - Support external credential store integration (env vars only path)
  - Add validation that `.codememory/` has appropriate perms (0700)
  - Document .gitignore requirement for config file

**Environment Variable Override Confusion:**
- Risk: Users may have `OPENAI_API_KEY` or `NEO4J_PASSWORD` in shell history/environment; unaware credentials are in use
- Files: `src/codememory/config.py` (lines 157-171)
- Current mitigation: Preference order documented in comments
- Recommendations:
  - Explicit logging when env vars override config values
  - Show active config values (redacted) on `codememory status` and `codememory serve`
  - Warn if credentials in both config and env (potential confusion)

**No Input Validation on Graph Queries:**
- Risk: File paths and queries accepted from CLI without escaping; could allow Cypher injection
- Files: `src/codememory/cli.py` (multiple); `src/codememory/server/tools.py` (multiple)
- Current mitigation: Uses parameterized queries (safe from injection)
- Recommendations:
  - Add path normalization/validation before any graph lookup
  - Document Cypher injection protections for maintainers
  - Restrict max query depth/breadth in impact analysis

## Performance Bottlenecks

**Embedding Generation is Single-Threaded:**
- Problem: Each code entity (file, function, class) gets an OpenAI embedding call sequentially
- Files: `src/codememory/ingestion/graph.py` (lines 320-364)
- Cause: OpenAI API rate limiting and simple sequential architecture
- Impact: Initial indexing very slow (1-2 seconds per entity)
- Improvement path:
  - Batch embedding requests (OpenAI supports batch input)
  - Add concurrent request pool with rate limiter
  - Consider local embedding model (sentence-transformers) as fallback

**Full Repo Scan on Watch Initial Start:**
- Problem: `codememory watch` re-indexes all files even if they haven't changed
- Files: `src/codememory/ingestion/watcher.py` (lines 367-370)
- Cause: Initial scan runs full pipeline even for existing repos
- Impact: Watch startup takes minutes on large repos; blocking before file watching starts
- Improvement path:
  - Skip initial scan if graph already populated with matching file set
  - Use `--no-scan` flag (already available) by default; require explicit scan
  - Implement incremental indexing on startup

**Neo4j Connection Pool Exhaustion:**
- Problem: Default connection pool may be too small for concurrent operations
- Files: `src/codememory/ingestion/graph.py` (lines 150-156)
- Cause: Multiple passes (1-4) each open sessions; parallel file processing may starve pool
- Impact: Timeout errors under concurrent load; slow queries during indexing
- Improvement path:
  - Profile connection pool utilization
  - Add configurable pool size based on repo size
  - Consider connection pool metrics in status command

## Fragile Areas

**Parser Dependency on Tree-Sitter Language Bindings:**
- Files: `src/codememory/ingestion/parser.py`; `src/codememory/ingestion/watcher.py` (lines 218-226)
- Why fragile: Imports tree_sitter bindings inline in two places; if binding missing, module fails to load
- Safe modification:
  - Centralize Tree-Sitter loader in dedicated module
  - Add graceful fallback if binding unavailable
  - Test coverage of missing binding case
- Test coverage: No explicit tests for missing binding scenario

**Watcher Handler State Not Thread-Safe:**
- Files: `src/codememory/ingestion/watcher.py` (lines 24-322)
- Why fragile: `_debounce_cache` dict is mutated across watchdog threads without locking
- Safe modification:
  - Add threading.Lock to debounce operations
  - Ensure builder is thread-safe (likely not; Neo4j driver should be)
- Test coverage: No concurrent event tests

**Config File Format Not Validated on Load:**
- Files: `src/codememory/config.py` (lines 74-85)
- Why fragile: JSONDecodeError caught but partial/malformed configs not rejected; missing keys cause KeyError later
- Safe modification:
  - Validate config schema on load (use pydantic or jsonschema)
  - Test with corrupted/incomplete config files
- Test coverage: No bad config tests

## Scaling Limits

**Current Database Capacity:**
- Neo4j vector search index (vector embeddings) has no size limit mentioned
- Default embedding dimension: 3072 (text-embedding-3-large)
- Current capacity: Not known; depends on Neo4j deployment size
- Scaling path: Document Neo4j sizing for 10k, 100k, 1M entities; provide tuning guide

**Telemetry SQLite Database Growth:**
- Files: `src/codememory/telemetry.py`
- Issue: Tool call telemetry appended indefinitely; no archival/cleanup policy
- Current capacity: Unbounded growth in `telemetry.sqlite3`
- Scaling path:
  - Add retention policy (keep 30/90 days)
  - Implement automatic cleanup on rotation
  - Document expected DB size growth

**Memory Usage During Indexing:**
- Problem: Full Pass 2 (entity parsing) loads all function/class code into memory
- Impact: Large repos (>500 entities) may exhaust memory on resource-constrained systems
- Scaling path:
  - Stream entities rather than loading all at once
  - Profile memory during indexing of large repos
  - Add memory usage to metrics output

## Dependencies at Risk

**OpenAI SDK Version Pinning:**
- Files: `pyproject.toml`
- Risk: OpenAI SDK API may change between versions; no version constraint specified in observed code
- Impact: Embedding calls could break if SDK major version released with breaking changes
- Migration plan: Pin to specific version range (e.g., `openai>=1.0,<2.0`); test on major updates before upgrading

**Tree-Sitter Language Bindings Maintenance:**
- Files: `src/codememory/ingestion/parser.py`
- Risk: tree_sitter_python, tree_sitter_javascript community-maintained; language grammar may lag language updates
- Impact: New syntax (e.g., Python 3.12 type union syntax) not recognized; parsing fails silently
- Migration plan: Regular test against latest Python/JS versions; consider AST parsing fallback for failed parses

**Neo4j Driver Compatibility:**
- Files: Multiple
- Risk: Neo4j 5.x+ driver API is subject to deprecations; 6.0 may introduce breaking changes
- Impact: Connection failures; unsupported API calls
- Migration plan: Document minimum Neo4j driver version; test against driver beta versions

## Missing Critical Features

**No Incremental Indexing on Startup:**
- Problem: Large repositories require full re-index even if only few files changed
- Blocks: Optimal user experience; users must wait on startup even for minimal changes
- Status: Partial support via `codememory watch --no-scan` but not default behavior

**No Distributed/Multi-Repo Support:**
- Problem: Single `.codememory/config.json` per repo; no way to index multiple repos into shared graph
- Blocks: Monorepo users must maintain separate graphs
- Status: Not designed; architectural limitation

**No Explicit Test of OpenAI Dependency:**
- Problem: Init wizard does not verify OpenAI API key is valid before saving
- Blocks: Users save invalid keys; discover failure only on first search
- Status: Not implemented; should add validation step in init wizard

## Test Coverage Gaps

**Telemetry Store Race Conditions:**
- What's not tested: Concurrent annotation operations; tool calls during annotation application
- Files: `src/codememory/telemetry.py`
- Risk: Annotation data loss or inconsistency under concurrent load
- Priority: Medium (research feature, not production-critical)

**Neo4j Connection Failures:**
- What's not tested: Full circuit breaker lifecycle; recovery after timeout
- Files: `src/codememory/ingestion/graph.py`
- Risk: Circuit breaker behavior unvalidated; may not recover correctly
- Priority: High (affects reliability)

**Large File Edge Cases:**
- What's not tested: Files > 24,000 chars; very large repos (10k+ files)
- Files: `src/codememory/ingestion/graph.py`; `src/codememory/ingestion/watcher.py`
- Risk: Truncation failures; memory exhaustion; timeout failures unknown
- Priority: High (affects production stability)

**Watcher File System Events:**
- What's not tested: Rapid file changes; rename operations; concurrent modifications
- Files: `src/codememory/ingestion/watcher.py`
- Risk: Event queue overflow; missed updates; graph inconsistency
- Priority: Medium (affects watch feature reliability)

**Config Migration:**
- What's not tested: Loading old config format; upgrading between versions
- Files: `src/codememory/config.py`
- Risk: Users upgrading break on version mismatch
- Priority: Low (early stage; no migration history yet)

---

*Concerns audit: 2026-03-20*
