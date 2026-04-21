<p align="center">
  <img src="https://raw.githubusercontent.com/jarmen423/agentic-memory/main/assets/logo.svg" alt="Agentic Memory" width="120">
</p>

<h1 align="center">Agentic Memory</h1>

<p align="center">
  <b>Memory that understands time.</b>
</p>

<p align="center">
  The first agent memory system built on a time-aware knowledge graph.<br>
  Query what was true last week. Track how claims evolve. Retrieve with confidence — all via MCP.
</p>

<p align="center">
  <a href="https://pypi.org/project/agent-memory-labs/"><img src="https://img.shields.io/pypi/v/agent-memory-labs?style=flat-square&color=00F0FF&labelColor=0A0A0F" alt="PyPI"></a>
  <a href="https://pypi.org/project/agent-memory-labs/"><img src="https://img.shields.io/pypi/pyversions/agent-memory-labs?style=flat-square&color=FF006E&labelColor=0A0A0F" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSL--1.1-F59E0B?style=flat-square&labelColor=0A0A0F" alt="License"></a>
  <a href="https://agentmemorylabs.com"><img src="https://img.shields.io/badge/website-agentmemorylabs.com-00F0FF?style=flat-square&labelColor=0A0A0F" alt="Website"></a>
</p>

---

## What is Agentic Memory?

Most AI agents start every session with a blank slate. **Agentic Memory** fixes that.

It gives your agents **persistent, searchable memory** across four domains — code, conversations, research, and git history — stored in a unified Neo4j graph and exposed through the Model Context Protocol (MCP). Agents can recall what they learned yesterday, last week, or last month.

The killer feature? **Temporal GraphRAG**. Every relationship in the graph carries a validity interval. Ask "what did we decide about the auth flow in March?" and get a temporally consistent answer — not today's guess.

---

## Features

### Temporal GraphRAG
Time-aware graph layer powered by SpacetimeDB. Query what was true at any point in time with deterministic temporal retrieval. Track claim evolution, detect contradictions, and retrieve with confidence intervals.

### Code Memory
Structural understanding of files, entities, imports, and on-demand execution tracing — not just text similarity. Your agent knows *where* things are and *how* they connect.

### Research Memory
Ingest URLs, PDFs, and research reports as searchable findings. Schedule recurring research sessions. Build a living knowledge base that grows over time.

### Conversation Memory
Stores and retrieves past agent/user exchanges by semantic similarity. Never lose context between sessions. Search across months of conversations in milliseconds.

### Git Graph (Opt-in)
Adds commit/author/file-version history to the same Neo4j graph. Ask temporal questions about your codebase: "who wrote this function and when?"

### Unified Search
`search_all_memory` spans all domains in a single query — code, research, conversations, and git history — with cross-domain relevance ranking.

### Real-time Sync
File watcher automatically updates the code graph as you work. No manual re-indexing required.

### MCP Native
Drop-in integration with Claude, Cursor, ChatGPT, Windsurf, Codex, and any MCP-compatible AI. One protocol, every client.

---

## Quick Start

```bash
# Install globally (recommended)
pipx install agent-memory-labs

# Or with uv
uv tool install agent-memory-labs

# Initialize in any repository
cd /path/to/your/repo
agent-memory init

# Index your code
agent-memory index

# Start the MCP server
agent-memory serve
```

That's it. Your repository is now indexed and ready for AI agents.

---

## Usage

### Code Memory

```bash
agent-memory init                 # Setup wizard
agent-memory status               # Repository statistics
agent-memory index                # One-time structural ingest
agent-memory index --full         # Full rebuild
agent-memory watch                # Continuous sync on file changes
agent-memory trace-execution src/app.py:run_checkout --json
```

### Research Memory

```bash
agent-memory research "https://example.com/article"
agent-memory search "What did I read about vector databases?" --domain web
```

### Conversation Memory

```bash
agent-memory search "What did we decide about the auth flow?" --domain chat
```

---

## Architecture

```
AI Agent (Claude/Cursor/etc.)
        |
    MCP Protocol
        |
+-------+-------+
|  Agentic Memory  |
+------------------+
|  Unified Graph   |  <-- Neo4j (code + chat + research + git)
|  Temporal Layer  |  <-- SpacetimeDB (validity intervals, PPR)
|  Embeddings      |  <-- Gemini / OpenAI / Nemotron
+------------------+
```

1. **Structural code graphs** — AST parsing and import analysis, not just file contents
2. **Unified Neo4j backend** — All memory domains live in one graph database
3. **MCP-native** — Primary interface is the Model Context Protocol
4. **Temporal awareness** — Git history and time-sliced queries built into the graph

---

## Self-Hosting

Agentic Memory is designed to be fully self-hostable:

- **Neo4j** Community Edition
- **Python 3.10+**
- **Embedding provider API key** (Gemini, OpenAI, or Groq)

See [docs/SETUP_FULL_STACK.md](docs/SETUP_FULL_STACK.md) for detailed instructions.

---

## Integrations

Works out of the box with:

**Claude** · **Cursor** · **ChatGPT** · **Windsurf** · **Codex**

Any MCP-compatible client can connect to `agent-memory serve` and immediately search across all indexed memory domains.

---

## Packages

| Package | Description | Install |
|---------|-------------|---------|
| `agent-memory-labs` | Core Python package | `pipx install agent-memory-labs` |
| `agentic-memory-openclaw` | OpenClaw plugin | `openclaw plugin install agentic-memory-openclaw` |
| `am-temporal-kg` | Temporal GraphRAG utilities | npm / pnpm |
| `am-sync-neo4j` | Neo4j sync helpers | npm / pnpm |

---

## Contributing

We welcome contributions to the core indexing, search, and MCP surfaces.

1. Fork the repo
2. Create a feature branch
3. Run tests: `pytest`
4. Submit a PR

Please keep PRs focused on the self-hostable core.

---

## License

This project is licensed under the **Business Source License 1.1 (BSL 1.1)**.

- Source available for non-production use, research, and evaluation
- Converts to a standard open-source license after 4 years
- Commercial use requires a license — [contact us](https://agentmemorylabs.com)

See [LICENSE](LICENSE) for full terms.

---

<p align="center">
  <a href="https://agentmemorylabs.com">Website</a> ·
  <a href="docs/INSTALLATION.md">Docs</a> ·
  <a href="docs/TROUBLESHOOTING.md">Troubleshooting</a> ·
  <a href="docs/API.md">API Reference</a>
</p>
