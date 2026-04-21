# 🧠 Agentic Memory

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
pipx install agent-memory-labs

# Or with uv tooling
uv tool install agent-memory-labs
uvx --from agent-memory-labs agent-memory --help

# Or use pip in a virtualenv
pip install agent-memory-labs
```

After a `pipx` install:
- `agent-memory` is available globally on that machine
- you install the CLI once, not once per repository
- each repository keeps its own local Agentic Memory config under `.agentic-memory/`

### 2. Initialize in any repository

```bash
cd /path/to/your/repo
agent-memory init
```

The interactive wizard will guide you through:
- Neo4j setup (local Docker, Aura cloud, or custom)
- Code embedding provider selection
- Gemini API key by default for code semantic search
- File extensions to index

By default, `agent-memory init` configures the `code` module to use
`gemini-embedding-2-preview` so code memory stays aligned with the rest of the
multimodal Agentic Memory system. If you want code memory completely separate,
you can switch the `code` module to another text embedding provider such as
OpenAI.

### Multi-Repo Workflow

If a machine hosts more than one repository, the normal flow is still:

```bash
cd /path/to/repo-a
agent-memory init

cd /path/to/repo-b
agent-memory init
```

After that, Agentic Memory discovers the active repository from your current
working directory.

---

## 📖 Usage

### Code memory

```bash
# Setup/config for code memory in this repo
agent-memory init

# Show repository status and statistics
agent-memory status

# One-time structural code ingest (files, entities, imports)
agent-memory index

# Full repo rebuild after embedding-model or task-format changes
agent-memory index --full

# Continuous structural code ingest on file changes
agent-memory watch

# JIT trace one function's likely execution neighborhood
agent-memory trace-execution src/app.py:run_checkout --json

# Start MCP server for AI agents
agent-memory serve

# Semantic search across code
agent-memory search "where is the auth logic?"
```

### Research memory

```bash
# Ingest a URL as a research finding
agent-memory research "https://example.com/article"

# Search across ingested research
agent-memory search "What did I read about vector databases?" --domain web
```

### Conversation memory

```bash
# Search past conversations
agent-memory search "What did we decide about the auth flow?" --domain chat
```

---

## 🏗️ Architecture

Agentic Memory is built on a few key ideas:

1. **Structural code graphs** — We parse ASTs and imports to understand code structure, not just file contents.
2. **Unified Neo4j backend** — All memory domains live in one graph database for cross-domain queries.
3. **MCP-native** — The primary interface is the Model Context Protocol, making it compatible with any MCP client.
4. **Temporal awareness** — Git history and time-sliced queries let you ask "what did the code look like last month?"

---

## 📦 Packages

| Package | Description | Location |
|---------|-------------|----------|
| `agent-memory-labs` | Core Python package (PyPI) | This repo |
| `agentic-memory-openclaw` | OpenClaw plugin (npm) | `packages/am-openclaw/` |
| `am-temporal-kg` | Temporal GraphRAG utilities | `packages/am-temporal-kg/` |
| `am-sync-neo4j` | Neo4j sync helpers | `packages/am-sync-neo4j/` |

---

## 🛠 Self-Hosting

Agentic Memory is designed to be fully self-hostable:

- **Neo4j** (Community Edition works fine)
- **Python 3.10+**
- **Embedding provider API key** (Gemini, OpenAI, or Groq)

For detailed self-hosting instructions, see [docs/SETUP_FULL_STACK.md](docs/SETUP_FULL_STACK.md).

---

## 🤝 Contributing

We welcome contributions to the core indexing, search, and MCP surfaces.

1. Fork the repo
2. Create a feature branch
3. Run tests: `pytest`
4. Submit a PR

Please keep PRs focused on the self-hostable core. Hosted backend changes are maintained separately.

---

## 📄 License

This project is licensed under the Business Source License 1.1 (BSL 1.1).

- **Source available** for non-production use, research, and evaluation
- **Time-delayed open source** — converts to a standard open-source license after 4 years
- **Commercial use** requires a license — contact us for hosted options

See [LICENSE](LICENSE) for full terms.

---

## 🔗 Links

- **Docs**: [docs/INSTALLATION.md](docs/INSTALLATION.md)
- **Troubleshooting**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- **API Reference**: [docs/API.md](docs/API.md)
- **Website**: https://agentmemorylabs.com
