# Agentic Memory MCP Guidance

When exploring this codebase, prefer using the `agentic-memory` MCP tools over native tools when they can answer the question faster or with better repo context.

## Agentic Memory MCP Tools

### Tool List

- `search_codebase`
- `get_file_dependencies`
- `get_git_file_history`
- `get_commit_context`
- `identify_impact`
- `get_file_info`
- `trace_execution_path`
- `search_all_memory`
- `search_conversations`
- `get_conversation_context`
- `search_web_memory`
- `memory_ingest_research`
- `create_memory_entities`
- `create_memory_relations`
- `add_memory_observations`
- `delete_memory_entities`
- `delete_memory_relations`
- `delete_memory_observations`
- `search_memory_nodes`
- `read_memory_graph`
- `backfill_memory_embeddings`

### Tool Descriptions

| Tool | Description |
|------|-------------|
| `search_codebase(query, limit, domain)` | Semantically search the codebase for functionality using vector similarity. Supports `code`, `git`, and `hybrid` domains. |
| `get_file_dependencies(file_path)` | Returns files this file imports and files that import this file. Useful for understanding upstream and downstream dependencies. |
| `get_git_file_history(file_path, limit)` | Returns commit history for a file from the git graph domain. |
| `get_commit_context(sha, include_diff_stats)` | Returns detailed metadata and optional diff stats for a commit SHA. |
| `identify_impact(file_path, max_depth)` | Identifies the blast radius of changes to a file by returning transitive dependents organized by depth. |
| `get_file_info(file_path)` | Returns detailed file info including defined functions, classes, and direct import relationships. |
| `trace_execution_path(start_symbol, max_depth)` | Traces one function's likely execution path on demand instead of relying on a repo-wide call graph. |
| `search_all_memory(query, limit, modules)` | Searches across code, git, web research, and conversation memory in one combined result set. |
| `search_conversations(query, limit)` | Searches stored conversation history for relevant prior exchanges. |
| `get_conversation_context(query, limit)` | Retrieves the most relevant prior conversation context bundle for the current task. |
| `search_web_memory(query, limit)` | Searches previously ingested research and web findings. |
| `memory_ingest_research(content, title, type, findings, citations, ...)` | Saves research findings and reports into persistent memory for later retrieval. |
| `create_memory_entities(entities)` | Creates or updates repo-scoped concept or decision nodes for agent-authored durable memory. |
| `create_memory_relations(relations)` | Creates typed relations between memory entities such as `DEPENDS_ON`, `DECIDES`, or `RELATES_TO`. |
| `add_memory_observations(observations)` | Appends additional observations to an existing memory entity without replacing prior observations. |
| `delete_memory_entities(entity_names)` | Deletes memory entities by name from the repo-scoped memory graph. |
| `delete_memory_relations(relations)` | Deletes typed relations between existing memory entities. |
| `delete_memory_observations(observations)` | Removes specific observations from existing memory entities. |
| `search_memory_nodes(query, limit)` | Searches the writable memory graph for abstract concepts, design decisions, and stored observations. |
| `read_memory_graph()` | Returns a summary snapshot of the current repo-scoped memory graph. |
| `backfill_memory_embeddings(limit, only_missing)` | Regenerates embeddings for memory entities, mainly for repair or migration workflows. |

## Memory Graph

1. **Agentic Memory (`agentic-memory` MCP):** Tracks code structure, git history, research memory, conversation memory, and a writable repo-scoped concept graph through a shared Neo4j-backed retrieval surface.

---
> TODO: Healthcare public-dataset experiment planning lives in `D:\code\agentic-memory\docs\research\healthcare-experiments\README.md`. Before trying to run any MIMIC-backed work, verify whether PhysioNet / MIMIC access is approved and configured on this machine; as of 2026-04-14, no repo-local or user-home credentials or downloaded dataset directories were found.
>
> TODO: Managed hosted publication is now live at `https://backend.agentmemorylabs.com` and `https://mcp.agentmemorylabs.com`. OpenAI submission was sent on 2026-04-19 after real ChatGPT validation, domain verification, tool scan, screenshots, reviewer prompts, and submission assets were completed. Before claiming publication is complete, capture the OpenAI case/reference and approval evidence, run real Claude validations against the public MCP surfaces, and update `docs/publication/status/*` with real approval/listing evidence.
---
# Agentic Memory Repo Guide For Agents

This file is the repo-local operating guide for coding agents working inside
`D:\code\agentic-memory`.

It is intentionally practical. Use it to answer:

- what this repo currently is
- which product paths are primary vs secondary
- where the important code and docs live
- how to run Agentic Memory against this repository itself
- which assumptions are safe and which ones are not

---

## 1. Current Product Shape

Agentic Memory is a multi-domain memory system for AI agents. The same project
currently exposes three related but distinct surfaces:

1. **Core code/research/conversation memory CLI + MCP**
   - Python package: `agent-memory-labs`
   - Console command: `agent-memory`
   - Main code: `src/agentic_memory`
   - Purpose: index repositories, ingest research/conversation memory, expose
     retrieval tools over MCP and CLI
