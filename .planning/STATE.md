# Agentic Memory — Project State

**Last Updated:** 2026-03-20
**Current Phase:** 1 — Foundation
**Phase Status:** Not Started

---

## Active Phase

**Phase 1: Foundation**
- Shared ingestion abstractions, embedding service layer, multi-database setup, config validation

**Next Action:** Run `/gsd:plan-phase` for Phase 1

---

## Phase Status

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundation | Not Started |
| 2 | Web Research Core | Not Started |
| 3 | Web Research Scheduling | Not Started |
| 4 | Conversation Memory | Not Started |
| 5 | Cross-Module Integration & Hardening | Not Started |

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

---

## Blockers / Open Questions

- [ ] Confirm Gemini embedding API: model name, dimensionality, auth method (Vertex AI vs AI Studio)
- [ ] Confirm Neo4j Community Edition supports multi-database on single instance
- [ ] Verify Vercel agent-browser current API surface and install method
