# 🧠 Agentic Memory
https://github.com/jarmen423/agentic-memory

> **Multi-Domain Memory Layer for AI Agents**

Agentic Memory gives AI agents persistent, searchable memory across four domains: **code**, **git history**, **web research**, and **conversations** — all stored in a unified Neo4j graph and exposed via MCP.

**Core Value Prop:** *"Don't let your agent work from a blank slate. Give it memory."*

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **📊 Code Graph** | Structural understanding of files, entities, imports, and on-demand execution tracing — not just text similarity |
| **💬 Conversation Memory** | Stores and retrieves past agent/user exchanges by semantic similarity |
| **🌐 Research & Web Memory** | Ingests URLs, PDFs, and research reports as searchable findings |
| **🧬 Git Graph (Opt-in)** | Adds commit/author/file-version history in the same Neo4j DB |
| **🔍 Unified Search** | `search_all_memory` spans all domains in a single query |
| **⚡ Real-time Sync** | File watcher automatically updates the code graph as you work |
| **🤖 MCP Protocol** | Drop-in integration with Claude, Cursor, Windsurf, and any MCP-compatible AI |
| **⏱️ Temporal GraphRAG** | Time-aware graph layer for deterministic retrieval at any point in time |

---

## 🚀 Quick Start

### 1. Install globally

```bash
# Recommended: Use pipx for isolated global installation
pipx install agentic-memory

# Or with uv tooling
uv tool install agentic-memory
uvx agentic-memory --help

# Or use pip in a virtualenv
pip install agentic-memory
```

### 2. Initialize in any repository

```bash
cd /path/to/your/repo
agentic-memory init
```

The interactive wizard will guide you through:
- Neo4j setup (local Docker, Aura cloud, or custom)
- Code embedding provider selection
- Gemini API key by default for code semantic search
- File extensions to index

By default, `agentic-memory init` configures the `code` module to use
`gemini-embedding-2-preview` so code memory stays aligned with the rest of the
multimodal Agentic Memory system. If you want code memory completely separate,
you can switch the `code` module to another text embedding provider such as
OpenAI.

That's it! Your repository is now indexed and ready for AI agents.

### Running Agentic Memory On This Repository

If you are working inside the `agentic-memory` repo itself, this checkout is
already initialized through:

- `D:\code\agentic-memory\.codememory\config.json`

So you normally do **not** need to run `agentic-memory init` again.

On this machine, the practical local flow is:

```powershell
cd D:\code\agentic-memory
docker compose up -d neo4j
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli status --json
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli index --json
```

Why the commands use `python -m agentic_memory.cli` instead of `agentic-memory`:

- the console script may not be on `PATH`
- the repo-local virtualenv path is explicit and avoids shell ambiguity

Current local config expectations for this repo:

- Neo4j: `bolt://localhost:7687`
- Neo4j user: `neo4j`
- Neo4j password: `password`
- code embedding provider: Gemini (`gemini-embedding-2-preview`)

If `status` fails before indexing starts, the most likely immediate cause is
that Neo4j is not running locally yet.

---

## 📖 Usage

### Code memory

```bash
# Setup/config for code memory in this repo
agentic-memory init

# Show repository status and statistics
agentic-memory status

# One-time structural code ingest (files, entities, imports)
agentic-memory index

# Continuous structural code ingest on file changes
agentic-memory watch

# Experimental old repo-wide CALLS build
agentic-memory build-calls

# JIT trace one function's likely execution neighborhood
agentic-memory trace-execution src/app.py:run_checkout --json

# Start MCP server for AI agents
agentic-memory serve

# Semantic search across code
agentic-memory search "where is the auth logic?"
```

If the console script is not on `PATH`, use the module form instead:

```powershell
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli status --json
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli index --json
```

### Code-memory behavior model

The default code pipeline now stops after structural graph construction:

- Pass 1: structure scan and changed-file detection
- Pass 2: entities, chunks, and embeddings
- Pass 3: import graph construction

What it does **not** do by default:

- repo-wide `CALLS` reconstruction

Behavioral tracing is now handled just in time with:

- CLI: `agentic-memory trace-execution ...`
- MCP: `trace_execution_path(...)`

The older repo-wide analyzer-backed `CALLS` flow is still available explicitly:

- CLI: `agentic-memory build-calls`

Detailed explanation:

- `docs/JIT_TRACING.md`
- `docs/PUBLIC_PLUGIN_SURFACES.md`

