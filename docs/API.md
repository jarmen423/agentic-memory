# API Reference

Complete reference for Agentic Memory's CLI commands, MCP tools, configuration options, and Python API.

## Table of Contents

- [CLI Commands](#cli-commands)
- [OpenClaw REST Surface](#openclaw-rest-surface)
- [MCP Tools](#mcp-tools)
- [Configuration Options](#configuration-options)
- [Python API](#python-api)
- [Error Codes](#error-codes)

---

## OpenClaw REST Surface

The OpenClaw private-beta REST contract is now committed separately from the
general CLI/MCP reference.

Primary artifact:

- `D:\code\agentic-memory\docs\openclaw\openapi\agentic-memory-openclaw.openapi.json`

Artifact notes:

- this is a filtered OpenAPI export from `create_app().openapi()`
- it keeps the OpenClaw operator surface plus the shared `/health` and
  authenticated `/metrics` endpoints
- it does not include unrelated product/admin/search routes outside the
  OpenClaw beta contract

OpenClaw-specific docs:

- `D:\code\agentic-memory\docs\openclaw\guides\PRIVATE_BETA_QUICKSTART.md`
- `D:\code\agentic-memory\docs\openclaw\openapi\README.md`

Core endpoints in the committed OpenClaw surface:

- `GET /health`
- `GET /metrics`
- `POST /openclaw/session/register`
- `POST /openclaw/memory/search`
- `POST /openclaw/memory/read`
- `POST /openclaw/memory/ingest-turn`
- `POST /openclaw/context/resolve`
- `POST /openclaw/project/activate`
- `POST /openclaw/project/deactivate`
- `POST /openclaw/project/status`
- `POST /openclaw/project/automation`
- `GET /openclaw/health/detailed`
- `GET /openclaw/metrics/summary`
- `GET /openclaw/search/recent`
- `GET /openclaw/agents/{agent_id}/sessions`
- `GET /openclaw/workspaces`

Auth model:

- `/health`
  - no bearer token required
- `/metrics`
  - bearer token required
- `/openclaw/*`
  - bearer token required

The rest of this document covers the broader CLI, MCP, config, and Python API
surfaces for Agentic Memory as a whole.

---

## CLI Commands

### `agentic-memory init`

Initialize Agentic Memory in the current repository with an interactive wizard.

**Usage:**
```bash
agentic-memory init
```

**What it does:**
1. Creates `.codememory/` directory
2. Generates `config.json` with your settings
3. Offers to run initial indexing
4. Tests Neo4j connection

**Default code embedding provider:**
- New repos default `modules.code` to Gemini (`gemini-embedding-2-preview`).
- That keeps code memory aligned with the rest of the multimodal Agentic Memory system.
- You can switch code to another text embedding model, such as OpenAI, if you want a separate code-memory lane.

**Interactive prompts:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step 1: Neo4j Database Configuration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Options:
  1. Local Neo4j (Docker)
  2. Neo4j Aura (Cloud)
  3. Custom URL
  4. Use environment variables

Choose Neo4j setup [1-4] (default: 1):
```

**Output files:**
- `.codememory/config.json` - Repository configuration
- `.codememory/` - Added to `.gitignore`

**Example:**
```bash
$ cd /path/to/my/project
$ agentic-memory init

🚀 Initializing Agentic Memory in: /path/to/my/project

[Follow prompts...]

✅ Agentic Memory initialized successfully!
Config file: /path/to/my/project/.codememory/config.json

Next steps:
  • agentic-memory status    - Show repository status
  • agentic-memory watch     - Start continuous monitoring
  • agentic-memory serve     - Start MCP server for AI agents
```

**Exit codes:**
- `0` - Success
- `1` - Already initialized (edit or remove `.codememory/` to re-run setup)

---

### `agentic-memory status`

Display statistics about the indexed repository.

**Usage:**
```bash
agentic-memory status
```

**Output:**
```
📊 Agentic Memory Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Repository: /path/to/project
Config:     /path/to/project/.codememory/config.json

📈 Graph Statistics:
   Files:     142
   Functions: 856
   Classes:   67
   Chunks:    923
   Last sync: 2025-02-09 14:32:15
```

**Error cases:**
- Not initialized: Suggests running `agentic-memory init`
- Neo4j unavailable: Shows connection error

---

### `agentic-memory index`

Run a one-time structural ingestion pipeline.

**Usage:**
```bash
agentic-memory index [options]
```

**Options:**
- `--quiet`, `-q` - Suppress progress output

**What it does:**
1. Pass 0: Setup database constraints
2. Pass 1: Scan files and detect changes
3. Pass 2: Parse entities and create embeddings
4. Pass 3: Build import graph

**Important:**
- Normal `index` no longer runs repo-wide `CALLS` construction.
- Behavioral tracing is now on demand through `trace-execution`.
- The older repo-wide analyzer-backed `CALLS` path is still available explicitly through `build-calls`.

**Example:**
```bash
$ agentic-memory index

============================================================
🚀 Starting Hybrid GraphRAG Ingestion
============================================================

📂 [Pass 1] Scanning Directory Structure...
✅ [Pass 1] Processed 15 new/modified files.

🧠 [Pass 2] Extracting Entities & Creating Chunks...
[1/15] 🧠 Processing: src/auth.py...
...
✅ [Pass 2] Entities and Semantic Chunks created.

🕸️ [Pass 3] Linking Files via Imports...
✅ [Pass 3] Import graph built.

============================================================
📊 COST SUMMARY
============================================================
⏱️  Total Time: 45.23 seconds
🔢 Embedding API Calls: 142
📝 Total Tokens Used: 85,234
💰 Estimated Cost: $0.0111 USD
📦 Model: gemini-embedding-2-preview
============================================================
✅ Structural graph is ready for Agent retrieval.
============================================================
```

**When to use:**
- After cloning a new repository
- After major code changes
- If watch mode missed updates
- When you want files, entities, chunks, and imports up to date before using search or JIT tracing

**Exit codes:**
- `0` - Success
- `1` - Not initialized
- `2` - Neo4j connection failed
- `3` - Configured code embedding provider API error

---

### `agentic-memory watch`

Start continuous file monitoring and incremental updates.

**Usage:**
```bash
agentic-memory watch [options]
```

**Options:**
- `--no-scan` - Skip initial full scan (start watching immediately)

**What it does:**
1. Optionally runs full pipeline first
2. Watches filesystem for changes
3. Incrementally updates only changed files
4. Runs until interrupted (Ctrl+C)

**Important:**
- `watch` keeps the structural graph current.
- It does not run repo-wide `CALLS` construction as part of normal file watching.
- Use `trace-execution` for behavior exploration and `build-calls` only for the older experimental repo-wide path.

**Example:**
```bash
$ agentic-memory watch

👀 Starting Observer on: /path/to/project
🛠️  Setting up Database Indexes...
🚀 Running initial full pipeline...
[Full pipeline runs...]
✅ Initial scan complete. Watching for changes...
👀 Watching /path/to/project for changes. Press Ctrl+C to stop.

♻️  Change detected: src/auth.py
✅ Updated graph for: src/auth.py

➕ New file detected: src/utils/helpers.py
✅ Indexed new file: src/utils/helpers.py

🗑️  File deleted: src/legacy.py
✅ Removed from graph: src/legacy.py
```

**Events handled:**
- `on_modified` - File content changed
- `on_created` - New file added
- `on_deleted` - File removed

**Debouncing:**
- Ignores events within 1 second of last event per file
- Prevents redundant processing during save operations

**Limitations:**
- Does not build repo-wide `CALLS` by default
- Only processes supported file extensions (.py, .js, .ts, .tsx, .jsx)

**Exit codes:**
- `0` - Graceful shutdown (Ctrl+C)
- `1` - Configuration error
- `130` - Interrupted by SIGINT

---

### `agentic-memory serve`

Start the MCP server for AI agent integration.

**Usage:**
```bash
agentic-memory serve [options]
```

**Options:**
- `--port` <port> - Port to listen on (default: 8000)

**Example:**
```bash
$ agentic-memory serve

📂 Using config from: /path/to/project/.codememory/config.json
✅ Connected to Neo4j at bolt://localhost:7687
🧠 Starting MCP Interface on port 8000
```

**Server behavior:**
- Runs until interrupted (Ctrl+C)
- Exposes MCP tools for structural retrieval and on-demand behavioral tracing
- Uses local config or environment variables
- Graceful shutdown on SIGTERM/SIGINT

**Configuration priority:**
1. `.codememory/config.json`
2. Environment variables (`NEO4J_URI`, `CODE_EMBEDDING_PROVIDER`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, etc.)
3. Defaults

**Testing the server:**
```bash
# In another terminal
curl http://localhost:8000/tools/search_codebase \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication", "limit": 3}'
```

**Exit codes:**
- `0` - Graceful shutdown
- `1` - Port already in use
- `2` - Neo4j connection failed

---

### `agentic-memory build-calls`

Run the older analyzer-backed repo-wide `CALLS` build explicitly.

**Usage:**
```bash
agentic-memory build-calls [options]
```

**Options:**
- `--json` - Emit machine-readable JSON output

**What it does:**
- Runs the experimental repo-wide `CALLS` path manually
- Preserves analyzer diagnostics and comparison workflows
- Keeps that cost out of normal `index` and `watch`

**When to use:**
- You want to compare the old CALLS path with JIT tracing
- You want analyzer diagnostics in `call-status`
- You are debugging repo-specific semantic analyzer behavior

---

### `agentic-memory trace-execution`

Trace one function's likely execution neighborhood on demand.

**Usage:**
```bash
agentic-memory trace-execution <start_symbol> [options]
```

**Options:**
- `--max-depth <n>` - Maximum recursive direct-call depth to expand (default `2`)
- `--force-refresh` - Ignore valid cached trace data and recompute
- `--repo <path>` - Repository root path
- `--json` - Emit machine-readable JSON output

**Resolution order for `<start_symbol>`:**
1. exact `path:qualified_name` signature
2. unique repo-local `qualified_name`
3. unique repo-local short `name`

If resolution stays ambiguous, the command returns candidates instead of guessing.

**What it returns:**
- resolved root function
- typed edges:
  - `direct_call`
  - `callback`
  - `message_flow`
- unresolved targets
- cache hit/miss metadata
- repo CALLS diagnostics for operator context

**Why this exists:**
- It replaces mandatory repo-wide behavior tracing during normal indexing
- It lets operators and MCP clients pay for behavioral exploration only when they need it

---

### `agentic-memory search`

Test semantic search from the command line (for debugging/testing).

**Usage:**
```bash
agentic-memory search <query> [options]
```

**Arguments:**
- `query` - Natural language search query (required)

**Options:**
- `--limit`, `-l` <number> - Maximum results to return (default: 5)

**Example:**
```bash
$ agentic-memory search "JWT token validation" --limit 3

Found 3 result(s):

1. **verify_token** [`src/auth/tokens.py:verify_token`] - Score: 0.94
   ```
   def verify_token(token: str) -> bool:
       """Verify JWT signature and expiration"""
       try:
           decoded = jwt.decode(token, SECRET, algorithms=["HS256"])
           return decoded.get("exp", 0) > time.time()
       except JWTError:
           return False
   ```

2. **decode_jwt** [`src/auth/utils.py:decode_jwt`] - Score: 0.87
   ```
   def decode_jwt(encoded: str) -> dict:
       """Decode JWT payload without verification"""
       return jwt.decode(encoded, options={"verify_signature": False})
   ```

3. **refresh_access** [`src/auth/session.py:refresh_access`] - Score: 0.81
   ```
   async def refresh_access(refresh_token: str) -> str:
       """Generate new access token from refresh token"""
       user = await verify_refresh_token(refresh_token)
       return create_access_token(user.id)
   ```

```

**When to use:**
- Verify embeddings are working
- Test search query quality
- Debug search results
- Quick lookup without AI agent

**Exit codes:**
- `0` - Success
- `1` - Not initialized
- `2` - Configured code embedding API key not configured
- `3` - No results found

---

## MCP Tools

### Tool: `search_codebase`

Semantically search the codebase for functionality.

**Signature:**
```python
def search_codebase(query: str, limit: int = 5) -> str
```

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language search query |
| `limit` | integer | No | 5 | Maximum number of results |

**Returns:**
Formatted Markdown string with search results.

**Example output:**
```markdown
Found 3 relevant code result(s):

1. **authenticate** (`src/auth.py:authenticate`) [Score: 0.92]
   ```
   def authenticate(username, password):
       """Verify user credentials and return session token"""
       if not verify_password(username, password):
           raise AuthenticationError("Invalid credentials")
       return create_session(username)
   ```

2. **login** (`src/controllers/user.py:login`) [Score: 0.87]
   ```
   async def login(request):
       """Handle user login requests"""
       data = await request.json()
       user = authenticate(data["username"], data["password"])
       return json_response({"token": user.token})
   ```
```

**Use cases:**
- Finding implementation of specific features
- Locating bug-prone code areas
- Understanding codebase organization

**Error cases:**
- Graph not initialized: Returns "❌ Graph not initialized"
- Code embedding key missing: Returns "❌ Configured code embedding API key not configured"
- No results: Returns "No relevant code found"

---

### Tool: `get_file_dependencies`

Returns files that this file IMPORTS and files that IMPORT this file.

**Signature:**
```python
def get_file_dependencies(file_path: str) -> str
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | Yes | Relative path to file (e.g., "src/services/auth.py") |

**Returns:**
Formatted Markdown string with bidirectional dependencies.

**Example output:**
```markdown
## Dependencies for `src/services/auth.py`

### 📥 Imports (this file depends on):
- `src/models/user.py`
- `src/database/connection.py`
- `src/utils/hash.py`

### 📤 Imported By (files that depend on this):
- `src/api/routes/users.py`
- `src/api/routes/auth.py`
- `src/scripts/migrate_users.py`
```

**Use cases:**
- Understanding module dependencies
- Refactoring without breaking imports
- Identifying tightly coupled code

**Error cases:**
- File not found: Returns "❌ File `{path}` not found in the graph"
- Invalid path: Returns "❌ Invalid file path format"

---

### Tool: `identify_impact`

Identify the blast radius of changes to a file (transitive dependents).

**Signature:**
```python
def identify_impact(file_path: str, max_depth: int = 3) -> str
```

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Relative path to file |
| `max_depth` | integer | No | 3 | Maximum depth for transitive deps |

**Returns:**
Formatted Markdown string with affected files organized by depth.

**Example output:**
```markdown
## Impact Analysis for `src/models/user.py`

**Total affected files:** 8

### Depth 1 (direct dependents): 3 files
- `src/services/user.py`
- `src/api/routes/users.py`
- `src/api/routes/auth.py`

### Depth 2 (2-hop transitive dependents): 5 files
- `src/api/routes/admin.py`
- `src/tests/test_users.py`
- `src/tests/test_auth.py`
- `src/scripts/init_db.py`
- `src/controllers/user_controller.py`
```

**Use cases:**
- Assessing risk before refactoring
- Pre-commit impact checks
- Planning incremental changes

**Error cases:**
- File not found: Returns "❌ File not found in the graph"
- No dependents: Returns "No files depend on this file. Changes are isolated."

---

### Tool: `get_file_info`

Get detailed information about a file including its entities and relationships.

**Signature:**
```python
def get_file_info(file_path: str) -> str
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | Yes | Relative path to file |

**Returns:**
Formatted Markdown string with file structure.

**Example output:**
```markdown
## File: `user.py`

**Path:** `src/services/user.py`
**Last Updated:** 2025-02-09 14:32:15

### 📦 Classes (2)
- `UserService`

---

### Tool: `trace_execution_path`

Trace one function's likely execution neighborhood on demand.

**Signature:**
```python
def trace_execution_path(
    start_symbol: str,
    max_depth: int = 2,
    force_refresh: bool = False,
    repo_id: str | None = None,
) -> str
```

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_symbol` | string | Yes | - | Function signature or symbol name to trace |
| `max_depth` | integer | No | 2 | Recursive direct-call expansion depth |
| `force_refresh` | boolean | No | False | Ignore valid cached trace results |
| `repo_id` | string | No | None | Optional explicit repo target |

**Behavior:**
- resolves the root symbol deterministically
- traces one function at a time instead of building a whole-repo call graph
- caches trace results separately from trusted structural graph edges
- returns ambiguity candidates instead of guessing when symbol resolution is unsafe

**Edge/result categories:**
- `direct_call`
- `callback`
- `message_flow`
- unresolved targets

**Use cases:**
- understand what one entry point likely invokes
- inspect callback and message-driven behavior around one handler
- explore a behavioral neighborhood only when an agent actually needs it

**Error cases:**
- ambiguous symbol: returns candidate functions instead of guessing
- missing symbol: reports not found
- trace backend failure: returns formatted trace failure message
- `UserProfile`

### ⚡ Functions (5)
- `create_user()`
- `get_user_by_id()`
- `update_user()`
- `delete_user()`
- `list_users()`

### 📥 Imports (3)
- `src/models/user.py`
- `src/database/connection.py`
- `src/utils/hash.py`
```

**Use cases:**
- Quick file overview
- Understanding file organization
- Navigating large codebases

**Error cases:**
- File not found: Returns "❌ File `{path}` not found in the graph"
- Not yet indexed: Returns "*No entities found. File may not be parsed yet.*"

---

## Configuration Options

### Configuration File Structure

**Location:** `.codememory/config.json`

**Schema:**
```json
{
  "neo4j": {
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "password"
  },
  "gemini": {
    "api_key": null
  },
  "openai": {
    "api_key": null
  },
  "modules": {
    "code": {
      "embedding_provider": "gemini",
      "embedding_model": "gemini-embedding-2-preview",
      "embedding_dimensions": 3072
    },
    "web": {
      "embedding_provider": "gemini",
      "embedding_model": "gemini-embedding-2-preview",
      "embedding_dimensions": 3072
    },
    "chat": {
      "embedding_provider": "gemini",
      "embedding_model": "gemini-embedding-2-preview",
      "embedding_dimensions": 3072
    }
  },
  "indexing": {
    "ignore_dirs": [
      "node_modules",
      "__pycache__",
      ".git",
      "dist",
      "build",
      ".venv",
      "venv",
      ".pytest_cache",
      ".mypy_cache",
      "target",
      "bin",
      "obj"
    ],
    "ignore_files": [],
    "extensions": [".py", ".js", ".ts", ".tsx", ".jsx"]
  }
}
```

### Configuration Options Reference

#### `neo4j.uri`

**Type:** string
**Default:** `"bolt://localhost:7687"`
**Environment variable:** `NEO4J_URI`

Neo4j connection URI.

**Examples:**
- Local Docker: `bolt://localhost:7687`
- Neo4j Aura: `neo4j+s://instance.databases.neo4j.io`
- Remote server: `bolt://neo4j.example.com:7687`

---

#### `neo4j.user`

**Type:** string
**Default:** `"neo4j"`
**Environment variable:** `NEO4J_USER`

Neo4j username.

---

#### `neo4j.password`

**Type:** string
**Default:** `"password"`
**Environment variable:** `NEO4J_PASSWORD`

Neo4j password.

**Security:** Avoid committing to version control. Use environment variables in production.

---

#### `gemini.api_key`

**Type:** string or null
**Default:** `null`
**Environment variables:** `GEMINI_API_KEY`, `GOOGLE_API_KEY`

Gemini API key for the default code embedding provider.

**Examples:**
- In config: `"AIza..."`
- Use env var: `null` (recommended)
- No key: `null` (semantic code search disabled until a key is supplied)

---

#### `openai.api_key`

**Type:** string or null
**Default:** `null`
**Environment variable:** `OPENAI_API_KEY`

Optional OpenAI API key when you intentionally switch the `code` module to OpenAI.

**Examples:**
- In config: `"sk-..."`
- Use env var: `null` (recommended)
- No key: `null` (semantic search disabled)

**Get API key:** https://platform.openai.com/api-keys

---

#### `modules.code`

**Type:** object

Per-module embedding configuration for code memory.

**Fields:**
- `embedding_provider`
- `embedding_model`
- `embedding_dimensions`

**Default:**
```json
{
  "embedding_provider": "gemini",
  "embedding_model": "gemini-embedding-2-preview",
  "embedding_dimensions": 3072
}
```

---

#### `indexing.ignore_dirs`

**Type:** array of strings
**Default:** `["node_modules", "__pycache__", ".git", ...]`

Directories to skip during indexing.

**Patterns:** Simple name matching (not regex).

**Examples:**
```json
{
  "ignore_dirs": [
    "node_modules",
    "__pycache__",
    "tests",
    "migrations",
    "vendor"
  ]
}
```

---

#### `indexing.ignore_files`

**Type:** array of strings
**Default:** `[]`

Specific files to skip during indexing.

**Examples:**
```json
{
  "ignore_files": [
    "setup.py",
    "__init__.py"
  ]
}
```

---

#### `indexing.extensions`

**Type:** array of strings
**Default:** `[".py", ".js", ".ts", ".tsx", ".jsx"]`

File extensions to index.

**Supported:**
- `.py` - Python
- `.js`, `.jsx` - JavaScript
- `.ts`, `.tsx` - TypeScript

**Examples:**
```json
{
  "extensions": [".py"]  // Only Python files
}
```

---

### Environment Variables

**Priority:** Environment variables override config file values.

| Variable | Purpose | Example |
|----------|---------|---------|
| `NEO4J_URI` | Neo4j connection URI | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | `your_password` |
| `CODE_EMBEDDING_PROVIDER` | Code embedding provider override | `gemini`, `openai`, `nemotron` |
| `GEMINI_API_KEY` | Default Gemini code embedding API key | `your-gemini-key` |
| `GOOGLE_API_KEY` | Alternate Gemini auth env var | `your-gemini-key` |
| `OPENAI_API_KEY` | Optional OpenAI key for code isolation | `sk-...` |
| `LOG_LEVEL` | Logging verbosity | `DEBUG`, `INFO`, `WARNING` |

**Example `.env` file:**
```bash
# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=secure_password

# Default code embedding provider
GEMINI_API_KEY=your-gemini-api-key-here

# Optional: keep code memory separate on OpenAI instead
# CODE_EMBEDDING_PROVIDER=openai
# OPENAI_API_KEY=sk-your-api-key-here

# Optional
LOG_LEVEL=INFO
```

---

## Python API

### KnowledgeGraphBuilder

Main class for graph operations.

**Location:** `src/agentic_memory/ingestion/graph.py`

#### Constructor

```python
def __init__(
    uri: str,
    user: str,
    password: str,
    openai_key: Optional[str],
    repo_root: Optional[Path] = None,
    ignore_dirs: Optional[Set[str]] = None,
    ignore_files: Optional[Set[str]] = None,
    *,
    config: Any | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    embedding_api_key: str | None = None,
    embedding_base_url: str | None = None,
    embedding_dimensions: int | None = None
)
```

**Parameters:**
- `uri` - Neo4j connection URI
- `user` - Neo4j username
- `password` - Neo4j password
- `openai_key` - Legacy OpenAI API key parameter for backward compatibility
- `repo_root` - Repository path (optional)
- `ignore_dirs` - Directories to ignore (optional)
- `ignore_files` - Files to ignore (optional)
- `config` - Repo config used to resolve the module's embedding provider/model
- `embedding_provider` - Explicit provider override for code embeddings
- `embedding_model` - Explicit model override
- `embedding_api_key` - Explicit provider API key override
- `embedding_base_url` - Optional provider base URL override
- `embedding_dimensions` - Optional output dimension override

**Example:**
```python
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from pathlib import Path

builder = KnowledgeGraphBuilder(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password",
    openai_key=None,
    repo_root=Path("/path/to/repo")
)
```

---

#### Methods

##### `setup_database()`

Create database constraints and indexes.

```python
def setup_database(self) -> None
```

**Example:**
```python
builder.setup_database()
# Creates:
# - Uniqueness constraints
# - Vector index
# - Fulltext index
```

---

##### `run_pipeline()`

Execute the full 4-pass ingestion pipeline.

```python
def run_pipeline(self, repo_path: Optional[Path] = None) -> Dict
```

**Returns:**
```python
{
    "elapsed_seconds": 45.23,
    "embedding_calls": 142,
    "tokens_used": 85234,
    "cost_usd": 0.0111
}
```

**Example:**
```python
metrics = builder.run_pipeline(Path("/path/to/repo"))
print(f"Cost: ${metrics['cost_usd']:.4f}")
```

---

##### `semantic_search()`

Perform vector similarity search.

```python
def semantic_search(self, query: str, limit: int = 5) -> List[Dict]
```

**Returns:**
```python
[
    {
        "name": "authenticate",
        "sig": "src/auth.py:authenticate",
        "score": 0.92,
        "text": "def authenticate(username, password):..."
    },
    ...
]
```

**Example:**
```python
results = builder.semantic_search("JWT validation", limit=3)
for r in results:
    print(f"{r['name']} - Score: {r['score']:.2f}")
```

---

##### `get_file_dependencies()`

Get bidirectional file dependencies.

```python
def get_file_dependencies(self, file_path: str) -> Dict[str, List[str]]
```

**Returns:**
```python
{
    "imports": ["src/models/user.py", "src/utils/hash.py"],
    "imported_by": ["src/api/routes/users.py"]
}
```

**Example:**
```python
deps = builder.get_file_dependencies("src/services/auth.py")
print(f"Imports: {deps['imports']}")
print(f"Imported by: {deps['imported_by']}")
```

---

##### `identify_impact()`

Analyze transitive dependents of a file.

```python
def identify_impact(
    self,
    file_path: str,
    max_depth: int = 3
) -> Dict[str, List[Dict]]
```

**Returns:**
```python
{
    "affected_files": [
        {"path": "src/api/users.py", "depth": 1, "impact_type": "dependents"},
        {"path": "src/controllers/user.py", "depth": 2, "impact_type": "dependents"}
    ],
    "total_count": 2
}
```

**Example:**
```python
impact = builder.identify_impact("src/models/user.py", max_depth=2)
print(f"Total affected: {impact['total_count']}")
for f in impact['affected_files']:
    print(f"  {f['path']} (depth {f['depth']})")
```

---

##### `close()`

Close database connection.

```python
def close(self) -> None
```

**Example:**
```python
builder.close()
```

---

### Config

Configuration management class.

**Location:** `src/agentic_memory/config.py`

#### Constructor

```python
def __init__(self, repo_root: Path)
```

**Example:**
```python
from agentic_memory.config import Config
from pathlib import Path

config = Config(Path("/path/to/repo"))
```

---

#### Methods

##### `exists()`

Check if configuration exists.

```python
def exists(self) -> bool
```

---

##### `load()`

Load configuration from file.

```python
def load(self) -> Dict[str, Any]
```

---

##### `save()`

Save configuration to file.

```python
def save(self, config: Dict[str, Any]) -> None
```

---

##### `get_neo4j_config()`

Get Neo4j configuration with env var fallback.

```python
def get_neo4j_config(self) -> Dict[str, str]
```

**Returns:**
```python
{
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "password"
}
```

---

##### `get_module_config()`

Get per-module embedding configuration.

```python
def get_module_config(self, module_name: str) -> Dict[str, Any]
```

---

##### `get_embedding_provider_config()`

Get provider-level config such as API keys and base URLs.

```python
def get_embedding_provider_config(self, provider_name: str) -> Dict[str, Any]
```

---

##### `get_indexing_config()`

Get indexing configuration.

```python
def get_indexing_config(self) -> Dict[str, Any]
```

---

## Error Codes

### CLI Exit Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 0 | Success | - |
| 1 | General error | Not initialized, invalid config |
| 2 | Connection failed | Neo4j unavailable, wrong credentials |
| 3 | API error | Code embedding provider key invalid, provider rate limit |
| 130 | Interrupted | Ctrl+C pressed |

### MCP Tool Errors

| Error | Message | Resolution |
|-------|---------|------------|
| Graph not initialized | "❌ Graph not initialized" | Run `agentic-memory index` |
| File not found | "❌ File not found in the graph" | Check file path, run indexing |
| Code embedding key missing | "❌ Configured code embedding API key not configured" | Set `GEMINI_API_KEY` / `GOOGLE_API_KEY`, or switch provider and set that provider's key |
| No results | "No relevant code found" | Try different query |
| Connection failed | "❌ Failed to connect to Neo4j" | Check Neo4j is running |

### Exception Types

**Python exceptions raised:**

| Exception | When | How to handle |
|-----------|------|---------------|
| `RuntimeError` | Config file corrupted | Re-run `agentic-memory init` |
| `neo4j.ServiceUnavailable` | Neo4j not running | Start Neo4j |
| Provider-specific auth exception | Invalid embedding API key | Check the configured provider key |
| Provider-specific rate-limit exception | Embedding API rate limit | Wait and retry |
| `FileNotFoundError` | Repository not found | Check path is correct |

---

## Type Definitions

### FileNode

```python
{
    "path": str,              # Unique identifier
    "name": str,              # Filename
    "ohash": str,             # MD5 hash
    "last_updated": datetime  # Timestamp
}
```

### FunctionNode

```python
{
    "signature": str,         # Unique identifier
    "name": str,              # Function name
    "code": str,              # Full source
    "docstring": str | None,  # Docstring
    "parameters": str | None, # Parameters
    "return_type": str | None # Return type
}
```

### ClassNode

```python
{
    "qualified_name": str,    # Unique identifier
    "name": str,              # Class name
    "code": str               # Full source
}
```

### ChunkNode

```python
{
    "id": str,                # UUID
    "text": str,              # Code snippet
    "embedding": List[float], # 3072-dim vector
    "created_at": datetime    # Timestamp
}
```

### SearchResult

```python
{
    "name": str,              # Entity name
    "sig": str,               # Entity signature
    "score": float,           # Similarity (0-1)
    "text": str               # Code snippet
}
```

### ImpactResult

```python
{
    "path": str,              # File path
    "depth": int,             # Distance from source
    "impact_type": str        # "dependents"
}
```

---

**API Version:** 1.0.0
**Last Updated:** 2025-02-09
