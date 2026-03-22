---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: — Full Multi-Module Memory System
current_phase: 2
status: unknown
last_updated: "2026-03-21T07:11:53.356Z"
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
---

# Agentic Memory — Project State

**Last Updated:** 2026-03-21
**Current Phase:** 2
**Phase Status:** Complete
**Last Session Stopped At:** Completed 01-04-PLAN.md

---

## Active Phase

**Phase 1: Foundation**

- Shared ingestion abstractions, embedding service layer, multi-database setup, config validation

**Next Action:** Begin Phase 2 — Web Research Core

---

## Phase Status

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundation | Complete |
| 2 | Web Research Core | Not Started |
| 3 | Web Research Scheduling | Not Started |
| 4 | Conversation Memory Core | Not Started |
| 5 | am-proxy (ACP Proxy) | Not Started |
| 6 | am-ext (Browser Extension) | Not Started |
| 7 | Cross-Module Integration & Hardening | Not Started |

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
| REST API (`am-server`) required in Phase 4 | Both am-proxy and am-ext POST to `/ingest/conversation` — MCP alone is insufficient for passive capture |
| am-proxy: asyncio.call_later TTL for request/response buffer | Per-entry cancel handle prevents unbounded buffer growth; 300s TTL covers longest real tool calls |
| Browser extension: 800ms debounce on MutationObserver | Streaming responses cause hundreds of DOM mutations per turn; debounce fires once on turn completion |
| Passive ingestion: am-proxy (CLI agents) + am-ext (web UIs) | Covers full spectrum without OAuth scraping — proxy wraps ACP stdio, extension observes DOM |
| ingestion_mode: "passive" for proxy and extension payloads | Distinguishes auto-captured turns from explicit MCP writes in query and analytics |

---

## Performance Metrics

| Phase | Plan | Duration (min) | Tasks | Files |
|-------|------|----------------|-------|-------|
| 01 | 01 | 6 | 2 | 7 |
| 01 | 02 | 7 | 2 | 4 |
| 01 | 03 | 5 | 2 | 6 |
| 01 | 04 | 8 | 2 | 6 |

## Blockers / Open Questions

- [ ] Confirm Gemini embedding API: model name, dimensionality, auth method (Vertex AI vs AI Studio)
- [ ] Confirm Neo4j Community Edition supports multi-database on single instance
- [ ] Verify Vercel agent-browser current API surface and install method
