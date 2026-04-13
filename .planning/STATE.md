---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: — Full Multi-Module Memory System with Temporal GraphRAG
current_phase: 16
status: active
last_updated: "2026-04-13T14:23:18Z"
progress:
  total_phases: 16
  completed_phases: 13
  total_plans: 23
  completed_plans: 22
---

# Agentic Memory — Project State

**Last Updated:** 2026-04-13
**Current Phase:** 16
**Phase Status:** Phase 15 complete; Phase 16 locked and active
**Last Session Stopped At:** Phase 15 is complete and archived under `.planning/execution/archive/w15-openclaw-docs-and-private-beta/`. Dogfooding exposed that private-beta documentation did not yet equal a usable whole-stack onboarding flow, so the next active OpenClaw tranche is now Whole-Stack Onboarding. Phase 10 still needs live manual verification from the runbooks, and Phase 11 remains resumable from `.planning/execution/archive/w11-calls/`.

---

## Active Phase

**Phase 16: OpenClaw Whole-Stack Onboarding**

**Next Action:** Execute `w16-openclaw-whole-stack-onboarding` by locking the onboarding contract first, then splitting implementation across plugin UX, local stack/bootstrap cleanup, and docs/troubleshooting consolidation before closing the integration gate.

---

## Branch Strategy

| Branch | Description |
|--------|-------------|
| `main` | Full v1 with temporal GraphRAG plus the active OpenClaw whole-stack onboarding wave |
| `v1-baseline` | Frozen at Phase 5 completion — finish original Phase 6 + 7 here for A/B comparison |

---

## Phase Status

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundation | Complete |
| 2 | Web Research Core | Complete |
| 3 | Web Research Scheduling | Complete (folded into Phase 7) |
| 4 | Conversation Memory Core | Complete |
| 5 | am-proxy (ACP Proxy) | Complete |
| 6 | am-ext (Browser Extension) | Complete |
| 7 | Temporal Schema + Claim Extraction + Research Scheduling | Complete |
| 8 | SpacetimeDB Maintenance Layer | Complete |
| 9 | Temporal PPR Retrieval + Benchmark | Complete |
| 10 | Cross-Module Integration & Hardening | Paused pending manual verification |
| 11 | Code Graph Foundation and Code PPR | Paused with archived `w11-calls` registry |
| 12 | OpenClaw Foundation | Complete |
| 13 | OpenClaw Testing + Dashboard | Complete |
| 14 | OpenClaw Scaling + Packaging | Complete |
| 15 | OpenClaw Docs + Private Beta | Complete |
| 16 | OpenClaw Whole-Stack Onboarding | In Progress |

---

## Completed Work

- [x] Codebase mapped (`.planning/codebase/`)
- [x] Project scope defined (`PROJECT.md`)
- [x] GSD config initialized (`config.json`)
- [x] Research complete (`research/STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md`, `SUMMARY.md`)
- [x] Requirements defined and locked (`PROJECT.md` — Active section)
- [x] Roadmap created (`ROADMAP.md`)
- [x] Package renamed: `codememory` → `agentic-memory`
- [x] CLI command standardized: `codemem` → `codememory`
- [x] Plan 01-01: Source registry, connection manager, config extension (2026-03-21)
- [x] Plan 01-02: EmbeddingService (OpenAI/Gemini/Nemotron) + EntityExtractionService (Groq JSON mode) (2026-03-21)
- [x] Plan 01-03: BaseIngestionPipeline ABC + GraphWriter MERGE patterns + ConfigValidator (2026-03-21)
- [x] Plan 01-04: KnowledgeGraphBuilder adopts BaseIngestionPipeline; web/chat stubs; 5 CLI stub commands; Docker Compose documented (2026-03-21)
- [x] Plan 02-01: GraphWriter Research schema extensions; content chunker (header-split + recursive fallback); Crawl4AI async wrapper; 4 new package deps (2026-03-22)
- [x] Plan 02-02: ResearchIngestionPipeline — report + finding ingest paths; session-scoped chunk dedup; global finding dedup; HAS_CHUNK + PART_OF wiring; source registration (2026-03-21)
- [x] Plan 02-03: MCP tools (memory_ingest_research, search_web_memory, brave_search) and CLI commands (web-init, web-ingest with PDF detection, web-search stub) (2026-03-21)
- [x] Plan 02-04: FastAPI am-server REST foundation — app factory, auth, models, routes/health + routes/research (2026-03-21)
- [x] Phase 02 verified: all 7 checks passed, test suite green (2026-03-21)
- [x] Plan 04-01: Vector index bug fix (768d), fix_vector_index_dimensions() migration, GraphWriter conversation methods (write_session_node, write_has_turn_relationship, write_part_of_turn_relationship), 12 unit tests (2026-03-22)
- [x] Plan 04-02: ConversationIngestionPipeline with role-conditional embedding, session upsert, entity wiring; all 4 chat source keys registered; 22 unit tests (2026-03-22)
- [x] Plan 04-03: REST endpoints POST /ingest/conversation + GET /search/conversations; 3 MCP tools (search_conversations, get_conversation_context, add_message); register_conversation_tools() pattern (2026-03-22)
- [x] Plan 05-01: packages/am-proxy/ standalone package scaffold; ProxyConfig dataclass + load_config() TOML loader; AGENT_CONFIGS registry (claude/codex/gemini/opencode/kiro); pytest conftest fixtures (2026-03-25)
- [x] Plan 05-02: IngestClient fire-and-forget (GC-safe _pending set, silent failure); ACPProxy with full ACP routing table, buffer TTL, turn construction; 22 unit tests (2026-03-25)
- [x] Plan 05-03: cli.py entry point with argparse, Windows ProactorEventLoop policy, setup subcommand; 19 CLI unit tests; 41 total am-proxy tests passing (2026-03-25)
- [x] Phase 05 verified: all 6 success criteria passed, 41/41 tests green (2026-03-25)

