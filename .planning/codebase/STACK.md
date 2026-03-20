# Technology Stack

**Analysis Date:** 2026-03-20

## Languages

**Primary:**
- Python 3.10+ - Core language for entire application
- JavaScript/TypeScript - Parsed code analysis support

## Runtime

**Environment:**
- Python 3.10+ (via `requires-python = ">=3.10"` in `D:\code\agentic-memory\pyproject.toml`)

**Package Manager:**
- pip (via PyPI)
- Lockfile: `requirements.txt` present

## Frameworks

**Core:**
- FastMCP (Model Context Protocol) - MCP server framework for AI agent integration
  - Location: `D:\code\agentic-memory\src\codememory\server\app.py`
  - Used for: Exposing graph query tools to AI agents

**Database/Graph:**
- Neo4j (5.25+ Community Edition) - Knowledge graph database
  - Version: 5.25-community (as specified in docker-compose.yml)
  - Client: neo4j 5.14.0+ Python driver
  - Vector search support: Built-in (Neo4j 5.18+)
  - Location: `D:\code\agentic-memory\src\codememory\ingestion\graph.py`

**Code Parsing:**
- tree-sitter - AST parser for code analysis
  - tree-sitter-python - Python code parsing
  - tree-sitter-javascript - JavaScript/TypeScript code parsing
  - Location: `D:\code\agentic-memory\src\codememory\ingestion\parser.py`

**Testing:**
- pytest 7.0.0+ - Test runner
  - Config: `D:\code\agentic-memory\pyproject.toml` (pytest section)
  - pytest-cov - Coverage reporting
  - pytest-asyncio - Async test support
  - pytest-mock - Mocking framework

**Build/Dev:**
- hatchling - Build backend (declared in pyproject.toml)
- black 23.0.0+ - Code formatting
- ruff 0.1.0+ - Fast linting
- mypy 1.0.0+ - Type checking
- pre-commit 3.0.0+ - Git hooks

## Key Dependencies

**Critical:**
- neo4j - Neo4j database driver (Cypher queries, graph operations)
  - Required for: Core knowledge graph operations
  - Version: >=5.14.0

- openai - OpenAI API client
  - Required for: Semantic embeddings (text-embedding-3-large)
  - API endpoint: OpenAI embeddings API
  - Version: >=1.0.0

- mcp - Model Context Protocol library
  - Required for: MCP server framework and tool definitions
  - Exposes: search_codebase, get_file_dependencies, identify_impact, etc.

**Infrastructure:**
- python-dotenv - Environment variable loading
  - Location: `D:\code\agentic-memory\src\codememory\cli.py`
  - Purpose: Load .env files for configuration

- watchdog - File system monitoring
  - Location: `D:\code\agentic-memory\src\codememory\ingestion\watcher.py`
  - Purpose: Continuous file change detection for incremental indexing

- responses - HTTP mocking for tests
  - Version: >=0.23.0

## Configuration

**Environment:**
Configured via multiple methods in priority order:

1. **Environment variables** (highest priority):
   - `NEO4J_URI` - Neo4j connection URI (e.g., "bolt://localhost:7687")
   - `NEO4J_USER` / `NEO4J_USERNAME` - Neo4j authentication
   - `NEO4J_PASSWORD` - Neo4j password
   - `OPENAI_API_KEY` - OpenAI API key for embeddings
   - `CODEMEMORY_ENV_FILE` - Path to .env file
   - `CODEMEMORY_CLIENT` - Client identifier for telemetry
   - `CODEMEMORY_TELEMETRY_ENABLED` - Enable/disable telemetry (default: 1)
   - `CODEMEMORY_TELEMETRY_DB` - SQLite telemetry database path

2. **Repository config** (.codememory/config.json):
   - Location: `<repo_root>/.codememory/config.json`
   - Loaded by: `D:\code\agentic-memory\src\codememory\config.py`
   - Contains: Neo4j URI/credentials, OpenAI API key, indexing rules, git config

3. **Default config**:
   - Fallback values in `DEFAULT_CONFIG` in config.py
   - Neo4j: `bolt://localhost:7687`
   - OpenAI: Requires env var or config file

**Build:**
- Build config: `pyproject.toml`
- Wheel package: Built from `src/codememory/`

## Platform Requirements

**Development:**
- Python 3.10+
- Neo4j instance (Docker or Aura cloud)
- OpenAI API key (optional, but required for semantic search)

**Production:**
- Python 3.10+
- Neo4j 5.18+ (with vector search capability)
  - Docker container: `neo4j:5.25-community` (recommended)
  - Or: Neo4j Aura cloud instance
- OpenAI API account (for embedding tokens)

**Docker:**
- Orchestration: `docker-compose.yml` (in project root)
- Neo4j service with:
  - HTTP port: 7474
  - Bolt port: 7687
  - Memory: 2GB heap, 1GB pagecache
  - APOC procedures enabled for vector operations

---

*Stack analysis: 2026-03-20*
