# OpenClaw Plugin: Production Readiness Blueprint



## Executive Summary



**What**: Take the OpenClaw plugin from functional single-agent prototype (v0.1.0) to production-ready GA with 10-agent concurrency, premium dashboard, marketplace distribution, and full operational maturity.



**Why**: The OpenClaw plugin is the highest-leverage distribution channel for Agentic Memory. A frictionless install + premium dashboard positions AM as the default memory layer for the OpenClaw ecosystem — capturing every agent's conversation, code, and research into a shared structural graph that persists across sessions, devices, and projects.



**Current State**: Core plugin code is functional. Both memory and context-engine slots wired. Setup wizard, turn ingestion, memory search, and project lifecycle all implemented. Gaps: no structured error handling, no distributed observability, no load testing, no dashboard UI, no marketplace packaging, no documentation beyond integration plan.



**Timeline**: 20 weeks across 5 phases (Foundation → Testing → Dashboard → Scaling/Deploy → GTM/GA)



**ROI Metrics**:

- GA target: 200 installs, 80 active users, <2% weekly churn

- Memory captures reduce context-switching cost by eliminating manual context reload

- Cross-device recall creates lock-in: users won't leave once their agent memory is centralized



---



## Phase 0: Foundation Hardening (Weeks 1-3)



### 0.1 Structured Error Reporting



**Problem**: `backend-client.ts:42-49` throws generic `Error` with raw response text. No error taxonomy, no error codes, no structured JSON.



**Deliverables**:

- Add `ErrorResponse` Pydantic model to `src/am_server/models.py`: `{ "error": { "code": str, "message": str, "request_id": str, "details": dict } }`

- Add FastAPI exception handler in `src/am_server/app.py` rendering standard error shape

- Update `packages/am-openclaw/src/backend-client.ts`:

  - Parse structured error into typed `AgenticMemoryBackendError { code, message, requestId }`

  - Add retry with exponential backoff for transient errors (429, 503), max 3 retries

  - Add configurable request timeout (default 10s)



**Files**:

- `src/am_server/models.py`

- `src/am_server/app.py`

- `packages/am-openclaw/src/backend-client.ts`



### 0.2 Observability Foundation



**Problem**: Telemetry is SQLite-only local sidecar (`src/agentic_memory/telemetry.py`). Request ID middleware exists but connects to nothing.



**Deliverables**:

- Add OpenTelemetry SDK to backend (optional dep group `[observability]` in `pyproject.toml`)

- Instrument `src/am_server/middleware.py` to emit spans per request

- New `src/am_server/metrics.py` with 6 core metrics:

  1. `am_ingest_turns_total` (counter) — labels: workspace_id, agent_id, source_key

  2. `am_search_requests_total` (counter) — labels: workspace_id, module

  3. `am_search_latency_seconds` (histogram) — labels: module

  4. `am_context_resolve_latency_seconds` (histogram)

  5. `am_neo4j_query_latency_seconds` (histogram) — labels: operation

  6. `am_embedding_api_latency_seconds` (histogram) — labels: provider

- Add Prometheus-compatible `/metrics` endpoint

- Add fire-and-forget `POST /openclaw/telemetry/event` for plugin-side timing



**Files**:

- `src/am_server/middleware.py`

- New: `src/am_server/metrics.py`

- `pyproject.toml` (new optional deps)



### 0.3 Security Hardening



**Problem**: Auth is single bearer token via string equality (`src/am_server/auth.py:39`). No CORS, no rate limiting, no input bounds.



**Deliverables**:

- CORS middleware in `src/am_server/app.py` with explicit origin allowlist

- Rate limiting: 100 req/s per workspace_id (ingest), 50 req/s (search) — `slowapi` or custom token bucket

- Multi-key support: `AM_SERVER_API_KEYS` (comma-separated), backward-compatible with single `AM_SERVER_API_KEY`

- Input validation bounds on all Pydantic models: content max 100KB, query max 2000 chars, limit max 50