### Public plugin surfaces

Agentic Memory now supports a hosted remote-MCP plugin architecture for public AI surfaces. The publication model is:

- OpenAI / ChatGPT: OpenAI app review and publish, backed by the hosted OpenAI MCP surface
- Codex: distribution derived from the approved OpenAI app; `.codex-plugin/plugin.json` is the local preflight package
- Claude: Anthropic directory submission backed by the hosted Claude MCP surface

Default hosted/public MCP mounts:

- `/mcp`
- `/mcp-openai`
- `/mcp-codex`
- `/mcp-claude`

Internal/self-hosted full MCP mount:

- `/mcp-full`

Canonical publication/legal URLs:

- `https://api.agenticmemory.com/publication/agentic-memory`
- `https://api.agenticmemory.com/publication/privacy`
- `https://api.agenticmemory.com/publication/terms`
- `https://api.agenticmemory.com/publication/support`
- `https://api.agenticmemory.com/publication/dpa`

Publication packets:

- `docs/publication/openai`
- `docs/publication/anthropic`
- `docs/publication/shared`

For the public surface contract and auth details, see [docs/PUBLIC_PLUGIN_SURFACES.md](docs/PUBLIC_PLUGIN_SURFACES.md).

### Web & research memory

```bash
# Setup/index repair for research memory
agentic-memory web-init

# Actual ad hoc research ingest from a URL or PDF
agentic-memory web-ingest https://example.com/paper.pdf

# Search research memory
agentic-memory web-search "transformer attention mechanisms"

# Create future ingest triggers
agentic-memory web-schedule --project my-project --query "LLM memory" --interval 24h

# Actual scheduled or ad hoc research ingest execution
agentic-memory web-run-research --project my-project
```

### Conversation memory

```bash
# Setup/index repair for conversation memory
agentic-memory chat-init

# Actual conversation ingest
agentic-memory chat-ingest /path/to/conversation.json

# Search past conversations
agentic-memory chat-search "what did we decide about the auth flow?"
```

### Optional learned reranking

Agentic Memory can optionally apply a shared learned reranking layer across
code, research, and conversation search:

- first-stage retrieval still gathers candidates with the domain's normal
  dense / lexical / temporal logic
- reranking only reorders the candidate pool that survived those filters
- if the hosted reranker is disabled or unavailable, the system falls back to
  baseline ordering and records that fallback in retrieval provenance

The current hosted backend is Cohere Rerank v2. Configure it with:

```bash
AM_RERANK_ENABLED=true
AM_RERANK_PROVIDER=cohere
AM_RERANK_MODEL=rerank-v4.0-fast
COHERE_API_KEY=...
```

Optional per-domain candidate caps and timeout settings live in `.env.example`.

If you want a backup path for retryable provider failures, you can keep direct
Cohere as primary and configure OpenRouter as a narrow failover:

```bash
AM_RERANK_FALLBACK_PROVIDER=openrouter
AM_RERANK_FALLBACK_MODEL=cohere/rerank-4-fast
OPENROUTER_API_KEY=...
```

The fallback is only used for retryable provider-side failures such as
timeouts, HTTP `429`, and `5xx` responses.

### Git graph (opt-in)

```bash
agentic-memory git-init --repo /absolute/path/to/repo --mode local --full-history
agentic-memory git-sync --repo /absolute/path/to/repo --incremental
agentic-memory git-status --repo /absolute/path/to/repo --json
```

Git graph command details and rollout notes: [docs/GIT_GRAPH.md](docs/GIT_GRAPH.md)

---

## 🧾 Tool-Use Annotation (Research)

Agentic Memory supports SQLite telemetry for MCP tool calls plus manual post-response labeling as `prompted` or `unprompted`.

```bash
agentic-memory --prompted "check our auth"
agentic-memory --unprompted "check our auth"
```

Full workflow and options: [docs/TOOL_USE_ANNOTATION.md](docs/TOOL_USE_ANNOTATION.md)

---

## 🏗️ Architecture

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Code Repository │    │  Web / PDFs /    │    │  Conversation    │    │  Git Commits /   │
│  (file watcher)  │    │  Research Reports│    │  Logs            │    │  Blame / History │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                        │                        │
         └───────────────────────┴────────────────────────┴────────────────────────┘
                                              │
                                    Ingestion Pipelines
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │  Neo4j       │
                                       │  Memory Graph│
                                       └──────┬───────┘
                                              │
                                              ▼
