# 🧠 Agentic Memory
https://github.com/jarmen423/agentic-memory

> **Active, Structural Memory System for AI Coding Agents**

Agentic Memory is not just "RAG" for code. It is an **active, structural memory layer** that understands code relationships (dependencies, imports, inheritance), not just text similarity.

**Core Value Prop:** *"Don't let your Agent code blind. Give it a map."*

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **📊 Structural Graph** | Understands imports, dependencies, call graphs - not just text similarity |
| **🔍 Semantic Search** | Vector embeddings with contextual prefixing for accurate results |
| **⚡ Real-time Sync** | File watcher automatically updates the graph as you code |
| **🧬 Git Graph (Opt-in)** | Adds commit/author/file-version history in the same Neo4j DB with separate labels |
| **🤖 MCP Protocol** | Drop-in integration with Claude, Cursor, Windsurf, and any MCP-compatible AI |
| **💥 Impact Analysis** | See the blast radius of changes before you make them |

---

## 🚀 Quick Start (One Command Setup)

### 1. Install globally

```bash
# Recommended: Use pipx for isolated global installation
pipx install codememory

# Or with uv tooling
uv tool install codememory
uvx codememory --help

# Or use pip in a virtualenv
pip install codememory
```

### 2. Initialize in any repository

```bash
cd /path/to/your/repo
codememory init
```

The interactive wizard will guide you through:
- Neo4j setup (local Docker, Aura cloud, or custom)
- OpenAI API key (for semantic search)
- File extensions to index

That's it! Your repository is now indexed and ready for AI agents.

---

## 📖 Usage

### In any initialized repository:

```bash
# Show repository status and statistics
codememory status

# One-time full index (e.g., after major changes)
codememory index

# Watch for changes and continuously update
codememory watch

# Start MCP server for AI agents
codememory serve

# Test semantic search
codememory search "where is the auth logic?"

# Git graph (rollout build)
codememory git-init --repo /absolute/path/to/repo --mode local --full-history
codememory git-sync --repo /absolute/path/to/repo --incremental
codememory git-status --repo /absolute/path/to/repo --json
```

Git graph command details and rollout notes: [docs/GIT_GRAPH.md](docs/GIT_GRAPH.md)

---

## 🧾 Tool-Use Annotation (Research)

Agentic Memory now supports SQLite telemetry for MCP tool calls plus manual post-response labeling as `prompted` or `unprompted`.

```bash
codememory --prompted "check our auth"
codememory --unprompted "check our auth"
```

Full workflow and options: [docs/TOOL_USE_ANNOTATION.md](docs/TOOL_USE_ANNOTATION.md)

---

## 🏗️ Architecture

```
┌─────────────────┐     Watches      ┌──────────────────┐
│  User Repository│ ───────────────> │ Ingestion Service│
│                 │                  │ (Observer)       │
└─────────────────┘                  └────────┬─────────┘
                                              │ Writes
                                              ▼
                                       ┌──────────────┐
                                       │  Neo4j       │
                                       │  Cortex      │
                                       └──────┬───────┘
                                              │ Reads
                                              ▼
┌─────────────────┐     MCP Protocol  ┌──────────────────┐
│   AI Agent /    │ <───────────────> │  MCP Server      │
│   Claude        │                   │  (Interface)     │
└─────────────────┘                   └──────────────────┘
```

### Components

| Component | Role | Description |
|-----------|------|-------------|
| **Observer** (`watcher.py`) | The "Writer" | Watches filesystem changes and keeps the graph in sync |
| **Graph Builder** (`graph.py`) | The "Mapper" | Parses code with Tree-sitter, builds Neo4j graph with embeddings |
| **MCP Server** (`app.py`) | The "Interface" | Exposes high-level skills to AI agents via MCP protocol |

---

## 🔌 MCP Tools Available to AI Agents

| Tool | Description |
|------|-------------|
| `search_codebase(query, limit=5, domain="code")` | Semantic search for code, git, or hybrid domain routing |
| `get_file_dependencies(file_path, domain="code")` | Returns imports and dependents for a file |
| `identify_impact(file_path, max_depth=3, domain="code")` | Blast radius analysis for changes |
| `get_file_info(file_path, domain="code")` | File structure overview (classes, functions) |
| `get_git_file_history(file_path, limit=20, domain="git")` | File-level commit history and ownership signals (git rollout) |
| `get_commit_context(sha, include_diff_stats=true)` | Commit metadata and change statistics (git rollout) |
| `find_recent_risky_changes(path_or_symbol, window_days, domain="hybrid")` | Recent high-risk changes using hybrid signals (git rollout) |

> Note: `domain` routing and git-domain tools are part of the git graph rollout. If they are missing in your installed build, use code-domain tools only and upgrade to a git-enabled release.

---

## ✅ Integration Recommendation Policy (PR7)

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

### Quick Start

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

Per-repository configuration is stored in `.codememory/config.json`:

```json
{
  "neo4j": {
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "password"
  },
  "openai": {
    "api_key": "sk-..."  // Optional - can use OPENAI_API_KEY env var
  },
  "indexing": {
    "ignore_dirs": ["node_modules", "__pycache__", ".git"],
    "extensions": [".py", ".js", ".ts", ".tsx", ".jsx"]
  }
}
```

**Note:** `.codememory/` is gitignored by default to prevent committing API keys.

---

## 🔧 Installation from Source

```bash
# Clone the repository
git clone https://github.com/jarmen423/agentic-memory.git
cd agentic-memory

# Install in editable mode
pip install -e .

# Run the init wizard in any repo
codememory init
```

---

## 🧪 Development

```bash
# Install in editable mode
pip install -e .

# Run type checking (when mypy is configured)
mypy src/codememory

# Run tests (when added)
pytest
```

---

## 📊 What Gets Indexed?

| Entity | Description | Relationships |
|--------|-------------|---------------|
| **Files** | Source code files | `[:DEFINES]`→ Functions/Classes, `[:IMPORTS]`→ Files |
| **Functions** | Function definitions | `[:CALLS]`→ Functions, `[:HAS_METHOD]`← Classes |
| **Classes** | Class definitions | `[:HAS_METHOD]`→ Methods |
| **Chunks** | Semantic embeddings | `[:DESCRIBES]`→ Functions/Classes |

---

## 🔌 MCP Integration

### Claude Desktop

```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
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
      "command": "codememory",
      "args": ["serve", "--repo", "/absolute/path/to/your/project", "--port", "8000"]
    }
  }
}
```

### Windsurf

Add to your MCP configuration file.

> Note: `--repo` requires the upcoming release that adds explicit repo targeting for `serve`.
> If your installed version does not support `--repo`, use your client's `cwd` setting
> (if supported) or launch via a wrapper script that runs `cd /absolute/path/to/project && codememory serve`.

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
- **OpenAI** - Embeddings for semantic search
- **MCP (Model Context Protocol)** - Standard interface for AI tools