- `docs/SECURITY.md`: threat model document (single-tenant local deployment, bearer token auth, no multi-tenant isolation)



**Files**:

- `src/am_server/auth.py`

- `src/am_server/app.py`

- `src/am_server/models.py`

- New: `docs/SECURITY.md`



### Phase 0 Exit Criteria

- [ ] All OpenClaw endpoints return structured error JSON on failure

- [ ] Prometheus `/metrics` endpoint serves 6 defined metrics

- [ ] CORS and rate limiting middleware active

- [ ] `backend-client.ts` retries transient errors with backoff



---



## Phase 1: Testing & Performance Baseline (Weeks 3-6)



### 1.1 Contract Tests



**New file**: `tests/test_openclaw_contract.py`

- For each of the 8 OpenClaw endpoints: validate request schema matches Pydantic model, response shape matches what `runtime.ts` parses

- Source of truth: `OpenClaw*Request`/`OpenClaw*Response` models in `src/am_server/models.py`

- Generate TypeScript type assertions from Pydantic models for cross-language contract enforcement



### 1.2 TypeScript Plugin Tests



**New directory**: `packages/am-openclaw/tests/`

- Add `vitest` to dev deps

- Unit tests for `shared.ts`: `resolveAgenticMemoryPluginConfig`, `normalizeMessageText`, `estimateTokenCount`, `parseOpenClawSessionIdentity`, `buildSessionId`

- Mock-server integration tests for `backend-client.ts`

- Runtime tests for `AgenticMemorySearchManager.search()` and `AgenticMemoryContextEngine.assemble()` with mocked backend



### 1.3 Load Tests



**New file**: `tests/load/test_openclaw_load.py`

- Framework: `locust` or `httpx` async client

- Simulate 10 concurrent agents: register session, loop (ingest turn + occasional search)

- Target: 10 agents x 2 turns/s = 20 ingest req/s sustained for 5 minutes

- Measure: p50/p95/p99 latency per endpoint, Neo4j pool utilization, embedding API rate limit hits



### 1.4 E2E Test



**New file**: `tests/e2e/test_openclaw_e2e.py`

- Start `am-server` in subprocess

- Simulate full plugin lifecycle: register session → ingest 5 turns → search → read → resolve context

- Assert round-trip data correctness



### 1.5 Chaos Tests



- Backend unavailable during ingest → expect graceful failure, no data corruption

- Neo4j connection pool exhaustion → expect 503, not hang

- Embedding API timeout → expect degraded search (text-only), not crash



### 1.6 Performance Targets



| Metric | Target | Method |

|--------|--------|--------|

| Ingest turn latency (p95) | < 200ms | Load test w/ Neo4j + embedding API |

| Search latency (p95) | < 500ms | 10 concurrent searches |

| Context resolve latency (p95) | < 800ms | Includes search + formatting |

| Memory footprint (backend) | < 512MB RSS | Process monitoring under load |

| Neo4j heap | < 2GB | Docker stats under load |

| Embedding API rate | < 60 req/min (free) / 300 req/min (paid) | Metrics tracking |



### 1.7 Bottleneck Analysis (Pre-identified)



1. **Connection pool**: `connection.py:32` sets `connection_acquisition_timeout=60` — too high for real-time. Reduce to 10s, fail fast.

2. **Singleton pipeline**: `lru_cache(maxsize=1)` in `dependencies.py` shares one pipeline instance. Concurrent ingest calls serialize on Neo4j session. Fix: open new session per request, or add async write queue.

3. **Embedding rate limits**: 10 agents at 2 turns/s = 120 embedding calls/min — exceeds Gemini free tier. Fix: batch embeddings (10 texts/call), add backpressure queue, skip embedding on rate limit (ingest text, embed later).



### Phase 1 Exit Criteria

- [ ] All contract tests pass in CI

- [ ] Load test sustains 20 req/s for 5 min with p95 < 500ms

- [ ] TypeScript plugin >= 80% line coverage

- [ ] E2E test passes in CI

- [ ] Chaos tests demonstrate graceful degradation