---

## Accumulated Context

### Roadmap Evolution

- Phase 11 added: Code Graph Foundation and Code PPR
- Phase 12 added: OpenClaw Foundation
- Phase 13 added: OpenClaw Testing + Dashboard
- Phase 14 added: OpenClaw Scaling + Packaging
- Phase 15 added: OpenClaw Docs + Private Beta

---

## Key Decisions Log

| Decision | Rationale |
|----------|-----------|
| Separate Neo4j per module (:7687/:7688/:7689) | Embedding dimension conflict (OpenAI 3072d vs Gemini 768d) |
| Gemini for web/chat, OpenAI for code | Multimodal support; code module already validated |
| Nvidia Nemotron in v1 | NIM API is OpenAI-compatible — trivial addition via abstraction layer |
| Crawl4AI primary + Vercel agent-browser fallback | agent-browser more efficient than raw Playwright for agent workflows |
| Smart scheduling with LLM variable substitution | Context-aware research — avoids topic repetition, steered by history |
| Set-and-forget conversation capture | Provider-native hooks (Claude Code confirmed); MCP tool as fallback |
| SOURCE_REGISTRY is a leaf module (no internal imports) | Prevents circular dependency issues as all modules import from here |
| ConnectionManager pool settings mirror KnowledgeGraphBuilder | Consistent connection behavior across old and new code |
| test_from_config uses monkeypatch.delenv() for NEO4J_* vars | test_cli.py loads .env which pollutes env vars for subsequent tests |
| EmbeddingService uses gemini-embedding-2-preview | PLAN spec acceptance criteria explicitly requires this model name (RESEARCH.md recommends gemini-embedding-001 GA) |
| EntityExtractionService prompt uses escaped braces {{}} | Python .format() requires literal braces doubled; prevents KeyError on prompt formatting |
| GraphWriter namespace: conditional Cypher branch not None-check | Avoids writing namespace=None on Memory nodes when no namespace provided |
| Gemini MRL: ConfigValidator warns, does not raise, on non-default dims | Gemini supports output_dimensionality override; OpenAI/Nemotron have fixed dims |
| KGB.__init__ creates ConnectionManager internally, calls super().__init__(conn) | Preserves (uri, user, password) caller interface; self.driver = self._conn.driver keeps 300+ internal references intact |
| ingest() wraps run_pipeline() as thin ABC compliance shim | Satisfies ABC without disrupting existing multi-pass pipeline orchestration |
| Output-centric research ingestion (agent output, not source pages) | Source pages are ephemeral agent context; Reports/Findings/Citations are the durable knowledge artifacts |
| REST API (`am-server`) foundation built in Phase 2 | Web research endpoints + auth land in Phase 2 (02-04-PLAN); Phase 4 extends with `/ingest/conversation`. Connectors unblocked sooner. |
| am-proxy: asyncio.call_later TTL for request/response buffer | Per-entry cancel handle prevents unbounded buffer growth; 300s TTL covers longest real tool calls |
| am-proxy uses dataclasses.dataclass for ProxyConfig (not Pydantic) | Keeps package dependency footprint minimal; no pydantic required for a thin proxy tool |
| get_agent_config() passthrough for unknown names | Unknown agent treated as its own binary — zero-config for custom agents, no raise needed |
| fire_and_forget uses _pending set for GC-safe task retention | asyncio.create_task() holds only weak reference on Python 3.12+ (CPython #117379); _pending set holds strong reference until done callback discards |
| _handle_line wrapped in bare except Exception: pass | Routing errors must never surface to the agent session — silent failure contract |
| threads/update ingests unless explicitly done=False | Default True means partial updates ingested; only streaming chunks (done=False) skipped |
| Browser extension: 800ms debounce on MutationObserver | Streaming responses cause hundreds of DOM mutations per turn; debounce fires once on turn completion |
| Passive ingestion: am-proxy (CLI agents) + am-ext (web UIs) | Covers full spectrum without OAuth scraping — proxy wraps ACP stdio, extension observes DOM |
| am-proxy CLI: parse_known_args() not REMAINDER for passthrough | Python 3.13 subparser treats bare positional args as invalid subcommand choices even in parse_known_args; flag-style extras work via remaining list |
| asyncio.run mock in tests uses side_effect with coro.close() | Prevents RuntimeWarning: coroutine never awaited when patching asyncio.run with return_value |
| ingestion_mode: "passive" for proxy and extension payloads | Distinguishes auto-captured turns from explicit MCP writes in query and analytics |
| Module-level imports (try/except) for markdownify and pymupdf4llm | Enables pytest patch() interception; fallback None values for environments without optional deps |
| Overlap in _recursive_split as word-count (int(overlap_tokens/1.3)) | Consistent with _token_count approximation; ~38 words for 50-token overlap |
| Chunk content_hash encodes (session_id:chunk_index:text) | MERGE on (source_key, content_hash) implements CONTEXT.md Chunk dedup key of (session_id, chunk_index); prevents cross-session collapse |
| Finding content_hash is sha256(text) text-only | Global dedup — same finding found in multiple sessions stored once, avoids duplication across project |
| All MCP tools use sync def; brave_search has no auto-ingest guard | Matches existing rate_limit/log_tool_call sync wrapper pattern; Brave results are ephemeral agent context |
| CLI local imports require patching source module path in tests | codememory.cli.ConnectionManager doesn't exist at test time; patch codememory.core.connection.ConnectionManager instead |
| fix_vector_index_dimensions() as separate migration method | IF NOT EXISTS in setup_database() cannot correct already-existing wrong-dimension indexes; DROP + CREATE needed for live databases that ran old DDL |
| CASE expression for last_turn_index in Session MERGE | Atomic max tracking in Cypher avoids Python-side read-modify-write race on concurrent turn ingestion |
| Session MERGE key = session_id alone (not composite with project_id) | session_id is globally unique by caller convention; composite key would break idempotency on mismatched project_id |
| EMBEDDABLE_ROLES frozenset controls embedding/entity path | system and tool turns stored without embedding keeps chat_embeddings index focused on semantically meaningful content |
| Turn content_hash = sha256(session_id:turn_index), content excluded | Session-scoped MERGE key; re-delivery of updated turn content overwrites in place without duplicate node creation |
| register_conversation_tools(mcp) pattern avoids circular import | tools.py cannot import mcp from app.py since app.py imports tools.py; function receives mcp as argument, called at app.py module level |
| MCP conversation tools are async; existing tools are sync | FastMCP supports both; async chosen for conversation tools per plan spec (run_in_executor for pipeline.ingest) |

---

## Performance Metrics

| Phase | Plan | Duration (min) | Tasks | Files |
|-------|------|----------------|-------|-------|
| 01 | 01 | 6 | 2 | 7 |
| 01 | 02 | 7 | 2 | 4 |
| 01 | 03 | 5 | 2 | 6 |
| 01 | 04 | 8 | 2 | 6 |
| 02 | 01 | 7 | 2 | 6 |
| 02 | 02 | 8 | 1 | 3 |
| 02 | 03 | 25 | 2 | 4 |
| 02 | 04 | 60 | 1 | 13 |
| 04 | 01 | 4 | 3 | 3 |
| 04 | 02 | 7 | 2 | 3 |
| 04 | 03 | 7 | 2 | 6 |
| 05 | 01 | 15 | 4 | 7 |
| 05 | 02 | 15 | 3 | 4 |
| 05 | 03 | 15 | 2 | 2 |

## Blockers / Open Questions

- [ ] Confirm Gemini embedding API: model name, dimensionality, auth method (Vertex AI vs AI Studio)
- [ ] Confirm Neo4j Community Edition supports multi-database on single instance
- [ ] Verify Vercel agent-browser current API surface and install method
