# Agentic Memory (CodeMemory)

**Version:** 0.1.0-alpha  
**Description:** Structural Memory Layer for AI Agents - A hybrid GraphRAG system that creates a "Digital Twin" of codebases in Neo4j to power AI coding agents.

---

## Project Overview

Agentic Memory is not just "RAG" for code. It is an **active, structural memory system** for Autonomous Agents. Unlike standard vector databases that only know "similarity," CodeMemory understands **structure** (dependencies, imports, inheritance).

**Core Value Proposition:** "Don't let your Agent code blind. Give it a map."

The system moves beyond simple vector search by establishing a property graph that models syntax, dependencies (Imports/Calls), and semantic meaning (Embeddings).

---

## Architecture

The system is decoupled into three independent components:

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
│   AI Agent /    │ <───────────────> │  MCP Skill       │
│   Claude        │                   │  (Interface)     │
└─────────────────┘                   └──────────────────┘
```

### Component A: The Observer (Ingestion Service)

- **Role:** The "Writer." It watches the file system and keeps the graph in sync.
- **Key Command:** `codemem watch ./my-repo`
- **Implementation:** `src/codememory/ingestion/watcher.py`

### Component B: The Brain (Neo4j Database)

- **Role:** Stores the structural and semantic representation of code.
- **Features:** Vector indexes, graph relationships (CALLS, IMPORTS), constraints.

### Component C: The Interface (MCP Server)

- **Role:** The "Reader" and "Translator."
- **Why MCP?** It allows us to expose high-level *skills* to the agent, rather than raw SQL access.
- **Key Tools:**
  1. `search_codebase(query: str)`: Hybrid search (Vector + Keyword).
  2. `get_file_dependencies(path: str)`: Returns what this file imports and what calls it.
- **Implementation:** `src/codememory/server/`

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| Database | Neo4j 5.18+ (Graph + Vector) |
| Parsing | Tree-sitter (0.21+) |
| Embeddings | OpenAI (`text-embedding-3-small`) |
| Agent Protocol | MCP (Model Context Protocol) |
| State Management | PostgreSQL (for file hash tracking) |
| Framework | LlamaIndex |

### Key Dependencies

- `neo4j>=5.14.0` - Graph database driver
- `openai>=1.12.0` - Embeddings API
- `tree-sitter>=0.21.0` - Static analysis/parsing
- `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript` - Language bindings
- `mcp[fastapi]>=0.1.0` - MCP SDK
- `watchdog` - File system watching
- `llama-index-*` - Ingestion pipeline framework

---

## Project Structure

```
agentic-memory/
├── src/codememory/                 # Main Python package
│   ├── __init__.py
│   ├── cli.py                      # Entry point (argparse)
│   ├── pyproject.toml              # Package-specific config (legacy)
│   ├── ingestion/                  # Refactored ingestion logic
│   │   ├── __init__.py
│   │   ├── watcher.py              # File system watcher
│   │   ├── parser.py               # Tree-sitter parsing logic (stub)
│   │   └── graph.py                # Neo4j writer & query builder
│   ├── server/                     # MCP Server
│   │   ├── __init__.py
│   │   ├── app.py                  # FastMCP server setup
│   │   └── tools.py                # Agent tools implementation
│   └── docker/
│       └── docker-compose.yml      # Full stack deployment
│
├── 4_pass_ingestion_with_prep_hybridgraphRAG.py  # Legacy: Day 0 indexer
├── 5_continuous_ingestion.py                     # Legacy: Continuous daemon
├── 5_continuous_ingestion_jina.py               # Legacy: Jina embeddings variant
├── debug_extraction.py                          # Debug script for parsing
├── upload_checkpoint.py                         # Manual embedding uploader
│
├── pyproject.toml                 # Main project configuration (Hatchling)
├── graphrag_requirements.txt      # Legacy requirements (Python 3.11)
├── SPEC.md                        # Architecture specification
├── GRAPHRAG_README.md             # Legacy setup documentation
├── 4-stage-ingestion-with-prep.md # Design rationale document
├── .env                           # Environment variables (gitignored)
└── .gitignore                     # Git exclusions
```

---

## Build and Installation

### Local Development Setup

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Install in editable mode
pip install -e .

# 3. Configure environment
cp .env.example .env  # Edit with your credentials
```

### Docker Deployment

```bash
# Start full stack (Neo4j + Ingestor + MCP Server)
docker-compose -f src/codememory/docker/docker-compose.yml up

# Requires OPENAI_API_KEY environment variable set
```

---

## Commands

### CLI Commands

The package provides the `codemem` (or `codememory`) CLI command:

```bash
# Watch a repository for changes
codemem watch ./my-repo \
  --neo4j-uri bolt://localhost:7687 \
  --neo4j-user neo4j \
  --neo4j-password password

# Start the MCP server
codemem serve --port 8000

# Show help
codemem --help
```

### Tool-Use Annotation (Personal Research)

You can manually label MCP tool-use bursts as `prompted` or `unprompted`:

```bash
codememory --prompted "check our auth"
codememory --unprompted "check our auth"
```

See full behavior and options: `docs/TOOL_USE_ANNOTATION.md`.

### Environment Variables

Create a `.env` file in the project root:

```ini
# Required
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
OPENAI_API_KEY=sk-...

# Optional (for legacy scripts)
POSTGRES_URI=postgresql+psycopg2://user:pass@localhost:5432/dbname
REPO_PATH=/absolute/path/to/repo
```