---



## Phase 2: Dashboard UI (Weeks 5-10)



### 2.1 Architecture Decision



**Replace** existing vanilla HTML/JS in `desktop_shell/static/` (3 files, no build system) with a React SPA. Serve from existing `desktop_shell/app.py` FastAPI app.



**Stack**:

- React 18 + TypeScript + Vite

- Radix UI primitives + custom styled components (lightweight, not MUI)

- Recharts for time-series visualizations

- TanStack Query for data fetching with auto-refresh

- Package location: `packages/am-dashboard/` (new npm workspace)



### 2.2 Design Tokens



Extend existing dark-mode palette from `desktop_shell/static/styles.css`:



```

Existing:                    New additions:

--bg: #08111f               --success: #34d399

--bg-soft: #0e192d          --warning: #fbbf24

--panel: rgba(15,25,44,0.82) --danger: #f87171

--accent: #7fd1ff            --radius-sm: 6px

--accent-strong: #4fb0ff     --radius-md: 12px

                             --radius-lg: 20px

                             --font-mono: 'JetBrains Mono', 'SF Mono', monospace

```



### 2.3 Dashboard Pages



**Page 1 — Overview / Home**

- Top row: 4 metric cards (active agents, turns ingested today, searches today, memory health score)

- Middle: Ingestion activity timeline (area chart, 24h window, 5-min buckets)

- Bottom: Recent agent sessions table (agent_id, device_id, last activity, turn count, project)



**Page 2 — Agent Activity**

- Per-agent detail view (sidebar selection)

- Turn timeline: scrollable list with role badges, timestamps, token counts

- Session lifecycle state machine visualization



**Page 3 — Memory Health**

- Neo4j connection pool gauge (current/max)

- Vector index stats: node count per index

- Embedding API health: success rate, latency histogram, rate limit hits

- Storage growth chart



**Page 4 — Search Quality**

- Recent searches with relevance scores

- Score distribution histogram

- Hit source breakdown (code vs research vs conversation)

- Latency percentile chart



**Page 5 — Workspace Management**

- Workspace/device/agent tree view

- Active projects per workspace

- Project lifecycle controls

- Integration status grid



### 2.4 New Backend Endpoints for Dashboard



Add to `src/am_server/routes/dashboard.py`:

1. `GET /openclaw/metrics/summary` — aggregated counters

2. `GET /openclaw/agents/{agent_id}/sessions` — session history

3. `GET /openclaw/health/detailed` — Neo4j pool stats, index stats, embedding health

4. `GET /openclaw/search/recent` — last N searches with scores

5. `GET /openclaw/workspaces` — workspace/device/agent tree



### 2.5 Accessibility (WCAG 2.1 AA)

- Keyboard navigation for all interactive elements

- Screen reader labels for all charts (aria-label with data summary)

- Color contrast >= 4.5:1 for all text

- Respect `prefers-reduced-motion` for animations



### Phase 2 Exit Criteria

- [ ] Dashboard builds and serves from `desktop_shell/`

- [ ] All 5 pages render with real backend data

- [ ] Lighthouse accessibility score >= 90

- [ ] No console errors in browser



---



## Phase 3: Scaling, Deployment & Packaging (Weeks 8-14)



### 3.1 10-Agent Write Path Optimization



- **Async write queue**: `asyncio.Queue` (depth 1000) between `/openclaw/memory/ingest-turn` and `ConversationIngestionPipeline`. Background worker drains + batches.

- **Batched Neo4j writes**: Group up to 10 turns into single `UNWIND` Cypher instead of one MERGE per turn

- **Batched embedding**: Accumulate up to 10 texts per Gemini API call

- **Backpressure**: On embedding rate limit, ingest text immediately, queue embedding for background retry



### 3.2 Read Path Optimization



- TTL cache (60s) for `/openclaw/project/status` per workspace_id

- Query result cache for identical searches within 30s window



### 3.3 Resource Budget (10 agents)



| Component | Allocation | Notes |