┌─────────────────┐     MCP Protocol  ┌──────────────────┐
│   AI Agent /    │ <───────────────> │  MCP Server      │
│   Claude        │                   │  (Interface)     │
└─────────────────┘                   └──────────────────┘
```

### Components

| Component | Role | Description |
|-----------|------|-------------|
| **Code Watcher** (`watcher.py`) | The "Code Writer" | Watches filesystem changes, keeps the code graph in sync |
| **Graph Builder** (`graph.py`) | The "Code Mapper" | Parses code with Tree-sitter, builds Neo4j graph with embeddings |
| **Research Pipeline** (`web/pipeline.py`) | The "Research Writer" | Ingests URLs, PDFs, and findings into the memory graph |
| **Chat Pipeline** (`chat/pipeline.py`) | The "Conversation Writer" | Stores conversation turns with semantic embeddings |
| **MCP Server** (`server/app.py`) | The "Interface" | Exposes all memory domains to AI agents via MCP protocol |

---

## 🔌 MCP Tools Available to AI Agents

### Unified search

| Tool | Description |
|------|-------------|
| `search_all_memory(query)` | Search across all domains — code, research, and conversations — in one call |

### Code domain

| Tool | Description |
|------|-------------|
| `search_codebase(query, limit=5)` | Semantic search over code |
| `get_file_dependencies(file_path)` | Returns imports and dependents for a file |
| `identify_impact(file_path, max_depth=3)` | Blast radius analysis for changes |
| `get_file_info(file_path)` | File structure overview (classes, functions) |
| `trace_execution_path(start_symbol, max_depth=2, force_refresh=false)` | On-demand behavioral tracing for one function root |

### Conversation domain

| Tool | Description |
|------|-------------|
| `search_conversations(query, limit=5)` | Semantic search over past conversation turns |
| `get_conversation_context(session_id)` | Retrieve a full conversation context window |
| `add_message(role, content, session_id)` | Store a new message in conversation memory |

### Research domain

| Tool | Description |
|------|-------------|
| `schedule_research(project_id, query, interval)` | Schedule recurring research sessions |
| `run_research_session(project_id)` | Run a research session immediately |
| `list_research_schedules(project_id)` | List active research schedules |

### Git domain (opt-in)

| Tool | Description |
|------|-------------|
| `get_git_file_history(file_path, limit=20)` | File-level commit history and ownership signals |
| `get_commit_context(sha, include_diff_stats=true)` | Commit metadata and change statistics |
| `find_recent_risky_changes(path_or_symbol, window_days)` | Recent high-risk changes using hybrid signals |

> Note: Git-domain tools are part of the git graph rollout. If missing in your build, run `agentic-memory git-init` first.

---

## 🗂️ Memory Domains

| Domain | What Gets Stored | Graph Nodes |
|--------|-----------------|-------------|
| **Code** | Source files, functions, classes, imports | `File`, `Function`, `Class`, `Chunk` |
| **Conversations** | Agent/user message turns, session context | `ConversationTurn`, `Session` |
| **Research** | Web pages, PDFs, reports, findings, claims | `Report`, `Finding`, `Chunk`, `Source` |
| **Git** | Commits, authors, file versions, diffs | `Commit`, `Author`, `FileVersion` |

---

## ⏱️ Experimental Temporal GraphRAG

Phase 8 adds a shadow-mode temporal maintenance layer alongside the existing Neo4j graph:

- `packages/am-temporal-kg/` — SpacetimeDB TypeScript module for temporal edge ingest, scheduled maintenance, and deterministic temporal retrieval
- `packages/am-sync-neo4j/` — subscription worker that mirrors curated temporal rows back into Neo4j

This layer is additive. Existing retrieval paths remain unchanged until the later retrieval cutover phase.

---

## 🖥️ Full-Stack Local Flow

A unified search surface spans code, research, and conversation memory:

- MCP: `search_all_memory(...)`
- REST: `GET /search/all`

A local product control plane handles install and dogfood loops:

- CLI: `agentic-memory product-status`, `agentic-memory product-repo-add`, `agentic-memory product-integration-set`, `agentic-memory product-component-set`, `agentic-memory product-event-record`
- REST: `GET /product/status`, `POST /product/repos`, `POST /product/integrations`, `POST /product/components/{component}`, `POST /product/events`, `POST /product/onboarding`
- Workflow: [docs/PRODUCT_DOGFOODING.md](docs/PRODUCT_DOGFOODING.md)

A lightweight local FastAPI app in `desktop_shell/` provides a browser-based control plane:

```bash
python -m am_server.server
python -m desktop_shell --backend-url http://127.0.0.1:8765
```

Reference docs:

- [docs/SETUP_FULL_STACK.md](docs/SETUP_FULL_STACK.md)
- [docs/MCP_TOOL_REFERENCE.md](docs/MCP_TOOL_REFERENCE.md)
- [docs/PROVIDER_CONFIGURATION.md](docs/PROVIDER_CONFIGURATION.md)
- [docs/research/RERANKERS_PRIMER.md](docs/research/RERANKERS_PRIMER.md)
- [docs/research/RERANKERS_CROSS_DOMAIN_USE_CASES.md](docs/research/RERANKERS_CROSS_DOMAIN_USE_CASES.md)
- [docs/research/RERANKING_DECISION_MEMO.md](docs/research/RERANKING_DECISION_MEMO.md)
- [docs/SPACETIMEDB_OPERATIONS.md](docs/SPACETIMEDB_OPERATIONS.md)
- [docs/PRODUCT_DOGFOODING.md](docs/PRODUCT_DOGFOODING.md)

---

## ✅ Integration Recommendation Policy

Current recommendation policy is explicit:

1. **Recommended default:** `mcp_native` integration for production reliability.
2. **Optional path:** `skill_adapter` workflow for shell/script-driven operators.
3. **Promotion rule:** `skill_adapter` becomes first-class only after parity evidence
   is captured versus `mcp_native` across success rate, latency, token cost, retries,
   and operator steps.

Reference docs and evaluation artifacts:

- [docs/evaluation-decision.md](docs/evaluation-decision.md)
- [evaluation/README.md](evaluation/README.md)
- [evaluation/tasks/benchmark_tasks.json](evaluation/tasks/benchmark_tasks.json)
- [evaluation/schemas/benchmark_results.schema.json](evaluation/schemas/benchmark_results.schema.json)
- [evaluation/skills/skill-adapter-workflow.md](evaluation/skills/skill-adapter-workflow.md)

---

## 🐳 Docker Setup (Neo4j)

```bash
# Start Neo4j
docker-compose up -d neo4j

