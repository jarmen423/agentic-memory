# Common Pitfalls

**Domain:** Knowledge Graph & Agent Memory Systems
**Researched:** 2026-03-20
**Confidence:** MEDIUM (based on training data and existing codebase analysis)

## Critical Pitfalls

System failures, data corruption, or requiring rewrites. Must prevent.

### Pitfall 1: Embedding Model Mixing in Unified Database
**What goes wrong:** Using OpenAI (3072d) + Gemini (768d) embeddings in same Neo4j vector index

**Why it happens:**
- No validation when modules use different embedding models
- Unified database seems simpler
- Config allows different models without warning

**Consequences:**
- Neo4j vector index requires uniform dimensionality
- Runtime errors: `Invalid vector dimension: expected 3072, got 768`
- Silent failures: Wrong results returned (meaningless similarity scores)
- Cannot distinguish which chunks use which model

**Prevention:**
- **Option A (Recommended):** Separate databases per embedding model
- **Option B:** Namespace with separate indexes: `code_embedding` (3072d), `web_embedding` (768d)
- **Option C:** Standardize on single embedding model for all modules
- Add config validation: fail if mixing models in unified database

**Detection:**
- Vector search throws dimension mismatch errors
- Neo4j logs show index errors
- `codememory init` or module config change

**Phase mapping:** Critical for Foundation Phase - must be designed into schema from start.

---

### Pitfall 2: Naive Deduplication Data Loss
**What goes wrong:** URL-based or content-hash-only deduplication loses temporal and provenance information

**Why it happens:**
- Simple dedup logic: "if URL exists, skip"
- No consideration for content changes over time
- Treating web pages like immutable code files

**Consequences:**
- Lose "when did I first see this?" information
- Cannot track content evolution (page updated but same URL)
- Source attribution lost (same content from multiple sources)
- Automated research can't detect trends or changes

**Prevention:**
- Use composite deduplication keys: `(content_hash, source_url, crawl_date, context)`
- Store content versions as separate nodes, link with `PREVIOUS_VERSION` relationships
- Track ingestion metadata: first_seen, last_updated, version_count
- Support "re-crawl and diff" workflow

**Detection:**
- Users report "I know this changed but graph shows old version"
- Automated research misses content updates
- Search returns stale information

**Phase mapping:** Web Research Memory ingestion pipeline (Phase 1).

---

### Pitfall 3: Context Window Pollution
**What goes wrong:** Conversation retrieval floods agent context with irrelevant historical mentions from unrelated sessions

**Why it happens:**
- No session/conversation boundary filtering in queries
- Semantic search alone: "auth" matches discussions from 6 months ago
- No temporal decay or recency bias
- User identity not enforced in multi-user scenarios