|-----------|-----------|-------|

| Neo4j heap | 4GB | Up from 2GB in current docker-compose |

| Neo4j pagecache | 1GB | Existing |

| Backend RSS | 512MB | FastAPI + pipelines + OTel |

| Embedding API | 300 req/min | Gemini paid tier, batched |

| Neo4j pool | 50 connections | Existing, sufficient |

| Uvicorn workers | 4 | Up from 1 default |



### 3.4 Environment Provisioning



**Dev** (laptop):

- `docker-compose up` (Neo4j)

- `pip install -e ".[dev,observability]"`

- `npm run build --workspace agentic-memory`

- Single uvicorn worker, no TLS



**Staging**:

- Docker Compose: Neo4j + am-server + dashboard

- Neo4j 4GB heap, persistent volume

- am-server: 2 workers behind Caddy reverse proxy with TLS

- Jaeger for traces, Prometheus + Grafana for metrics



**Production**:

- Neo4j on dedicated VM or Neo4j Aura (managed)

- am-server in Docker behind LB with TLS termination

- 4 uvicorn workers, horizontal scaling to 2+ containers

- Grafana Cloud or self-hosted for observability

- Automated backups: `neo4j-admin database dump` on schedule



### 3.5 CI/CD Pipeline Expansion



Add to `.github/workflows/ci.yml`:



| Job | What |

|-----|------|

| **ts-build-test** | `npm ci && npm run build && npx vitest run` for am-openclaw |

| **contract-tests** | `pytest -m contract` with Neo4j service |

| **dashboard-build** | `npm run build --workspace am-dashboard` + Lighthouse audit |

| **security-scan** | `pip-audit` + `npm audit` + `trivy` on Docker image |



New workflow `.github/workflows/release.yml` (tag `v*`):

- Build Python wheel + sdist

- Build TypeScript plugin dist

- Build dashboard dist

- Create GitHub Release with all artifacts

- Publish to PyPI + npm



### 3.6 Plugin Packaging for OpenClaw Marketplace



- Remove `"private": true` from `packages/am-openclaw/package.json`

- Add `"license": "MIT"`, `"repository"`, `"homepage"`, `"bugs"` fields

- Build distributable `.tgz` via `npm pack`

- Install command: `openclaw install agentic-memory`

- Version migration logic in `setup-api.js` for future schema changes



### 3.7 Auto-Updater Strategy



- **Plugin**: Rely on OpenClaw marketplace update flow (host compares installed vs registry version)

- **Backend**: Publish versioned Docker images to ghcr.io

  - `GET /health` includes `"version": "x.y.z"` from `pyproject.toml`

  - `GET /openclaw/update-check` compares running version against latest GitHub Release

  - Dashboard shows update notification when newer version available

  - Operator applies by pulling new image + restart



### 3.8 Rollback Strategy



- Docker images tagged by version — rollback = change image tag

- Neo4j schema migrations are additive only (`CREATE IF NOT EXISTS`) — no destructive DDL

- Plugin config schema versioned (`schema_version: 1`) for future migrations

- Product state JSON versioned for migration support



### Phase 3 Exit Criteria

- [ ] 10-agent load test passes (20 ingest req/s, p95 < 200ms)

- [ ] CI builds and packages the plugin artifact

- [ ] Docker image published to ghcr.io

- [ ] Rollback tested (version N → N-1 → N with no data loss)

- [ ] All 3 environments provisioned and documented



---



## Phase 4: Documentation, Distribution & GTM (Weeks 12-18)



### 4.1 Documentation Deliverables



| Document | Purpose |

|----------|---------|

| `docs/OPENCLAW_QUICKSTART.md` | 5-minute setup: install → verify memory capture |

| `docs/OPENCLAW_API_REFERENCE.md` | All 8 endpoints with request/response examples, error codes |

| `docs/OPENCLAW_ARCHITECTURE.md` | Data flow diagram, identity model, project lifecycle |

| `docs/OPENCLAW_SCALING.md` | 10-agent config, Neo4j tuning, embedding quotas |