# Neo4j will be available at:
# HTTP: http://localhost:7474
# Bolt: bolt://localhost:7687
# Username: neo4j
# Password: password (change this in production!)
```

### Neo4j Aura (Cloud)

Get a free instance at [neo4j.com/cloud/aura/](https://neo4j.com/cloud/aura/)

---

## 📁 Configuration

Per-repository configuration is stored in `.agentic-memory/config.json`:

```json
{
  "neo4j": {
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "password"
  },
  "openai": {
    "api_key": "sk-..."
  },
  "indexing": {
    "ignore_dirs": ["node_modules", "__pycache__", ".git"],
    "extensions": [".py", ".js", ".ts", ".tsx", ".jsx"]
  }
}
```

**Note:** `.agentic-memory/` is gitignored by default to prevent committing API keys.

---

## 🔌 MCP Integration

### Claude Desktop

```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "agentic-memory",
      "args": ["serve", "--repo", "/absolute/path/to/your/project"]
    }
  }
}
```

### Cursor IDE

```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "agentic-memory",
      "args": ["serve", "--repo", "/absolute/path/to/your/project", "--port", "8000"]
    }
  }
}
```

### Windsurf

Add to your MCP configuration file.

> Note: If your installed version does not support `--repo`, use your client's `cwd` setting or launch via a wrapper script: `cd /absolute/path/to/project && agentic-memory serve`.

---

## 🔧 Installation from Source

```bash
git clone https://github.com/jarmen423/agentic-memory.git
cd agentic-memory
pip install -e .
agentic-memory init
```

---

## 🧪 Development

```bash
pip install -e .
mypy src/agentic_memory
pytest
```

---

## 📝 License

MIT License - see LICENSE file for details.

---

## 🤝 Contributing

Contributions welcome! Please see TODO.md for the roadmap.

---

## 🙏 Acknowledgments

- **Neo4j** - Graph database with vector search
- **Tree-sitter** - Incremental parsing for code
- **Google Gemini** - Default embedding provider for multimodal memory alignment
- **MCP (Model Context Protocol)** - Standard interface for AI tools
- **SpacetimeDB** - Temporal graph layer