2. **Hosted/self-hosted backend for client integrations**
   - Main code: `src/am_server`
   - Purpose: REST/OpenClaw-facing backend used by plugins and future hosted
     clients
3. **OpenClaw plugin**
   - Package: `packages/am-openclaw`
   - npm package name: `agentic-memory-openclaw`
   - Runtime plugin id: `agentic-memory`

The important product distinction right now:

- **Managed hosted beta** is the preferred user-facing path
- **Self-hosted full stack** remains supported as the operator path

Do not blur those two paths in docs or implementation.

---

## 2. Architecture Boundaries That Matter

Keep this boundary clear in code and docs:

- client/plugin/app -> talks to backend URL
- backend (`am-server`) -> talks to Neo4j, provider APIs, optional temporal
  services, and product state
- databases/providers are backend concerns, not end-user plugin concerns

For OpenClaw specifically:

- normal users should think in terms of:
  - install plugin
  - run `doctor`
  - run `setup`
  - connect to hosted or self-hosted backend
- they should **not** need to reason about Neo4j, SpacetimeDB, or Grafana to
  use the managed path

---

## 3. Repo Areas

### Core memory package

- `D:\code\agentic-memory\src\agentic_memory`
  - CLI, code graph indexing, research/chat ingest, MCP server, product-state helpers

### Hosted/self-hosted backend

- `D:\code\agentic-memory\src\am_server`
  - FastAPI backend for `/health`, `/metrics`, `/openclaw/*`, onboarding contract,
    auth, and hosted/self-hosted integration logic

### OpenClaw plugin

- `D:\code\agentic-memory\packages\am-openclaw`
  - install/setup/doctor UX and OpenClaw-facing client integration

### Desktop shell

- `D:\code\agentic-memory\desktop_shell`
  - lightweight local control plane / browser-based shell

### Planning

- `D:\code\agentic-memory\.planning`
  - active execution registry, phases, handoffs, roadmap

### Docs

- `D:\code\agentic-memory\README.md`
  - broad product overview and primary quickstart
- `D:\code\agentic-memory\docs\INSTALLATION.md`
  - installation guide across product surfaces
- `D:\code\agentic-memory\docs\SETUP_FULL_STACK.md`
  - self-hosted/operator full-stack setup
- `D:\code\agentic-memory\docs\TROUBLESHOOTING.md`
  - common failures and repair steps
- `D:\code\agentic-memory\docs\PRODUCT_DOGFOODING.md`
  - repeatable local validation loop
- `D:\code\agentic-memory\docs\openclaw\`
  - OpenClaw-specific quickstart, deployment, beta ops, support, marketplace

---

## 4. Primary Documentation Paths

When updating docs, keep these paths aligned:

### Managed hosted beta

- `D:\code\agentic-memory\docs\INSTALLATION.md`
- `D:\code\agentic-memory\docs\openclaw\guides\PRIVATE_BETA_QUICKSTART.md`
- `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`

### Self-hosted/operator path

- `D:\code\agentic-memory\docs\SETUP_FULL_STACK.md`
- `D:\code\agentic-memory\docs\TROUBLESHOOTING.md`
- `D:\code\agentic-memory\docs\PRODUCT_DOGFOODING.md`

### Public plugin/publication path

- `D:\code\agentic-memory\docs\PUBLIC_PLUGIN_SURFACES.md`
- `D:\code\agentic-memory\docs\publication\`

If behavior changes, update the docs in all affected paths rather than leaving
stale parallel stories.

---

## 5. Running Agentic Memory On This Repository

This repo already contains a local repo config:

- `D:\code\agentic-memory\.codememory\config.json`

That means this repository is already initialized for code memory. You should
normally **not** re-run `agent-memory init` unless you intentionally want to
replace the local config.

### Local prerequisites for code-memory commands

The current local config expects:

- Neo4j at `bolt://localhost:7687`
- username `neo4j`
- password `password`

It currently defaults the code embedding module to Gemini:

- provider: `gemini`
- model: `gemini-embedding-2-preview`

### Windows local command flow for this repo

From `D:\code\agentic-memory`:

```powershell
docker compose up -d neo4j
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli status --json
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli index --json
```

Why these commands use the venv Python directly:

- `agent-memory` may not be on `PATH` on this machine
- `python -m agentic_memory.cli ...` avoids shell-path ambiguity

### Expected local states

- if Neo4j is down:
  - `status` fails with a connection error to `localhost:7687`
- if Neo4j is up but the repo has never been indexed:
  - `status` returns zero-ish counts
- if indexing is configured but no embedding key is available:
  - `index` may fail once the pipeline reaches embedding generation

### Do not assume these commands are cheap

- `index` can take time on a repo this size
- `watch` is long-running
- `build-calls` is explicitly experimental

Use:

- `status` for a quick state check
- `index` for one-time ingest
- `watch` only when you intentionally want a foreground long-running observer

---

## 6. Backend And OpenClaw Reality

For the current OpenClaw integration:

- plugin package install surface:
  - `openclaw plugin install agentic-memory-openclaw`
  - some OpenClaw hosts may expose `plugins install`; docs should call out host-version differences when relevant