| `docs/OPENCLAW_TROUBLESHOOTING.md` | Common errors, diagnostic commands, log analysis |

| `docs/SRE_RUNBOOK.md` | Incident response: pool exhaustion, rate limits, OOM, corruption recovery |

| `docs/SECURITY.md` | Threat model, auth, secrets management, network policy |



### 4.2 Sample Artifact Templates



- **OpenAPI spec**: Export from FastAPI `/openapi.json`, commit as `docs/openapi.yaml`

- **Data model diagram**: Neo4j schema visualization (nodes, relationships, indexes)

- **Docker Compose prod template**: `docker-compose.prod.yml` with TLS, resource limits, health checks

- **Plugin config template**: Example configs for memory-only and memory+context modes



### 4.3 Marketplace Listing



- Title: "Agentic Memory"

- Tagline: "Structural memory that follows your agents across devices and sessions"

- Categories: Memory, Context Engine

- Screenshots: Dashboard overview, agent activity, search quality

- Pricing: Free (open source), premium support tier optional



### 4.4 Onboarding Funnel



1. Marketplace discovery → install (`openclaw install agentic-memory`)

2. Setup wizard → backend verification (`openclaw agentic-memory setup`)

3. First session → memory capture confirmed

4. First search → memory retrieval working

5. Multi-device → cross-device recall proven

6. Context augmentation → optional upgrade to `augment_context` mode



### 4.5 Go-To-Market Timeline



| Milestone | Week | Target |

|-----------|------|--------|

| Private beta | 14 | 5 invited users, 3 complete setup, 2 active >7 days |

| Public beta | 16 | 50 installs, 20 active (>=1 search/day), NPS >= 40 |

| GA (v1.0.0) | 20 | 200 installs, 80 active, <2% weekly churn |



### 4.6 GTM Positioning



"The only shared memory layer for OpenClaw that understands code structure, research context, and conversation history across all your agents and devices."



- Default: memory plugin ON, context engine OFF

- Upgrade path: one config switch to enable `augment_context`

- Competitive moat: no other plugin captures structured code + research + conversation in a unified graph



### 4.7 Support & Feedback Loops



- GitHub Issues for bugs

- GitHub Discussions for questions

- Discord channel (if OpenClaw community exists)

- Telemetry events (opt-in): setup completion rate, search frequency, error rates

- Monthly user survey

- GitHub issue triage every 48 hours



### Phase 4 Exit Criteria

- [ ] All 7 documentation files written and reviewed

- [ ] Marketplace listing submitted

- [ ] 5 private beta users onboarded and actively using

- [ ] OpenAPI spec committed



---



## Phase 5: GA Release (Weeks 18-20)



### Deliverables

- Incorporate public beta feedback

- Close all P0 bugs

- SRE runbook exercised in fire drill

- Final performance validation under production-like load

- Version bump to v1.0.0

- Public announcement



### Phase 5 Exit Criteria

- [ ] NPS >= 40 from beta users

- [ ] No open P0 bugs

- [ ] SRE fire drill completed successfully

- [ ] v1.0.0 tag pushed, marketplace listing live



---



## Risk Assessment



| Risk | L | I | Mitigation |

|------|---|---|-----------|

| Neo4j write throughput at 10 agents | H | H | Async write queue + batched UNWIND + pool tuning |

| Gemini embedding API rate limits | H | H | Batch embedding + backpressure queue + paid tier |

| OpenClaw host SDK breaking changes | M | H | Pin minHostVersion + contract tests + rapid patches |

| Neo4j CE lacks enterprise features (RBAC, clustering) | M | M | Document limitation, recommend Aura for enterprise |

| ProductStateStore JSON corruption under concurrency | M | M | Add file locking or migrate to SQLite |

| Supply chain vulnerability in deps | L | H | Dependabot + pip-audit + npm audit in CI |

| Data privacy: conversation content in Neo4j | - | V | Document retention policy + add purge endpoint |



### Contingency Plans