**Consequences:**
- Agent confused by irrelevant context
- Privacy leaks (user A sees user B's conversations)
- Poor retrieval quality (old low-relevance results outrank recent high-relevance)
- Wasted context window tokens

**Prevention:**
- Add conversation scoping: filter by session_id, conversation_id, user_id
- Implement temporal decay in retrieval scoring (recent > old)
- Add conversation coherence filtering
- Support scoped retrieval: "search current conversation" vs "search all history"
- Store conversation graph structure: message → reply_to → message

**Detection:**
- Agent responses reference wrong conversation context
- Users say "that's from a different conversation"
- Privacy complaints

**Phase mapping:** Must be designed into Conversation Memory architecture from start (Phase 2).

---

### Pitfall 4: Rate Limiting Cascade Failures
**What goes wrong:** Web research pipelines hit rate limits, retry aggressively, get blocked, then retry harder causing exponential backoff failure or permanent IP bans

**Why it happens:**
- No rate limiting awareness before sending requests
- Retry logic uses exponential backoff but no circuit breaker
- Multiple concurrent research sessions share same IP/API quota
- No graceful degradation when limits hit

**Consequences:**
- IP addresses get permanently banned
- API keys get revoked
- Research pipelines stall completely
- Cascading failures when retries consume all quota

**Prevention:**
- Implement token bucket or leaky bucket rate limiter BEFORE requests
- Add per-source rate limit tracking (Brave API: X req/day, domain crawls: Y req/min)
- Use circuit breaker pattern: after N failures, stop trying for cooldown period
- Support manual override: "pause all research", "cancel session"
- Log rate limit headers and adjust limits proactively

**Detection:**
- HTTP 429 (Too Many Requests) errors in logs
- API responses with "rate limit exceeded" messages
- Sudden drop in successful ingestions
- External service blocks/bans

**Phase mapping:** Critical for Web Research Memory scheduled research (Phase 1).

---

### Pitfall 5: Extraction Quality Degradation Blindness
**What goes wrong:** Web content extraction silently degrades over time as sites change HTML structure, garbage accumulates in knowledge graph

**Why it happens:**
- No quality validation after extraction
- Parsers fail silently when site structure changes
- No diff detection between re-crawls
- No human-in-the-loop validation for automated research

**Consequences:**
- Knowledge graph fills with malformed content
- Search returns gibberish (navigation menus, ads, boilerplate)
- Users lose trust in automated research
- Manual cleanup required but hard to identify bad data

**Prevention:**
- Validate extracted content: minimum text length, coherence checks, boilerplate detection
- Store extraction metadata: `extractor_version`, `extraction_confidence_score`
- Add quality flags: `extraction_quality: high|medium|low|failed`
- Implement extraction diffing: flag wildly different re-crawl content for review
- Support manual validation workflow
- Log extraction failures explicitly (don't store empty/garbage nodes)

**Detection:**
- Search results contain navigation menus, footers, cookie banners
- Content is all caps, all links, or extremely short
- Users report "this URL used to work but now returns garbage"

**Phase mapping:** Build into Web Research Memory extraction pipeline from start (Phase 1).

---

### Pitfall 6: Incremental Update Inconsistency
**What goes wrong:** Incremental updates create orphaned nodes, duplicate relationships, or break graph integrity because update logic differs from initial ingestion logic

**Why it happens:**
- Separate code paths for initial ingestion vs incremental updates
- No transaction boundaries around multi-step updates
- Graph queries use different matching logic than inserts
- Relationship creation isn't idempotent

**Consequences:**
- Graph accumulates duplicate nodes with slight variations
- Orphaned nodes never get cleaned up
- Relationship counts grow unbounded
- Queries return duplicate results
- Neo4j constraint violations

**Prevention:**
- Use MERGE not CREATE in all graph operations (idempotent upserts)
- Wrap multi-step updates in explicit transactions
- Share code path: initial ingestion should call same functions as incremental updates
- Add unique constraints on composite keys in Neo4j schema
- Implement reconciliation: periodic checks for orphaned nodes
- Test incremental updates explicitly: ingest same content twice, verify single node

**Detection:**
- Neo4j constraint violations in logs
- Graph queries return duplicate results for same content
- Node counts grow faster than ingestion events
- Orphaned nodes visible in graph browser

**Phase mapping:** Critical for Conversation Memory incremental message updates (Phase 2) and Web Research re-crawling.

---

### Pitfall 7: Privacy Boundary Violations in Multi-User Memory
**What goes wrong:** Conversation memory from one user leaks into another user's agent context because graph queries don't filter by user/session boundaries

**Why it happens:**
- User identity not modeled in graph schema
- Queries don't include user_id filters by default
- Shared embedding space doesn't segregate user data
- Cached results served to wrong users

**Consequences:**
- Critical privacy violation (PII leakage between users)
- Regulatory compliance failures (GDPR, CCPA)
- User trust destroyed
- Legal liability

**Prevention:**
- Model user identity as first-class graph entity: `User → owns → Conversation`
- Add user_id to every conversation-related node
- Implement query-time filtering: all retrieval must filter by user_id
- Use separate vector indices per user (or add user_id metadata to vectors)
- Add integration tests: verify user A cannot retrieve user B's conversations
- Support data export/deletion per user (GDPR right to erasure)

**Detection:**
- User reports seeing content they didn't input
- Privacy audit fails
- Graph queries show cross-user relationships

**Phase mapping:** Must be designed into Conversation Memory schema from start (Phase 2).

---

## Moderate Pitfalls

Performance degradation, user friction, or maintenance burden.

### Pitfall 8: Embedding Generation Bottleneck
**What goes wrong:** Sequential embedding generation becomes critical path bottleneck, making initial ingestion prohibitively slow

**Prevention:**
- Use batch embedding APIs (OpenAI supports up to 2048 texts per batch)
- Implement concurrent request pool with rate limiting
- Consider local embedding models for bulk operations (sentence-transformers)
- Add progress tracking and ETA

**Phase mapping:** Affects all modules. Consider optimization in Phase 1 and 2.

---

### Pitfall 9: Stale Content Detection Failure
**What goes wrong:** Web research pipelines re-crawl URLs but don't detect when content is stale, deleted, or paywalled

**Prevention:**
- Track HTTP status codes: 404 (deleted), 410 (gone), 402/403 (paywall)
- Store last-modified headers and ETags
- Implement content diffing: only re-index if content changed
- Add tombstone nodes for deleted content (preserve provenance)
- Detect paywalls: check for common paywall patterns in HTML

**Phase mapping:** Web Research Memory re-crawling logic (Phase 1).

---

### Pitfall 10: Query Explosion in Large Graphs
**What goes wrong:** Graph traversal queries that work fine on small graphs become exponentially slow as graph grows

**Prevention:**
- Add max depth to all variable-length patterns: `MATCH (a)-[*..5]-(b)`
- Create indexes on frequently-queried properties (user_id, timestamp, content_hash)
- Use LIMIT on all queries that could return large result sets
- Profile queries with Neo4j EXPLAIN/PROFILE
- Add query timeouts at application level

**Phase mapping:** Design indexes into schema from start (all phases).

---

### Pitfall 11: Conversation Boundary Ambiguity
**What goes wrong:** System can't reliably determine where one conversation ends and another begins

**Prevention:**
- Require explicit conversation identifiers in import format
- Support multiple conversation models: thread_id, session_id, channel_id
- Add conversation start/end markers
- Detect conversation boundaries heuristically but allow manual override
- Store conversation metadata: participants, started_at, ended_at, platform

**Phase mapping:** Conversation Memory schema design (Phase 2).

---

### Pitfall 12: Scheduled Research Runaway
**What goes wrong:** Automated daily research schedules accumulate, overlap, and consume all resources without user realizing

**Prevention:**
- Implement schedule registry with status dashboard
- Add resource quotas: max crawls per schedule, max storage per research session
- Auto-pause schedules after N consecutive failures
- Support schedule expiration: "research this for 30 days"
- Add cost estimation: "this schedule will use ~X API calls/day"

**Phase mapping:** Web Research Memory scheduled research feature (Phase 1).

---

## Minor Pitfalls

User confusion, minor bugs, or edge case failures.

### Pitfall 13: PDF Extraction Inconsistency
**What goes wrong:** PDF parsing works for some PDFs but fails silently for others (scanned PDFs, complex layouts, non-English text)

**Prevention:**
- Detect PDF type: text-based vs scanned
- Use OCR for scanned PDFs (tesseract integration)
- Validate extracted text quality (length, character distribution)
- Store PDF extraction metadata: method_used, confidence_score

**Phase mapping:** Web Research Memory PDF ingestion (Phase 1).

---

### Pitfall 14: Timestamp Timezone Confusion
**What goes wrong:** Timestamps stored without timezone information cause incorrect query results

**Prevention:**
- Always use timezone-aware timestamps (UTC preferred)
- Normalize all timestamps to UTC at ingestion
- Store original timezone as metadata if relevant
- Add timestamp validation: reject timestamps in future or distant past

**Phase mapping:** All modules - enforce in base schema design.

---

### Pitfall 15: Metadata Explosion
**What goes wrong:** Every node gets dozens of metadata fields "just in case", making schema unmanageable

**Prevention:**
- Define core metadata schema per entity type
- Use separate nodes for extended metadata (don't inline)
- Implement metadata namespacing: `web:crawl_date` vs `conv:message_sent_at`
- Review metadata usage periodically - remove unused fields

**Phase mapping:** Schema governance process for all modules.

---

### Pitfall 16: Error Handling Opacity
**What goes wrong:** Ingestion failures happen silently - users think content was indexed but it failed

**Prevention:**
- Return ingestion summary: X succeeded, Y failed, Z skipped
- Store failed ingestion attempts with error details
- Add `codememory status` command showing recent failures
- Support retry: `codememory retry-failed`

**Phase mapping:** All ingestion pipelines - build in from start.

---

### Pitfall 17: Embedding Dimension Mismatch
**What goes wrong:** Switching embedding models without migrating existing vectors causes dimension mismatch

**Prevention:**
- Store embedding dimensions with each vector
- Validate new vectors match index dimensions before insert
- Fail fast with clear error message on mismatch
- Support embedding migration: re-embed all content when model changes

**Phase mapping:** Config validation in all modules using embeddings.

---

### Pitfall 18: Relationship Direction Confusion
**What goes wrong:** Graph queries fail or return incomplete results because relationship directions were inconsistent at creation time

**Prevention:**
- Document relationship direction conventions
- Use semantic names: `CONTAINS`, `REPLIED_TO`, `CRAWLED_FROM`
- Make direction obvious: source→target, parent→child, before→after
- Add schema validation tests

**Phase mapping:** Schema design for all modules.

---

## Phase-Specific Warnings

| Phase | Likely Pitfall | Mitigation |
|-------|---------------|------------|
| **Web Research Memory - Initial Crawling** | Pitfall 2 (naive deduplication), Pitfall 4 (rate limiting), Pitfall 5 (extraction quality) | Implement composite deduplication keys, circuit breaker rate limiting, extraction quality validation |
| **Web Research Memory - Scheduled Research** | Pitfall 12 (schedule runaway), Pitfall 4 (rate limiting cascade) | Schedule registry with quotas, resource monitoring, auto-pause on failures |
| **Web Research Memory - PDF Ingestion** | Pitfall 13 (PDF extraction inconsistency) | PDF type detection, OCR integration, extraction validation |
| **Conversation Memory - Initial Schema** | Pitfall 3 (context pollution), Pitfall 7 (privacy violations), Pitfall 11 (boundary ambiguity) | Design user/session boundaries into schema, conversation coherence scoring, explicit conversation identifiers |
| **Conversation Memory - Incremental Updates** | Pitfall 6 (update inconsistency) | Shared code paths for insert/update, idempotent MERGE operations, transaction boundaries |
| **Conversation Memory - Retrieval** | Pitfall 3 (context pollution), Pitfall 10 (query explosion) | Temporal decay, conversation scoping, query depth limits, indexes |
| **Shared Infrastructure - Embedding Strategy** | Pitfall 1 (embedding mixing), Pitfall 17 (dimension mismatch) | Separate databases per embedding model, validation on config change |
| **All Modules - Initial Ingestion** | Pitfall 8 (embedding bottleneck), Pitfall 16 (error opacity) | Batch embeddings, async processing, ingestion status reporting |
| **All Modules - Production Monitoring** | Pitfall 5 (extraction quality degradation), Pitfall 10 (query explosion) | Quality metrics, slow query monitoring, extraction confidence scoring |

## Existing Codebase Warnings

Based on CONCERNS.md analysis, avoid repeating these mistakes:

### Web Research Module Must Avoid:
1. **Silent embedding failures** - Code module has zero-vector fallback; web module should fail explicitly
2. **Text truncation without warning** - Implement chunking not truncation
3. **Single-threaded embedding** - Build batching from start, not as optimization
4. **Session management issues** - Prevent connection pool exhaustion

### Conversation Module Must Handle:
1. **Debounce cache memory leak** - Implement cache expiration from start
2. **Circuit breaker indefinite open** - Better recovery mechanism
3. **Thread safety** - Add locking for concurrent updates

## Sources

**Confidence Level: MEDIUM**

Research based on:
- Training data knowledge of common knowledge graph and RAG system patterns (as of January 2025)
- Analysis of existing codebase patterns in D:\code\agentic-memory (CONCERNS.md, PROJECT.md)
- Established best practices for web crawling, graph databases, and conversation systems
- Domain expertise in distributed systems, data engineering, and AI/ML pipelines

**Limitations:**
- No access to 2026-specific sources or recent research papers
- Unable to verify with Context7 or current official documentation (tools auto-denied)
- Relying on established patterns which may have evolved

**Validation needed:**
- Neo4j vector search best practices for current version (5.18+)
- Google Gemini embedding API specifics and limitations
- Brave Search API rate limits and patterns
- Crawl4AI and agent-browser specific gotchas

---

*Research completed: 2026-03-20*
*Recommendation: Validate critical pitfalls (1-7) prevention strategies before Phase 1 implementation*
