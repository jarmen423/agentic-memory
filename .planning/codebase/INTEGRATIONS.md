# External Integrations

**Analysis Date:** 2026-03-20

## APIs & External Services

**AI/ML Services:**
- OpenAI (Embeddings API) - Semantic code search and embeddings
  - SDK/Client: `openai` Python package (>=1.0.0)
  - Auth: `OPENAI_API_KEY` environment variable
  - Model: text-embedding-3-large (3072 dimensions)
  - Cost tracking: Implemented in `D:\code\agentic-memory\src\codememory\ingestion\graph.py`
    - Pricing: $0.13 USD per 1M tokens (as of Dec 2024)
    - Usage tracked in KnowledgeGraphBuilder.token_usage dict

## Data Storage

**Databases:**
- Neo4j Graph Database (Primary)
  - Type: Property graph database
  - Version: 5.18+ required (for vector search)
  - Connection: Bolt protocol (default: bolt://localhost:7687)
  - Driver: neo4j Python package (>=5.14.0)
  - Config env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
  - Config file: `.codememory/config.json` (neo4j section)
  - Connection pooling: 50 connections max
  - Circuit breaker: Implemented in graph.py (5-failure threshold)

- SQLite (Telemetry)
  - Location: `.codememory/telemetry.sqlite3`
  - Override: `CODEMEMORY_TELEMETRY_DB` env var
  - Tables:
    - `tool_calls` - MCP tool execution records
    - `manual_annotations` - User annotation workflow data
  - Schema: `D:\code\agentic-memory\src\codememory\telemetry.py` (lines 62-100)
  - Enable/disable: `CODEMEMORY_TELEMETRY_ENABLED` (default: enabled)

**File Storage:**
- Local filesystem only
  - Code indexing: Repository root and nested directories
  - Configuration: `.codememory/` directory (config.json, .graphignore)
  - Ignore patterns: `.graphignore` file (glob-based)

**Caching:**
- Neo4j driver-level connection pooling (50 concurrent connections)
- No external caching service (Redis/Memcached) required

## Authentication & Identity

**Auth Provider:**
- None - No user/identity management
- Configuration-based access control via environment variables
- Neo4j credentials required for database access

**API Key Management:**
- OpenAI API key:
  - Source 1: `.codememory/config.json` (persistent, not recommended in git)
  - Source 2: `OPENAI_API_KEY` environment variable (recommended)
  - Fallback: Interactive prompt during `codememory init`

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking (Sentry, DataDog, etc.)
- Logging to stdout/stderr via Python logging
- Circuit breaker pattern for Neo4j connection failures

**Logs:**
- Approach: Python logging framework (stdlib)
  - Logger: `codememory` package namespace
  - Configured in: Various modules (cli.py, graph.py, app.py, watcher.py)
  - Output: Console (can be redirected to files via shell)

**Telemetry:**
- SQLite-based tool-call tracking (local)
  - Location: `D:\code\agentic-memory\src\codememory\telemetry.py`
  - Records: Tool name, duration, success/failure, client ID, repo root
  - Annotation workflow: Manual user-driven labeling of prompted vs. unprompted tool usage
  - Commands: `codememory --prompted` and `codememory --unprompted`

## CI/CD & Deployment

**Hosting:**
- No built-in hosting - Self-hosted only
- MCP server runs locally via `codememory serve`
- Can be containerized via Dockerfile (referenced in docker-compose.yml)
- Supports environment-based configuration for different deployments

**CI Pipeline:**
- None detected - No GitHub Actions/GitLab CI config in repository
- Pre-commit hooks configured:
  - Black (code formatting)
  - Ruff (linting with auto-fix)
  - MyPy (type checking)
  - Config: `.pre-commit-config.yaml`

## Environment Configuration

**Required env vars:**
- `NEO4J_URI` - Neo4j connection URI
- `NEO4J_USER` / `NEO4J_USERNAME` - Neo4j username
- `NEO4J_PASSWORD` - Neo4j password
- `OPENAI_API_KEY` - OpenAI API key (optional if using config file)

**Optional env vars:**
- `CODEMEMORY_ENV_FILE` - Path to .env file to load
- `CODEMEMORY_REPO` - Override repository root detection
- `CODEMEMORY_CLIENT` - Client identifier for telemetry tracking
- `CODEMEMORY_TELEMETRY_ENABLED` - Disable telemetry (default: 1/enabled)
- `CODEMEMORY_TELEMETRY_DB` - Override telemetry SQLite path

**Secrets location:**
- Environment variables (preferred)
- `.codememory/config.json` (for per-repo config, should not be committed)
- `.env` file (project-local, should not be committed)
- Patterns in `.graphignore`: Ignores `.env`, `.env.*`, `*.env` from indexing

## Webhooks & Callbacks

**Incoming:**
- None - This is a pull-based system (watches files, not receiving webhooks)

**Outgoing:**
- None - No external service callbacks

**Git Integration:**
- Git repository read-only access (optional)
  - Commands: git log, git show, git rev-parse
  - Purpose: Extract commit history and metadata
  - Enabled via: `codememory git-init`, `codememory git-sync`
  - Config: `.codememory/config.json` (git section)
  - GitHub enrichment: Optional metadata enrichment (disabled by default)

## External Tools Integration

**File Watching:**
- watchdog library - Cross-platform file system events
  - Used in: `D:\code\agentic-memory\src\codememory\ingestion\watcher.py`
  - Purpose: Detect file changes for incremental indexing

**Code Parsing:**
- tree-sitter bindings (Python):
  - tree-sitter-python - Parse .py files
  - tree-sitter-javascript - Parse .js, .jsx, .ts, .tsx files
  - Used in: `D:\code\agentic-memory\src\codememory\ingestion\graph.py` (Pass 2)

**MCP Protocol:**
- Model Context Protocol (FastMCP implementation)
  - Location: `D:\code\agentic-memory\src\codememory\server\app.py`
  - Exposes 6 tools:
    1. `search_codebase` - Semantic and git search with domain routing
    2. `get_file_dependencies` - Direct import relationships
    3. `identify_impact` - Transitive dependency analysis
    4. `get_file_info` - File structure and entities
    5. `get_git_file_history` - Commit history (requires git ingestion)
    6. `get_commit_context` - Detailed commit metadata (requires git ingestion)

---

*Integration audit: 2026-03-20*