- **Neo4j can't handle write load**: Switch to async ingestion with Redis Streams or local SQLite WAL queue. Endpoint returns 202, background workers drain to Neo4j.

- **Gemini embedding unreliable**: Automatic failover chain Gemini → OpenAI → skip. `EmbeddingService` in `src/agentic_memory/core/embedding.py` already supports both providers.

- **Dashboard delayed**: Ship without it. Existing `desktop_shell/` provides minimal status. Backend API and CLI are fully functional.



---



## Dependency Map



```

Phase 0 (Foundation)

  ├──→ Phase 1 (Testing + Perf)

  │      └──→ Phase 3 (Scaling + Deploy)

  └──→ Phase 2 (Dashboard)          │

         └───────────────────────────┤

                                     └──→ Phase 4 (Docs + GTM)

                                            └──→ Phase 5 (GA)

```



Phases 1 and 2 run in parallel after Phase 0. Phase 3 depends on Phase 1 benchmarks. Phase 4 depends on Phase 2 (screenshots) and Phase 3 (packaging).



---



## Key Files Reference



| Component | Path | Relevance |

|-----------|------|-----------|

| Plugin entry | `packages/am-openclaw/src/index.ts` | Plugin registration |

| Plugin runtime | `packages/am-openclaw/src/runtime.ts` | Memory search + context engine |

| Plugin setup | `packages/am-openclaw/src/setup.ts` | Setup wizard + project commands |

| Plugin transport | `packages/am-openclaw/src/backend-client.ts` | HTTP client (needs retry) |

| Plugin types | `packages/am-openclaw/src/shared.ts` | Config + identity resolution |

| Plugin manifest | `packages/am-openclaw/openclaw.plugin.json` | OpenClaw host registration |

| Backend app | `src/am_server/app.py` | FastAPI factory (needs CORS/rate limit) |

| Backend auth | `src/am_server/auth.py` | Bearer token (needs multi-key) |

| OpenClaw routes | `src/am_server/routes/openclaw.py` | 8 endpoints |

| Backend models | `src/am_server/models.py` | Pydantic schemas (needs error model) |

| Neo4j connection | `src/agentic_memory/core/connection.py` | Pool config (needs timeout tuning) |

| Embedding service | `src/agentic_memory/core/embedding.py` | Multi-provider embeddings |

| Existing telemetry | `src/agentic_memory/telemetry.py` | SQLite sidecar |

| Existing UI | `desktop_shell/static/` | Vanilla HTML/JS (to be replaced) |

| Existing integration plan | `docs/PLAN-openclaw-integration.md` | Status snapshot as of 2026-04-07 |

| OpenClaw test harness | `tests/openclaw_harness.py` | Synthetic workload generator |

| OpenClaw integration tests | `tests/test_openclaw_shared_memory.py` | Identity preservation tests |

| CI workflow | `.github/workflows/ci.yml` | 3 jobs (needs 4 more) |

| Docker Compose | `docker-compose.yml` | Neo4j service |



---



## Verification Plan



After implementation of each phase:



1. **Phase 0**: Hit each OpenClaw endpoint with invalid input → verify structured error JSON. Curl `/metrics` → verify 6 metric names. Test CORS preflight. Test rate limit (burst 200 req → expect 429 after 100).

2. **Phase 1**: `pytest -m contract` passes. `pytest tests/load/` sustains targets. `npx vitest run` in am-openclaw with coverage report. `pytest tests/e2e/` passes.

3. **Phase 2**: `npm run build --workspace am-dashboard` succeeds. Open dashboard in browser, verify all 5 pages render. Run Lighthouse audit.

4. **Phase 3**: Run 10-agent load test for 5 min, verify p95 < 200ms ingest. `docker build` + push to ghcr.io. Pull previous version image, verify rollback.

5. **Phase 4**: Review all 7 docs for completeness. Submit marketplace listing. Onboard 5 beta users, track funnel conversion.

6. **Phase 5**: Run full regression suite. SRE fire drill. Tag v1.0.0.