---

## Code Organization

### Ingestion Module (`src/codememory/ingestion/`)

**`watcher.py`**
- `CodeChangeHandler` - Watchdog event handler for file changes
- `start_continuous_watch()` - Main loop for file system observation
- Supports `.py`, `.js`, `.ts` file extensions

**`graph.py`**
- `KnowledgeGraphBuilder` - Core class for graph operations
  - `EMBEDDING_MODEL = "text-embedding-3-small"`
  - `setup_indexes()` - Creates constraints and vector indexes
  - `process_file()` - Ingests a single file
  - `semantic_search()` - Hybrid vector + graph search
  - `get_embedding()` - OpenAI embedding generation

### Server Module (`src/codememory/server/`)

**`app.py`**
- FastMCP server initialization
- Tool decorators for agent interface
- `run_server()` - SSE/HTTP server entry point

**`tools.py`**
- `Toolkit` - Business logic separated from server
  - `semantic_search()` - Formats results for LLM consumption
  - `get_file_dependencies()` - Import/caller analysis

---

## Database Schema

### Node Types

| Label | Properties |
|-------|------------|
| `File` | `path` (unique), `last_updated` (datetime) |
| `Function` | `signature` (unique), `name`, `docstring`, `args`, `return_type` |
| `Class` | `name`, `methods` |
| `Chunk` | `text`, `embedding` (vector 1536d) |

### Relationships

| Type | Pattern | Description |
|------|---------|-------------|
| `IMPORTS` | `(File)-[:IMPORTS]->(File)` | File dependency |
| `CALLS` | `(Function)-[:CALLS]->(Function)` | Function call graph |
| `DEFINES` | `(File)-[:DEFINES]->(Function\|Class)` | Containment |
| `DESCRIBES` | `(Chunk)-[:DESCRIBES]->(Function)` | Vector to code mapping |
| `HAS_METHOD` | `(Class)-[:HAS_METHOD]->(Function)` | Class membership |

### Indexes

```cypher
// Constraints
CREATE CONSTRAINT file_path_unique FOR (f:File) REQUIRE f.path IS UNIQUE
CREATE CONSTRAINT func_sig_unique FOR (f:Function) REQUIRE f.signature IS UNIQUE

// Vector Index
CREATE VECTOR INDEX code_embeddings FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}}
```

---

## Legacy Scripts (Python 3.11 Required)

The root-level Python scripts are **legacy implementations** that require Python 3.11 due to `llama-index` and `tree-sitter` compatibility:

| Script | Purpose |
|--------|---------|
| `4_pass_ingestion_with_prep_hybridgraphRAG.py` | Day 0 full ingestion (4-pass algorithm) |
| `5_continuous_ingestion.py` | Continuous daemon with PostgreSQL state |
| `5_continuous_ingestion_jina.py` | Variant using Jina AI embeddings (~750d) |
| `debug_extraction.py` | Test Tree-sitter queries without full pipeline |
| `upload_checkpoint.py` | Manual upload of pickled embeddings |

**⚠️ Important:** These scripts use a separate virtual environment:

```bash
# Setup legacy environment
pyenv install 3.11.9
~/.pyenv/versions/3.11.9/bin/python -m venv .venv-graphrag
source .venv-graphrag/bin/activate
pip install -r graphrag_requirements.txt
```

---

## Development Guidelines

### Python Version Compatibility

- **Main package:** Python 3.10+
- **Legacy scripts:** Python 3.11 only (due to llama-index/tree-sitter bindings)

### Configuration Management

- Use `python-dotenv` for environment variables
- CLI arguments override environment variables
- No hardcoded paths in production code

### Error Handling

- Use `logging` module with appropriate levels
- Wrap embedding calls with try/except (fallback to zero vectors)
- Validate file paths before processing

### Code Style

- Type hints encouraged (`from typing import List, Dict, Optional`)
- Docstrings for public methods
- f-strings for formatting

---

## Testing Strategy

Currently, the project uses:

1. **Debug scripts** (`debug_extraction.py`) for rapid testing of parsing logic
2. **Manual integration testing** via CLI commands
3. **Checkpoints** (`.embedding_checkpoint.pkl`) for recovery

No automated unit test suite is currently configured.

---

## Security Considerations

1. **API Keys:** Store in `.env` file (already gitignored)
2. **Neo4j Credentials:** Use environment variables, never commit passwords
3. **File Access:** Watcher only reads files, never writes to source
4. **Docker:** Default password `neoj/password` should be changed in production

---

## Deployment Options

### Option 1: Local Development

```bash
pip install -e .
codemem watch /path/to/repo
codemem serve  # In another terminal
```

### Option 2: Docker Compose

```bash
cd src/codememory/docker
docker-compose up -d
```

Services exposed:
- Neo4j Browser: http://localhost:7474
- Neo4j Bolt: `bolt://localhost:7687`
- MCP Server: http://localhost:8000

---

## Known Limitations

1. **MVP Status:** The `parser.py` is currently a stub - full Tree-sitter logic needs porting from legacy scripts
2. **Language Support:** Currently Python, JavaScript, TypeScript only
3. **No Tests:** Automated test suite not yet implemented
4. **Single Repository:** Designed for one repo per Neo4j instance

---

## References

- `SPEC.md` - Full architecture specification
- `GRAPHRAG_README.md` - Legacy setup guide for Python 3.11
- `4-stage-ingestion-with-prep.md` - Design rationale for hybrid chunking
