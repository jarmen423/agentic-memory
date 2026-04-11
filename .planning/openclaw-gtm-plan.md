# Unified OpenClaw Production Readiness Plan

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Plan Assessment and Grading](#2-plan-assessment-and-grading)
3. [Architecture and Integration Blueprint](#3-architecture-and-integration-blueprint)
4. [Frictionless Install and Onboarding](#4-frictionless-install-and-onboarding)
5. [Dashboard UI/UX Specification](#5-dashboard-uiux-specification)
6. [Security, Privacy, and Compliance](#6-security-privacy-and-compliance)
7. [Testing Strategy](#7-testing-strategy)
8. [Performance Targets and SLOs](#8-performance-targets-and-slos)
9. [Monitoring, Telemetry, and Observability](#9-monitoring-telemetry-and-observability)
10. [CI/CD and Packaging](#10-cicd-and-packaging)
11. [Rollout Strategy](#11-rollout-strategy)
12. [Risk Assessment](#12-risk-assessment)
13. [Resource Estimates and Timeline](#13-resource-estimates-and-timeline)
14. [Success Metrics and Exit Criteria](#14-success-metrics-and-exit-criteria)
15. [Assumptions, Constraints, and Open Questions](#15-assumptions-constraints-and-open-questions)

---

## 1. Executive Summary

**Goal:** Take the OpenClaw plugin (`packages/am-openclaw`) from functional single-agent prototype to production-ready GA with 10-agent concurrency, a premium dashboard, marketplace distribution, and full operational maturity.

**Current State:** The core plugin code is functional. Both memory and context-engine slots are wired. Setup wizard, turn ingestion (8 backend endpoints), memory search, canonical reads (conversation only), and project lifecycle are implemented. The backend has bearer-token auth, the desktop shell has a minimal UI with OpenClaw panels, and there are 22+ Python tests covering identity preservation, shared workspace stress, and route contracts.

**Key Gaps:**
- No TypeScript build/test in CI (plugin package untested in automation)
- Single bearer token auth (no multi-tenant, no key rotation)
- Desktop shell is placeholder-quality (no build system, no signed installer)
- No load/performance/chaos testing
- Canonical reads limited to conversation turns (code/research hits return 404)
- No OpenAPI published artifact or contract tests
- No production Docker configuration for `am-server`
- `packages/am-openclaw/package.json` still `private: true`

**Phases:** 6 sequential phases with exit-criteria gates. Foundation -> Testing+Dashboard (parallel) -> Scaling+Packaging -> Docs+GTM -> GA Hardening -> GA Release. Each phase completes when its exit criteria are met, not on a fixed calendar.

**ROI Targets (GA):** 200 installs, 80 active users, <2% weekly churn, p95 memory search <600ms, 99.5% API availability.

---

## 2. Plan Assessment and Grading

### Evaluation Rubric

Each plan scored on a 1-5 scale across 12 criteria (5 = exceptional, 4 = strong, 3 = adequate, 2 = weak, 1 = absent).

| Criterion | Plan 3 (`plan-3.md`) | Tidy Tiger (`tidy-tiger.md`) | Blueprint (`121e24a2`) | Winner |
|-----------|:---:|:---:|:---:|--------|
| **Repo groundedness** (references real files, code locations) | 5 | 4 | 4 | Plan 3 |
| **Implementation specificity** (concrete deliverables, file changes) | 5 | 3 | 2 | Plan 3 |
| **Architecture clarity** (diagrams, component relationships) | 3 | 4 | 4 | Tidy Tiger / Blueprint |
| **Scope completeness** (all required areas covered) | 4 | 5 | 4 | Tidy Tiger |
| **Testing strategy depth** | 5 | 4 | 3 | Plan 3 |
| **Security & compliance** | 3 | 4 | 4 | Tidy Tiger / Blueprint |
| **UX/dashboard specification** | 4 | 5 | 3 | Tidy Tiger |
| **Observability & SRE** | 4 | 4 | 4 | Tie |
| **GTM & packaging** | 3 | 4 | 3 | Tidy Tiger |
| **Risk assessment** | 4 | 5 | 3 | Tidy Tiger |
| **Timeline realism** | 4 | 4 | 3 | Plan 3 / Tidy Tiger |
| **Actionability** (can engineer start immediately?) | 5 | 2 | 2 | Plan 3 |
| **TOTAL** | **49/60** | **48/60** | **39/60** | |

### Grade Summary

| Plan | Grade | Rationale |
|------|-------|-----------|
| **Plan 3** (`plan-3.md`) | **A-** (49/60) | Strongest implementation plan. File-level precision, pre-identified bottlenecks (connection pool timeout, singleton pipeline, embedding rate limits), concrete exit criteria per phase. Weakest on multi-tenant auth design, formal architecture diagrams, and desktop companion packaging beyond "replace with React SPA." |
| **Tidy Tiger** (`tidy-tiger.md`) | **A-** (48/60) | Best strategic plan. Comprehensive scope, explicit recommended defaults (deployment model, auth model, persistence), strongest UX direction (typography, design tokens, design system), most thorough failure mode enumeration, best release gates. Weakest on actionability—it is a plan-for-a-plan, not an implementation plan. |
| **Blueprint** (`openclaw_production_readiness_121e24a2.plan.md`) | **B** (39/60) | Solid executive overview. Good Mermaid diagram, reasonable phased timeline. Weakest on implementation specificity—sections read as checklist headers rather than actionable specifications. Largely subsumed by the other two plans which cover the same ground with more depth. |

### Synthesis Strategy

The consolidated plan below adopts:
- **Implementation structure and technical specificity** from Plan 3 (phases, file-level deliverables, bottleneck analysis, testing matrix)
- **Strategic defaults and architectural direction** from Tidy Tiger (deployment model, auth model, persistence migration, UX north star, design system, release gates, failure modes)
- **Executive framing and phased timeline structure** from Blueprint (Mermaid diagram style, SLO draft format, deliverable checklist)

Conflicts resolved:
- **SLO targets:** Tidy Tiger's beta/GA split is more nuanced than Plan 3's single target set. **Adopted: Tidy Tiger's tiered SLOs** with Plan 3's specific latency numbers as starting points.
- **Dashboard stack:** Plan 3 recommends React+Radix+Recharts in `packages/am-dashboard/`. Tidy Tiger recommends Manrope/IBM Plex Mono typography. **Adopted: Plan 3's stack with Tidy Tiger's design tokens** (adjusted to match existing dark-mode palette).
- **Auth model:** Plan 3 proposes multi-key via comma-separated env var. Tidy Tiger proposes workspace-scoped JWT. **Adopted: Plan 3's multi-key as Phase 0 quickfix, Tidy Tiger's JWT as Phase 3 target.**
- **Timeline:** Plan 3 and Tidy Tiger proposed fixed week-based schedules. **Adopted: Phase-gated sequencing with exit criteria** instead of fixed calendar durations. Each phase completes when its exit criteria are met.

---

## 3. Architecture and Integration Blueprint

### 3.1 Component Diagram

```
+------------------------------------------------------------------+
|                        OpenClaw Hosts (1..N)                      |
|  +----------------+  +----------------+  +----------------+      |
|  | Agent 1        |  | Agent 2        |  | Agent N        |      |
|  | (am-openclaw)  |  | (am-openclaw)  |  | (am-openclaw)  |      |
|  | memory+ctx-eng |  | memory+ctx-eng |  | memory+ctx-eng |      |
|  +-------+--------+  +-------+--------+  +-------+--------+      |
+----------|-------------------|-------------------|----------------+
           |                   |                   |
           v                   v                   v
+------------------------------------------------------------------+
|                  am-server (FastAPI)                              |
|  +------------------+  +-------------------+  +--------------+   |
|  | /openclaw/*      |  | Auth Middleware    |  | /metrics     |   |
|  | (8 endpoints)    |  | (Bearer -> JWT)   |  | (Prometheus) |   |
|  +--------+---------+  +-------------------+  +--------------+   |
|           |                                                       |
|  +--------v---------+  +-------------------+  +--------------+   |
|  | Conversation     |  | Unified Search    |  | Product      |   |
|  | Pipeline         |  | (Vector+Graph)    |  | State Store  |   |
|  +--------+---------+  +--------+----------+  +------+-------+   |
+-----------|---------------------|----------------------|----------+
            |                     |                      |
            v                     v                      v
+------------------+  +-------------------+  +------------------+
| Neo4j 5.25       |  | Embedding API     |  | Local JSON ->    |
| (Graph+Vector)   |  | (Gemini/OpenAI)   |  | SQLite (Phase 1) |
+------------------+  +-------------------+  +------------------+

+------------------------------------------------------------------+
|                  Desktop Shell / Dashboard                        |
|  +--------------------+  +---------------------+                 |
|  | am-dashboard (SPA) |  | Proxy routes to     |                 |
|  | React+Vite+Radix   |  | am-server API       |                 |
|  +--------------------+  +---------------------+                 |
+------------------------------------------------------------------+
```

*Source: Architecture pattern from Blueprint plan (Section 2), component details from Plan 3 (Key Files Reference), proxy routes from codebase inventory.*

### 3.2 Identity Model (Normative)

Every OpenClaw API call carries the identity tuple:

```
workspace_id  (string, required)  — tenant boundary
device_id     (string, required)  — physical machine
agent_id      (string, required)  — OpenClaw agent instance
session_id    (string, computed)  — <workspace_id>:<device_id>:<agent_id>
project_id    (string, optional)  — resolved server-side from product state if omitted
```

*Source: `packages/am-openclaw/src/shared.ts:buildSessionId()`, `src/am_server/models.py:OpenClawIdentityModel`.*

### 3.3 Integration Contracts

| Endpoint | Plugin Caller | Purpose | Non-blocking? |
|----------|--------------|---------|:---:|
| `POST /openclaw/session/register` | `bootstrap()` | Register agent session | No (startup) |
| `POST /openclaw/memory/ingest-turn` | `ingestOne()` | Ingest conversation turn | Yes (async) |
| `POST /openclaw/memory/search` | `search()` | Hybrid vector+graph search | No (user-facing) |
| `POST /openclaw/memory/read` | `readFile()` | Canonical read of a hit | No (user-facing) |
| `POST /openclaw/context/resolve` | `assemble()` | Build context blocks | No (only in augment_context) |
| `POST /openclaw/project/activate` | setup.ts | Activate project binding | No (CLI) |
| `POST /openclaw/project/deactivate` | setup.ts | Deactivate project | No (CLI) |
| `POST /openclaw/project/status` | setup.ts | Query active project | No (CLI) |
| `POST /openclaw/project/automation` | setup.ts | Configure workspace automation | No (CLI) |

*Source: Route inventory from `src/am_server/routes/openclaw.py`, plugin callers from `packages/am-openclaw/src/runtime.ts` and `setup.ts`.*

### 3.4 Dependency Map

```
OpenClaw host semver  -->  am-openclaw plugin (minHostVersion: >=2026.4.5)
                              |
                              v
                         am-server /openclaw/*
                              |
                   +----------+----------+
                   |          |          |
                   v          v          v
                 Neo4j    Embedding   Product State
                 5.25+    API         (JSON -> SQLite)
```

### 3.5 Explicit Failure Modes

*Source: Combined from Tidy Tiger (Section "Explicit failure modes") and Blueprint (Section 3).*

| Failure | User Impact | Mitigation |
|---------|-------------|------------|
| Plugin install fails / host version mismatch | Cannot activate | `minHostVersion` check; clear error message with upgrade link |
| Backend auth token expired/invalid | 401 on all calls | Structured error with actionable message; dashboard shows red status |
| Backend timeout during ingest | Potential message loss | Async queue; fire-and-forget with metric; retry with backoff |
| Neo4j connection pool exhaustion | 503 on search/ingest | Reduce `connection_acquisition_timeout` to 10s; fail fast; metric |
| Embedding API rate limit | Degraded search (text-only fallback) | Batch embeddings; backpressure queue; skip embedding, embed later |
| Partial graph/embedding failure | Empty or stale search results | Return best-effort results; log degradation; dashboard health indicator |
| Session/project mismatch | Wrong project context in search | Server-side resolution via `_resolve_active_project_id()`; fallback documented |
| Canonical read for non-conversation hit | 404 | Fall back to cached search snippet (already implemented in `runtime.ts`) |
| Plugin upgrade with schema change | Config corruption | `setup-api.js` migration hook; `schema_version` field in config |
| Desktop companion offline | No dashboard, but plugin still works | Plugin calls am-server directly; dashboard is optional control plane |

---

## 4. Frictionless Install and Onboarding

### 4.1 Install Flow (Target State)

```
Step 1: Install plugin
  $ openclaw install agentic-memory
  (or: marketplace one-click install)

Step 2: Run setup wizard
  $ openclaw agentic-memory setup
  > Backend URL [http://127.0.0.1:8765]: ___
  > API Key: ___
  > Device ID [auto-detected]: ___
  > Agent ID [default]: ___
  > Enable context augmentation? [n]: ___
  > Testing connection... OK
  > Memory capture enabled. Your agent will remember.

Step 3: Verify (automatic after setup)
  Plugin sends a test turn and searches for it.
  "Memory verified. Your agent recalled: [test content]"

Step 4: Use normally
  Every conversation turn is captured automatically.
  Memory search is available via agent tools.
```

*Source: Plan 3 (Section 4.4 Onboarding Funnel), adapted with Tidy Tiger's "3-step wizard" concept and the existing `setup.ts` implementation.*

### 4.2 Install Prerequisites

| Prerequisite | Required By | Notes |
|--------------|-------------|-------|
| OpenClaw host >= 2026.4.5 | Plugin manifest | Already enforced in `openclaw.plugin.json` |
| Running `am-server` instance | Plugin runtime | Can be local (Docker) or hosted |
| `AM_SERVER_API_KEY` configured | Auth | Until JWT migration (Phase 3) |
| Neo4j 5.18+ | am-server | Via `docker-compose.yml` or managed |
| Embedding API key | am-server | Gemini or OpenAI, configured in `.env` |

### 4.3 Time-to-First-Memory Target

**Beta:** p95 under 15 minutes from "install plugin" to verified cross-session recall.
**GA:** p95 under 10 minutes.

*Source: Blueprint (Section "ROI-focused metrics"), Tidy Tiger (Section "Recommended SLOs").*

### 4.4 Compatibility Matrix

| OS | OpenClaw Host | Plugin | am-server | Dashboard |
|----|--------------|--------|-----------|-----------|
| Windows 10+ | Supported | Supported | Docker or native | Browser-based |
| macOS 12+ | Supported | Supported | Docker or native | Browser-based |
| Linux (Ubuntu 22.04+) | Supported | Supported | Docker or native | Browser-based |

---

## 5. Dashboard UI/UX Specification

### 5.1 Architecture Decision

**Replace** existing vanilla HTML/JS in `desktop_shell/static/` with a React SPA in a new `packages/am-dashboard/` workspace. Serve from existing `desktop_shell/app.py` FastAPI app via static file mount.

*Source: Plan 3 (Section 2.1). Justified: The current shell has 3 static files with no build system, placeholder cards, and no component structure. A React SPA with a proper build pipeline is the minimum viable approach for the required feature set.*

**Stack:**
- React 18 + TypeScript + Vite
- Radix UI primitives + custom styled components
- Recharts for time-series visualizations
- TanStack Query for data fetching with auto-refresh
- Package location: `packages/am-dashboard/`

### 5.2 Design System

*Source: Tidy Tiger (Section "Design system direction"), Plan 3 (Section 2.2), existing `desktop_shell/static/styles.css`.*

**Design Tokens** (`dashboard-design-tokens.json`):

```json
{
  "color": {
    "bg": "#08111f",
    "bgSoft": "#0e192d",
    "surface": "#121826",
    "panel": "rgba(15, 25, 44, 0.82)",
    "accent": "#7fd1ff",
    "accentStrong": "#4fb0ff",
    "success": "#34d399",
    "warning": "#fbbf24",
    "danger": "#f87171",
    "text": "#e2e8f0",
    "textMuted": "#94a3b8"
  },
  "radius": {
    "sm": "6px",
    "md": "8px",
    "lg": "20px"
  },
  "spacing": {
    "unit": "8px"
  },
  "font": {
    "sans": "Manrope, Inter, system-ui, sans-serif",
    "mono": "IBM Plex Mono, JetBrains Mono, SF Mono, monospace"
  },
  "shadow": {
    "elevated": "0 4px 24px rgba(0, 0, 0, 0.3)"
  }
}
```

**Rationale for token choices:**
- Colors extend the existing dark palette from `desktop_shell/static/styles.css` (preserving `--bg`, `--bg-soft`, `--panel`, `--accent`)
- Typography from Tidy Tiger: Manrope for UI (geometric, modern, excellent readability), IBM Plex Mono for operational data (technical, professional)
- 8px spacing scale from Tidy Tiger for consistency

### 5.3 Dashboard Pages

*Source: Plan 3 (Section 2.3) with layout direction from Tidy Tiger (Section "Dashboard structure to specify").*

**Navigation:** Sidebar with 6 sections: Overview | Agents | Memory Health | Search Quality | Workspace | Settings

**Page 1 — Overview (Home)**
- Top row: 4 metric cards (active agents, turns ingested today, searches today, memory health score)
- Middle: Ingestion activity timeline (area chart, 24h window, 5-min buckets)
- Bottom: Recent agent sessions table (agent_id, device_id, last activity, turn count, project)
- Status hero: Backend connected / Neo4j healthy / Embedding API operational

**Page 2 — Agent Activity**
- 10-agent matrix/fleet view (card per agent, real-time status indicators)
- Per-agent detail: turn timeline, session lifecycle, last error
- Session state machine visualization (registered -> active -> idle -> expired)

**Page 3 — Memory Health**
- Neo4j connection pool gauge (current/max)
- Vector index stats: node count per index, storage growth chart
- Embedding API health: success rate, latency histogram, rate limit hits
- Queue depth (when async ingest is implemented)

**Page 4 — Search Quality**
- Recent searches with relevance scores
- Score distribution histogram
- Hit source breakdown (code vs research vs conversation)
- Latency percentile chart

**Page 5 — Workspace Management**
- Workspace/device/agent tree view
- Active projects per workspace
- Project lifecycle controls (activate, deactivate)
- Integration status grid
- API key management (Phase 3+)

**Page 6 — Settings**
- Backend URL configuration
- Mode toggle (capture_only / augment_context)
- Export diagnostics JSON (one-click support bundle)
- Update notification banner

### 5.4 New Backend Endpoints for Dashboard

*Source: Plan 3 (Section 2.4).*

Add to `src/am_server/routes/dashboard.py`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/openclaw/metrics/summary` | GET | Aggregated counters for dashboard cards |
| `/openclaw/agents/{agent_id}/sessions` | GET | Session history for agent detail view |
| `/openclaw/health/detailed` | GET | Neo4j pool stats, index stats, embedding health |
| `/openclaw/search/recent` | GET | Last N searches with scores for quality view |
| `/openclaw/workspaces` | GET | Workspace/device/agent tree for management |

### 5.5 Accessibility (WCAG 2.1 AA)

- Keyboard navigation for all interactive elements
- Screen reader labels for all charts (aria-label with data summary)
- Color contrast >= 4.5:1 for all text
- Respect `prefers-reduced-motion` for animations
- Focus rings on all interactive elements
- Lighthouse accessibility score target: >= 90

---

## 6. Security, Privacy, and Compliance

### 6.1 Authentication Evolution

*Source: Plan 3 (Section 0.3) for Phase 0, Tidy Tiger (Section "Auth model") for target state.*

| Phase | Mechanism | Implementation |
|-------|-----------|----------------|
| Phase 0 (now) | Multi-key bearer tokens | `AM_SERVER_API_KEYS` comma-separated env var, backward-compatible with `AM_SERVER_API_KEY` |
| Phase 3 | Workspace-scoped API keys | Keys stored server-side, scoped to `workspace_id`, rotatable via API |
| Post-GA | JWT with claims | `{workspace_id, role}` claims, short-lived tokens, desktop companion manages auth flow |

**Justification:** Multi-key is a 1-day change that immediately enables key rotation and dev/prod separation. Full JWT requires server-side key storage and token issuance, which depends on the persistence migration (Phase 1).

### 6.2 Authorization

- Every query MUST filter by authenticated workspace (enforce IDOR prevention)
- Rate limiting: 100 req/s per workspace (ingest), 50 req/s (search) via `slowapi` or custom token bucket
- Input validation bounds: content max 100KB, query max 2000 chars, limit max 50

### 6.3 Threat Model

*Source: Plan 3 (Section 0.3), Blueprint (Section 9).*

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| API key leaked in logs/repo | Medium | High | Never log full key; mask in error messages; `.env` in `.gitignore` |
| IDOR (cross-workspace data access) | Medium | Critical | Workspace-scoped queries; integration test for IDOR |
| Injection via content field | Low | High | Parameterized Cypher queries (already via neo4j driver); Pydantic validation |
| Bearer token brute force | Low | High | Rate limiting; key length >= 32 chars |
| Supply chain (malicious dep) | Low | High | `pip-audit` + `npm audit` in CI; lockfiles; Dependabot |
| PII in conversation content stored in Neo4j | N/A | Variable | Document data residency; add retention policy; purge endpoint |

### 6.4 Secrets Management

- Secrets NEVER committed; `.env` in `.gitignore` (already enforced)
- OS keychain for desktop companion (future)
- Config files with 0600 permissions where applicable
- Key rotation documented in runbook RB-002

### 6.5 Privacy and Data Handling

- Conversation content stored in Neo4j with workspace-scoped access
- Document retention policy: default 90 days, configurable per workspace
- Add `DELETE /openclaw/workspace/{workspace_id}/purge` endpoint for data deletion
- DPA template for enterprise customers (post-GA)

### 6.6 CORS

- Explicit origin allowlist in `src/am_server/app.py`
- Default: `http://localhost:*` for local development
- Production: configurable via `AM_SERVER_CORS_ORIGINS` env var

---

## 7. Testing Strategy

### 7.1 Test Matrix

*Source: Plan 3 (Sections 1.1-1.6) for implementation details, Tidy Tiger (Section "Testing strategy") for scope, Blueprint (Section 7) for acceptance criteria.*

| Test Type | Location | Framework | Coverage Target | CI Gate? |
|-----------|----------|-----------|:---:|:---:|
| Python unit | `tests/` | pytest | 80% line coverage | Yes |
| TypeScript unit | `packages/am-openclaw/tests/` | vitest | 80% line coverage | Yes |
| Contract tests | `tests/test_openclaw_contract.py` | pytest | 100% of OpenClaw endpoints | Yes |
| Integration tests | `tests/` (marker: integration) | pytest + Neo4j service | All route-level flows | Yes |
| E2E test | `tests/e2e/test_openclaw_e2e.py` | pytest | Full plugin lifecycle | Nightly |
| Load tests | `tests/load/test_openclaw_load.py` | locust or httpx async | 10-agent sustained | Weekly |
| Chaos tests | `tests/chaos/` | Custom | Graceful degradation | Pre-release |
| Security scan | CI job | pip-audit + npm audit + trivy | Zero critical/high | Yes |
| Dashboard build | `packages/am-dashboard/` | Vite + Lighthouse | Build succeeds, a11y >= 90 | Yes |

### 7.2 Concrete Acceptance Criteria

**Contract Tests (new: `tests/test_openclaw_contract.py`):**
- For each of the 8+1 OpenClaw endpoints: validate request schema matches Pydantic model, response shape matches what `runtime.ts` parses
- Cross-language assertion: generate TypeScript type guards from Pydantic models

**TypeScript Plugin Tests (new: `packages/am-openclaw/tests/`):**
- Unit tests for `shared.ts`: `resolveAgenticMemoryPluginConfig`, `normalizeMessageText`, `estimateTokenCount`, `parseOpenClawSessionIdentity`, `buildSessionId`
- Mock-server integration tests for `backend-client.ts` (structured error parsing, retry behavior)
- Runtime tests for `AgenticMemorySearchManager.search()` and `AgenticMemoryContextEngine.assemble()` with mocked backend

**Load Tests:**
- 10 concurrent agents x 2 turns/s = 20 ingest req/s sustained for 5 minutes
- Measure: p50/p95/p99 latency per endpoint, Neo4j pool utilization, embedding API rate limit hits
- Pass criteria: p95 ingest < 250ms, p95 search < 800ms

**E2E Test:**
- Start `am-server` in subprocess with Neo4j
- Simulate full plugin lifecycle: register session -> ingest 5 turns -> search -> read -> resolve context
- Assert round-trip data correctness

**Chaos Tests:**
- Backend unavailable during ingest -> graceful failure, no data corruption
- Neo4j connection pool exhaustion -> 503, not hang
- Embedding API timeout -> degraded search (text-only), not crash

### 7.3 GA Gate (Test Requirements)

- All contract tests pass in CI
- E2E green for 5 consecutive runs on `main`
- Load test sustains 20 req/s for 5 min with p95 < targets
- TypeScript plugin >= 80% line coverage
- Python >= 80% line coverage for `am_server` package
- Security scan clean (zero critical/high)
- Rollback tested once (version N -> N-1 -> N with no data loss)

---

## 8. Performance Targets and SLOs

### 8.1 Tiered SLO Targets

*Source: Tidy Tiger (Section "Recommended SLOs") as framework, Plan 3 (Section 1.6) for specific latency numbers adjusted to be realistic.*

| Metric | Beta Target | GA Target | Measurement |
|--------|:---:|:---:|-------------|
| Ingest turn ACK (p95) | < 250ms | < 150ms | Load test with Neo4j + embedding |
| Memory search (p95) | < 800ms | < 600ms | 10 concurrent searches |
| Context resolve (p95) | < 1500ms | < 1200ms | Includes search + formatting |
| Canonical read (p95) | < 400ms | < 300ms | Conversation turn with neighbors |
| Backend RSS | < 512MB | < 1GB | Process monitoring under load |
| Neo4j heap | < 4GB | < 4GB | Docker stats under load |
| Dashboard page-load (p95) | < 2.0s | < 1.5s | Desktop broadband |
| API availability | 99.5% | 99.9% | 7-day rolling window |
| 5xx error rate | < 0.5% | < 0.1% | 7-day rolling window |
| RPO | < 5 min | < 1 min | Backup frequency |
| RTO | < 60 min | < 15 min | Incident drill |

### 8.2 Pre-Identified Bottlenecks

*Source: Plan 3 (Section 1.7). These are concrete code-level issues to resolve in Phase 0-1.*

1. **Connection pool timeout:** `src/agentic_memory/core/connection.py:32` sets `connection_acquisition_timeout=60` — too high for real-time. Reduce to 10s, fail fast.
2. **Singleton pipeline:** `lru_cache(maxsize=1)` in `src/am_server/dependencies.py` shares one pipeline instance. Concurrent ingest calls serialize on Neo4j session. Fix: open new session per request, or add async write queue.
3. **Embedding rate limits:** 10 agents at 2 turns/s = 120 embedding calls/min — may exceed free tier. Fix: batch embeddings (10 texts/call), add backpressure queue, skip embedding on rate limit (ingest text, embed later).

### 8.3 Scaling Architecture (10 Agents)

*Source: Plan 3 (Section 3.1-3.3), Blueprint (Section 4).*

| Component | Allocation | Notes |
|-----------|-----------|-------|
| Neo4j heap | 4GB | Up from default in docker-compose |
| Neo4j pagecache | 1GB | Existing |
| Backend RSS | 512MB | FastAPI + pipelines + OTel |
| Embedding API | 300 req/min | Gemini paid tier, batched |
| Neo4j pool | 50 connections | Existing, sufficient for 10 agents |
| Uvicorn workers | 4 | Up from 1 default |

**Write path optimization:**
- Async write queue (`asyncio.Queue`, depth 1000) between ingest endpoint and pipeline
- Batched Neo4j writes: group up to 10 turns into single `UNWIND` Cypher
- Batched embedding: accumulate up to 10 texts per API call
- Backpressure: on rate limit, ingest text immediately, queue embedding for background retry

**Read path optimization:**
- TTL cache (60s) for `/openclaw/project/status` per workspace_id
- Query result cache for identical searches within 30s window

---

## 9. Monitoring, Telemetry, and Observability

### 9.1 Metrics

*Source: Plan 3 (Section 0.2), Blueprint (Section 10).*

**Core metrics (Prometheus-compatible, served on `/metrics`):**

| Metric | Type | Labels |
|--------|------|--------|
| `am_ingest_turns_total` | Counter | workspace_id, agent_id, source_key |
| `am_ingest_errors_total` | Counter | workspace_id, error_code |
| `am_search_requests_total` | Counter | workspace_id, module |
| `am_search_latency_seconds` | Histogram | module |
| `am_context_resolve_latency_seconds` | Histogram | - |
| `am_neo4j_query_latency_seconds` | Histogram | operation |
| `am_embedding_api_latency_seconds` | Histogram | provider |
| `am_embedding_errors_total` | Counter | provider, error_type |
| `am_active_sessions` | Gauge | workspace_id |

### 9.2 Structured Logging

- JSON lines format with fields: `workspace_id` (hashed if needed), `agent_id`, `trace_id`, `route`, `status_code`, `latency_ms`
- Log level: `warn`+ for hot paths (ingest, search), `info` for cold paths (setup, project commands)
- Never log: API keys, full conversation content (log truncated content hash instead)

### 9.3 Distributed Tracing

- OpenTelemetry SDK instrumentation on FastAPI + outbound embedding calls
- `X-Request-ID` header propagation (middleware already exists in `src/am_server/middleware.py`)
- Trace context on all Neo4j queries

### 9.4 Dashboards (Grafana)

| Dashboard | Panels |
|-----------|--------|
| SLO Overview | Availability, error budget, p95 latencies, active agents |
| Ingest Pipeline | Queue depth, write throughput, batch sizes, failures |
| Search Quality | Latency percentiles, hit counts by type, empty result rate |
| Neo4j Health | Connection pool, query duration, heap usage, storage growth |
| Embedding Health | API call rate, latency, error rate, rate limit events |

### 9.5 Alerting

| Alert | Condition | Severity | Runbook |
|-------|-----------|----------|---------|
| API error rate high | 5xx rate > 1% over 5 min | Page | RB-005 |
| Search latency degraded | p95 > 2s over 10 min | Warn | RB-005 |
| Neo4j pool exhaustion | available connections < 5 | Page | RB-004 |
| Embedding API errors | error rate > 10% over 5 min | Page | RB-006 |
| Ingest queue backlog | depth > 500 for > 5 min | Warn | RB-004 |
| Storage growth | Neo4j disk > 80% | Warn | RB-003 |

### 9.6 Data Retention

- Metrics: 30 days at full resolution, 1 year at 5-min aggregation
- Logs: 14 days hot (searchable), 90 days cold (archived)
- Traces: 7 days

---

## 10. CI/CD and Packaging

### 10.1 CI Pipeline Expansion

*Source: Plan 3 (Section 3.5). Current CI at `.github/workflows/ci.yml` has 3 Python-only jobs.*

**New CI jobs to add:**

| Job | Trigger | What |
|-----|---------|------|
| `ts-build-test` | Push/PR | `npm ci && npm run build && npx vitest run` for am-openclaw |
| `contract-tests` | Push/PR | `pytest -m contract` with Neo4j service container |
| `dashboard-build` | Push/PR | `npm run build --workspace am-dashboard` + Lighthouse audit |
| `security-scan` | Push/PR | `pip-audit` + `npm audit` + `trivy` on Docker image |
| `e2e-nightly` | Schedule (nightly) | Full E2E test with live am-server + Neo4j |
| `load-test-weekly` | Schedule (weekly) | 10-agent load test against staging |

**Fix existing CI:**
- Coverage target: change `--cov=codememory` to `--cov=am_server --cov=agentic_memory`
- Add Node.js setup step for TypeScript jobs

### 10.2 Release Pipeline

**New workflow: `.github/workflows/release.yml`** (triggered on tag `v*`):

1. Build Python wheel + sdist
2. Build TypeScript plugin dist (`npm pack` in `packages/am-openclaw`)
3. Build dashboard dist
4. Build Docker image and push to ghcr.io
5. Create GitHub Release with all artifacts
6. Publish to PyPI (am-server) and npm (`@agentic-memory/openclaw`)

### 10.3 Plugin Packaging

*Source: Plan 3 (Section 3.6).*

- Remove `"private": true` from `packages/am-openclaw/package.json`
- Set npm scope: `@agentic-memory/openclaw` (avoid name collision)
- Add `"license": "MIT"`, `"repository"`, `"homepage"`, `"bugs"` fields
- Build distributable `.tgz` via `npm pack`
- Install command: `openclaw install agentic-memory`
- Version migration logic in `setup-api.js` for future schema changes

### 10.4 Docker Configuration

**New file: `docker-compose.prod.yml`:**
- Neo4j 5.25 with resource limits (4GB heap, 1GB pagecache, persistent volume)
- am-server with 4 uvicorn workers, health check, resource limits
- Caddy or nginx reverse proxy with TLS termination
- Prometheus + Grafana (optional sidecar profile)

### 10.5 Rollback Strategy

*Source: Plan 3 (Section 3.8).*

- Docker images tagged by semver — rollback = change image tag and restart
- Neo4j schema migrations are additive only (`CREATE IF NOT EXISTS`) — no destructive DDL
- Plugin config schema versioned (`schema_version: 1`) with migration in `setup-api.js`
- API backward compatible for N-1 clients (response envelope stable)

---

## 11. Rollout Strategy

### 11.1 Phased Rollout

*Source: Tidy Tiger (Section "Proposed Phase Timeline") adapted with Plan 3's implementation specificity.*

| Phase | Goal | Exit Criteria |
|-------|------|---------------|
| **0: Foundation** | Error handling, observability, security hardening, persistence migration | Structured errors on all endpoints; `/metrics` serving 6 metrics; CORS + rate limiting active; `backend-client.ts` retries transient errors |
| **1: Testing + Dashboard** (parallel) | Contract tests, TypeScript tests, load tests, E2E; Dashboard MVP | Contract tests pass in CI; load test sustains 20 req/s; TS plugin >= 80% coverage; Dashboard 5 pages render with real data; Lighthouse a11y >= 90 |
| **2: Scaling + Packaging** | 10-agent write path, CI/CD pipeline, Docker prod config, plugin packaging | 10-agent load test passes; CI builds plugin artifact; Docker image on ghcr.io; rollback tested; 3 environments documented |
| **3: Docs + Private Beta** | Documentation, marketplace listing, 5 design partners onboarded | 7 docs written; marketplace listing submitted; 5 beta users active; OpenAPI committed |
| **4: Public Beta** | 50 installs target, telemetry-driven support | Install success >= 85%; 10-agent soak test 24h; no critical security findings; p95 meets beta SLOs for 7 days |
| **5: GA Release** | v1.0.0, public announcement | NPS >= 40; no open P0 bugs; SRE fire drill completed; p95 meets GA SLOs for 14 days |

### 11.2 Deployment Strategy

**Beta:** Single-instance deployment per customer/partner. Docker Compose with Neo4j + am-server + dashboard.

**GA:** Blue/green deployment capability:
- Two tagged Docker image versions active behind load balancer
- Health check on `/health` endpoint
- Traffic shift: 10% canary -> 50% -> 100% over 1 hour per rollout
- Automated rollback trigger: 5xx rate > 2% in 5 min window

### 11.3 Rollback Criteria

Rollback is triggered (automated or manual) when ANY of:
- 5xx error rate exceeds 2% for 5 minutes
- p95 ingest latency exceeds 1s for 10 minutes
- p95 search latency exceeds 3s for 10 minutes
- Neo4j connection failures exceed 10% of requests
- Data corruption detected (identity mismatch in ingest)

### 11.4 Rollback Procedure

1. Revert Docker image tag to previous version
2. Restart am-server containers
3. Verify `/health` returns previous version number
4. Run smoke test (register session + ingest + search)
5. Confirm metrics return to baseline within 5 minutes
6. Post-mortem within 24 hours

---

## 12. Risk Assessment

*Source: Combined from all three plans. Likelihood (L) and Impact (I) on 1-5 scale.*

| ID | Risk | L | I | Score | Owner | Mitigation | Trigger |
|----|------|:-:|:-:|:-----:|-------|------------|---------|
| R1 | Neo4j write throughput at 10 agents | 4 | 4 | 16 | Backend | Async write queue + batched UNWIND + pool tuning | p95 ingest > 500ms at 5 agents |
| R2 | Embedding API rate limits (Gemini free tier) | 4 | 4 | 16 | Backend | Batch embeddings + backpressure + paid tier | Rate limit errors > 5% |
| R3 | OpenClaw host SDK breaking changes | 3 | 4 | 12 | Plugin | Pin minHostVersion + contract tests + rapid patches | Host version bump |
| R4 | ProductStateStore JSON corruption under concurrency | 3 | 3 | 9 | Backend | Migrate to SQLite (Phase 0) + file locking interim | Any concurrent write failure |
| R5 | Plugin package lacks direct tests | 4 | 3 | 12 | Plugin | Add vitest suite (Phase 1) | Any regression in plugin |
| R6 | No signed installer or auto-update path | 3 | 3 | 9 | Desktop | Package desktop companion with release channels (Phase 3+) | User support requests |
| R7 | Supply chain vulnerability in deps | 2 | 4 | 8 | DevOps | Dependabot + pip-audit + npm audit in CI | Audit failure in CI |
| R8 | Canonical reads partial (conversation only) | 3 | 3 | 9 | Backend | Staged read-contract roadmap; fallback to cached snippets | User complaints about read quality |
| R9 | Single API key compromise | 3 | 4 | 12 | Security | Multi-key (Phase 0) + rotation runbook + scoped keys (Phase 3) | Any key leak |
| R10 | Dashboard delays block GA | 2 | 2 | 4 | Frontend | Ship without dashboard; existing shell provides minimal status | Phase 1 dashboard exit criteria remain unmet after all other Phase 1 criteria pass |

### Contingency Plans

*Source: Plan 3 (Section "Contingency Plans").*

- **Neo4j can't handle write load:** Switch to async ingestion with Redis Streams or local SQLite WAL queue. Endpoint returns 202, background workers drain to Neo4j.
- **Embedding API unreliable:** Automatic failover chain Gemini -> OpenAI -> skip. `EmbeddingService` in `src/agentic_memory/core/embedding.py` already supports both providers.
- **Dashboard delayed:** Ship without it. Existing `desktop_shell/` provides minimal status. Backend API and CLI are fully functional.

---

## 13. Resource Estimates and Timeline

### 13.1 FTE Estimates by Phase

| Phase | Backend FTE | Frontend FTE | DevOps FTE | Relative Effort |
|-------|:-----------:|:------------:|:----------:|:---------------:|
| 0: Foundation | 1.0 | 0.0 | 0.25 | Small |
| 1: Testing + Dashboard | 0.75 | 1.0 | 0.25 | Large |
| 2: Scaling + Packaging | 0.75 | 0.25 | 0.5 | Medium |
| 3: Docs + Private Beta | 0.5 | 0.25 | 0.25 | Small |
| 4: Public Beta | 0.5 | 0.25 | 0.25 | Small |
| 5: GA Release | 0.25 | 0.25 | 0.25 | Minimal |
| **Total** | | | | **~128 person-days** |

### 13.2 Infrastructure Costs (Monthly Estimate)

| Component | Dev | Staging | Production |
|-----------|----:|--------:|-----------:|
| Neo4j (self-hosted VM) | $0 (local Docker) | $50-100 | $100-200 |
| am-server compute | $0 (local) | $20-40 | $50-100 |
| Embedding API (Gemini) | Free tier | $10-30 | $30-100 |
| Monitoring (Grafana Cloud) | Free tier | Free tier | $30-50 |
| **Monthly total** | **$0** | **$80-170** | **$210-450** |

### 13.3 Phase Sequencing

```
Phase 0: Foundation
  ↓ (exit criteria met)
Phase 1: Testing + Dashboard  (two workstreams in parallel)
  ↓ (exit criteria met)
Phase 2: Scaling + Packaging
  ↓ (exit criteria met)
Phase 3: Docs + Private Beta
  ↓ (exit criteria met)
Phase 4: Public Beta
  ↓ (exit criteria met)
Phase 5: GA Release
```

Each transition occurs when the preceding phase's exit criteria (Section 11.1) are fully satisfied — not on a fixed calendar date.

### 13.4 Decision Gates

| Gate | When | Decision | Who Decides |
|------|------|----------|-------------|
| G1: Architecture freeze | End of Phase 0 | Confirm auth model, persistence migration, dashboard stack | Tech lead |
| G2: Beta readiness | End of Phase 2 | All contract tests pass, load test SLOs met, dashboard functional | Engineering + Product |
| G3: Public beta go/no-go | End of Phase 3 | 5 private beta partners active, no P0 bugs | Product + Engineering |
| G4: GA go/no-go | End of Phase 4 | All GA exit criteria met (Section 14) | Product + Engineering + Exec |

---

## 14. Success Metrics and Exit Criteria

### 14.1 Production-Ready Definition

The OpenClaw plugin is production-ready when ALL of the following are satisfied:

**Reliability:**
- API availability >= 99.5% over 14 consecutive days in staging
- 5xx error rate < 0.1% over 7-day rolling window
- 10-agent soak test passes for 7 consecutive days without data loss

**Performance:**
- All GA SLO targets met (Section 8.1) for 14 consecutive days
- Rollback drill completed successfully at least once

**Quality:**
- Zero open P0/P1 bugs
- All CI gates green on `main`
- Security scan clean (zero critical/high findings)
- TypeScript plugin coverage >= 80%
- Python am_server coverage >= 80%

**User Success:**
- Plugin install success rate >= 95% on supported hosts
- Time-to-first-memory p95 < 10 minutes
- NPS >= 40 from beta cohort

**Operations:**
- All 6 SRE runbooks written and exercised
- Monitoring dashboards operational with alerting configured
- Support runbook for top 5 failure modes documented

### 14.2 Key Business Metrics (Post-GA)

| Metric | 30-day Target | 90-day Target |
|--------|:---:|:---:|
| Total installs | 200 | 500 |
| Weekly active users | 80 | 150 |
| Weekly churn rate | < 2% | < 1.5% |
| Support ticket rate (% of active) | < 5% | < 3% |
| Memory searches per active user per day | >= 3 | >= 5 |

---

## 15. Assumptions, Constraints, and Open Questions

### 15.1 Assumptions

1. **OpenClaw host stability:** The `>=2026.4.5` host version remains backward-compatible through our GA timeline. No breaking SDK changes.
2. **Deployment model:** Default to self-hosted (local Docker) for beta. Hosted multi-tenant is a post-GA initiative.
3. **Single workspace per am-server:** v1 targets one workspace per server instance. Multi-tenant isolation is post-GA.
4. **Embedding provider:** Gemini is the default provider. OpenAI is supported as fallback. Both are configured via environment variables.
5. **Neo4j Community Edition:** Sufficient for 10-agent workload. Enterprise features (RBAC, clustering) are not required for v1.
6. **Team size:** 1-2 backend engineers, 1 frontend engineer, 0.25 DevOps. No dedicated QA.

### 15.2 Constraints

1. **Read-only during planning phase:** No code changes until plan is approved.
2. **Monorepo structure:** All changes stay within the existing monorepo. No new repositories.
3. **Python 3.10+ compatibility:** Backend code must run on Python 3.10, 3.11, and 3.12.
4. **Backward compatibility:** Existing `agentic-memory` CLI and `codememory` alias must continue to work.
5. **Plugin package name:** Must resolve npm scope before publishing (`@agentic-memory/openclaw`).

### 15.3 Open Questions

| # | Question | Impact | Resolution Path |
|---|----------|--------|-----------------|
| Q1 | Should the hosted path be the default offering, with self-hosted as enterprise-only? | GTM, pricing, infrastructure | Product decision by Gate G1 |
| Q2 | Does OpenClaw marketplace require a specific package format beyond `.tgz` + manifest? | Packaging, distribution | Verify with OpenClaw docs/team |
| Q3 | Is SSO required for GA or only for enterprise tier? | Auth implementation scope | Product decision by Gate G2 |
| Q4 | Should `augment_context` mode be enabled by default or remain opt-in? | User experience, performance | Data from private beta (Phase 3) |
| Q5 | What is the embedding cost budget per workspace per month? | Pricing, rate limiting | Finance/product decision by Gate G3 |
| Q6 | Should the desktop companion be a separate signed application or remain a browser-accessible shell? | Packaging complexity, user experience | Product decision by Gate G1 |
| Q7 | Is SpacetimeDB intended to replace or augment the current persistence layer? | Architecture, Phase 0 persistence migration | Tech lead decision by Gate G1 |

---

## Appendix A: SRE Runbook Outline

| ID | Title | Trigger |
|----|-------|---------|
| RB-001 | Provision new environment | New deployment |
| RB-002 | Rotate API keys | Scheduled or incident |
| RB-003 | Neo4j backup/restore | Scheduled or data loss |
| RB-004 | Scale API replicas / queue backlog | Load alert |
| RB-005 | Incident: memory search returns empty / API errors | Alert |
| RB-006 | Incident: embedding provider outage | Alert |

## Appendix B: Machine-Readable Artifact Templates (to produce during implementation)

```yaml
artifacts:
  - openapi/openclaw-agentic-memory.openapi.yaml
  - schemas/openclaw-session.schema.json
  - schemas/openclaw-turn.schema.json
  - schemas/memory-search-response.schema.json
  - cicd/github-actions-plugin-ci.yaml
  - cicd/github-actions-release.yaml
  - alerts/prometheus-alert-rules.yaml
  - design/dashboard-design-tokens.json
  - docker/docker-compose.prod.yml
  - examples/plugin-health-probe.ts
  - examples/e2e-test-matrix.md
```

## Appendix C: Key Files Reference

| Component | Path | Relevance |
|-----------|------|-----------|
| Plugin entry | `packages/am-openclaw/src/index.ts` | Plugin registration, 4 hooks |
| Plugin runtime | `packages/am-openclaw/src/runtime.ts` | Memory search + context engine |
| Plugin setup | `packages/am-openclaw/src/setup.ts` | Setup wizard + project CLI |
| Plugin transport | `packages/am-openclaw/src/backend-client.ts` | HTTP client (needs retry + structured errors) |
| Plugin types | `packages/am-openclaw/src/shared.ts` | Config + identity resolution |
| Plugin manifest | `packages/am-openclaw/openclaw.plugin.json` | OpenClaw host registration |
| Backend app | `src/am_server/app.py` | FastAPI factory (needs CORS + rate limit) |
| Backend auth | `src/am_server/auth.py` | Bearer token (needs multi-key) |
| OpenClaw routes | `src/am_server/routes/openclaw.py` | 8 endpoints |
| Backend models | `src/am_server/models.py` | Pydantic schemas (needs error model) |
| Neo4j connection | `src/agentic_memory/core/connection.py` | Pool config (needs timeout tuning) |
| Embedding service | `src/agentic_memory/core/embedding.py` | Multi-provider embeddings |
| Desktop shell | `desktop_shell/app.py` | FastAPI shell with proxy routes |
| Desktop UI | `desktop_shell/static/` | Vanilla HTML/JS (to be replaced) |
| OpenClaw tests | `tests/test_am_server.py` | 13 OpenClaw-specific test cases |
| Shared memory tests | `tests/test_openclaw_shared_memory.py` | Identity preservation, stress tests |
| CI workflow | `.github/workflows/ci.yml` | 3 jobs (needs 4+ more) |
| Docker Compose | `docker-compose.yml` | Neo4j service only |