- runtime config/setup surface:
  - `openclaw agentic-memory doctor`
  - `openclaw agentic-memory setup`
- backend truth source:
  - `GET /health/onboarding`

The backend currently distinguishes:

- backend reachable
- setup ready
- capture-only ready
- augment-context ready

Do not describe plain `/health` success as if setup is complete.

---

## 7. Deployment Modes

### Managed hosted beta

- preferred default story
- backend operated by us
- databases/provider keys operated by us
- user mainly needs:
  - plugin install
  - backend URL
  - API key

### Self-hosted full stack

- supported operator path
- operator runs:
  - Neo4j
  - optional temporal services
  - `am-server`
  - plugin against their backend URL

### Not a first-class mode right now

Do not frame this as a standard supported mode:

- hosted FastAPI + customer-managed databases

That may become an advanced exception later, but it should not shape the main
docs or onboarding defaults now.

---

## 7.1 Publication Snapshot (2026-04-14)

Current managed-hosted/publication reality:

- backend origin
  - `https://backend.agentmemorylabs.com`
  - published from the existing GCP VM through Cloudflare Tunnel
- public reviewer host
  - `https://mcp.agentmemorylabs.com`
  - fronted by the Cloudflare Worker in `deploy/cloudflare-public-edge`
- current live runtime shape
  - `am-server` runs directly on the VM under `systemd`
  - current live Neo4j target is loopback `bolt://127.0.0.1:7667`
- current live verification already performed
  - `https://backend.agentmemorylabs.com/health`
  - `https://backend.agentmemorylabs.com/health/onboarding`
  - `https://mcp.agentmemorylabs.com/publication/agentic-memory`
  - `https://mcp.agentmemorylabs.com/publication/privacy`
  - `https://mcp.agentmemorylabs.com/health`
- current live reviewer auth posture
  - public MCP now supports OAuth 2.0 authorization code flow for the public
    OpenAI review surface
  - reviewer-key fallback still exists through `AM_SERVER_PUBLIC_MCP_API_KEYS`
  - docs must stay truthful about whether a given surface is using OAuth,
    bearer fallback, or both

Current publication blockers:

- wait for OpenAI review outcome and capture the review/case reference
- run a real Claude validation against `/mcp-claude`
- attach real OpenAI and Anthropic approval/listing evidence in
  `docs/publication/status/`

---

## 8. Common Local Assumptions To Avoid

Avoid these mistakes in code, docs, and testing:

- assuming `agent-memory` is on `PATH`
- assuming Neo4j is already running locally
- assuming `localhost:3000` belongs to SpacetimeDB
- assuming saved OpenClaw defaults are the same as the actual intended backend
- assuming plugin install implies backend readiness
- assuming managed and self-hosted docs can share one blended quickstart
- assuming the live public MCP auth story is already OAuth-based

Prefer explicitness:

- explicit backend URL
- explicit deployment mode
- explicit `STDB_URI`
- explicit note when a prompt default comes from saved config

---

## 9. Agent Editing Expectations In This Repo

When making non-trivial code changes:

- add or maintain structured docstrings
- add targeted comments before non-obvious logic
- keep code understandable to a future agent or beginner reader

When making documentation changes:

- keep the same command examples consistent across:
  - `README.md`
  - `docs/INSTALLATION.md`
  - `docs/TROUBLESHOOTING.md`
  - `docs/openclaw/*`
- include plain Windows paths in user-facing references when helpful
- prefer operational accuracy over aspirational wording

When running verification:

- prefer direct commands with real outputs over assumptions
- report blockers exactly
- do not claim local indexing or hosted flows work unless they were actually run

---

## 10. Quick Command Reference

### Core code-memory loop on this repo

```powershell
docker compose up -d neo4j
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli status --json
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli index --json
```

### Start backend locally

```powershell
.\.venv-agentic-memory\Scripts\dotenv.exe -f .env run -- .\.venv-agentic-memory\Scripts\python.exe -m am_server.server
```

### Start desktop shell locally

```powershell
.\.venv-agentic-memory\Scripts\python.exe -m desktop_shell --backend-url http://127.0.0.1:8765
```

### OpenClaw managed/self-hosted validation

```bash
openclaw agentic-memory doctor --hosted --backend-url https://backend.agentmemorylabs.com
openclaw agentic-memory doctor --self-hosted --backend-url http://127.0.0.1:8765
```

---

## 11. If You Need More Context

Read these first, in this order:

1. `D:\code\agentic-memory\README.md`
2. `D:\code\agentic-memory\docs\INSTALLATION.md`
3. `D:\code\agentic-memory\docs\TROUBLESHOOTING.md`
4. `D:\code\agentic-memory\docs\SETUP_FULL_STACK.md`
5. `D:\code\agentic-memory\docs\openclaw\README.md`
6. `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`

If the question is about planning and current intended direction, check:

- `D:\code\agentic-memory\.planning\STATE.md`
- `D:\code\agentic-memory\.planning\ROADMAP.md`
- `D:\code\agentic-memory\.planning\execution\tasks.json`
