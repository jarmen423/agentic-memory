# Architecture

**Analysis Date:** 2026-03-20

## Pattern Overview

**Overall:** Hybrid GraphRAG with layered ingestion pipeline and Model Context Protocol (MCP) server interface.

**Key Characteristics:**
- Multi-pass ingestion pipeline (structure scan → entity extraction → embedding → relationship linking)
- Neo4j graph database as central knowledge store with vector search capability
- Tree-sitter AST parsing for language-agnostic code analysis (Python, JavaScript/TypeScript)
- Optional git history graph for commit/provenance tracking
- MCP server exposing graph queries as tools for AI agents
- Telemetry-based tool-use tracking for annotation and analysis

## Layers

**CLI Entry Point:**
- Purpose: User-facing command interface for initialization, indexing, watching, and querying
- Location: `src/codememory/cli.py`
- Contains: 12+ command handlers (init, status, index, watch, serve, search, deps, impact, git-init, git-sync, git-status, annotate)
- Depends on: Config, KnowledgeGraphBuilder, GitGraphIngestor, TelemetryStore
- Used by: Direct invocation via `codememory` command

**Configuration Management:**
- Purpose: Per-repository config resolution with fallback to environment variables
- Location: `src/codememory/config.py`
- Contains: Config class, DEFAULT_CONFIG template, repo root discovery, .graphignore pattern loading
- Depends on: pathlib, json, os (environment variables)
- Used by: CLI, server initialization

**Ingestion Layer:**
- Purpose: Transform raw repository code into structured graph nodes
- Location: `src/codememory/ingestion/`
- Contains three main components:
  - `parser.py`: CodeParser class using tree-sitter for AST extraction (functions, classes, imports, calls, env vars)
  - `graph.py`: KnowledgeGraphBuilder orchestrating 4-pass pipeline + semantic search
  - `git_graph.py`: GitGraphIngestor for optional git history sync
  - `watcher.py`: FileSystemEventHandler for incremental updates during active development
- Depends on: tree-sitter, neo4j driver, openai embeddings, watchdog
- Used by: CLI commands (index, watch), MCP server

**Knowledge Graph Builder (graph.py):**
- Purpose: Central orchestrator for code analysis and graph creation
- Contains:
  - **Pass 0**: Database setup (constraints, vector indexes, fulltext indexes)
  - **Pass 1**: Structure scan with change detection (MD5 hash-based)
  - **Pass 2**: Entity definition (parse files, extract functions/classes, create nodes)
  - **Pass 3**: Relationship linking (imports, calls, class methods)
  - **Pass 4**: Chunking and embedding generation (OpenAI text-embedding-3-large, 3072 dimensions)
  - Utility methods: semantic_search, get_file_dependencies, identify_impact
- Uses Circuit Breaker pattern for Neo4j resilience
- Uses Retry decorator for OpenAI transient errors
- Token usage tracking for cost estimation

**MCP Server:**
- Purpose: Expose graph capabilities as tools for AI agents via Model Context Protocol
- Location: `src/codememory/server/app.py` and `tools.py`
- Contains: FastMCP server, rate limiting, tool decorators, tool registry
- Depends on: mcp library, KnowledgeGraphBuilder, telemetry store
- Used by: AI agents communicating over MCP protocol

**Toolkit (tools.py):**
- Purpose: High-level semantic operations for agent consumption
- Location: `src/codememory/server/tools.py`
- Contains: Toolkit class wrapping graph methods with human-readable formatting
- Methods: semantic_search, get_file_dependencies, get_git_file_history, get_commit_context
- Returns: Markdown-formatted strings for LLM parsing

**Telemetry Layer:**
- Purpose: Track tool-use patterns for analysis and manual annotation workflow
- Location: `src/codememory/telemetry.py`
- Contains: TelemetryStore class using SQLite with tool_calls and manual_annotations tables
- Tracks: tool name, duration, success/error, client_id, repo_root, annotation metadata
- Used by: MCP server (log_tool_call decorator), CLI annotation workflow

## Data Flow

**Initialization Flow (cmd_init):**

1. User runs `codememory init`
2. Interactive wizard collects Neo4j credentials, OpenAI API key, file extensions, ignore patterns
3. Config saved to `<repo>/.codememory/config.json`
4. .graphignore patterns saved to `<repo>/.codememory/.graphignore`
5. Optional: Run initial indexing (pass_1 through pass_4)

**Indexing Flow (index/watch):**

1. CLI resolves repo root and loads config
2. KnowledgeGraphBuilder initialized with Neo4j connection, OpenAI client, ignore patterns
3. `run_pipeline()` executes:
   - **Pass 0**: setup_database() creates constraints and indexes
   - **Pass 1**: pass_1_structure_scan() walks repo, creates File nodes, change detection via MD5 hash
   - **Pass 2**: pass_2_entity_definition() parses files with tree-sitter, extracts classes/functions, creates entity nodes
   - **Pass 3**: pass_3_relationship_linking() creates IMPORTS, CALLS, DEFINES relationships
   - **Pass 4**: pass_4_embedding_and_chunking() chunks entities, generates embeddings via OpenAI, creates Chunk nodes with vectors
4. Returns metrics: embedding_calls, cost_usd

**Watch Flow (cmd_watch):**

1. CodeChangeHandler attached to watchdog Observer
2. File modifications trigger on_modified() → _delete_file_entities() → _process_single_file()
3. Incremental update: re-parse, re-embed, update relationships
4. Continues until process exits

**Query Flow (semantic_search, dependencies, impact):**

1. CLI or MCP tool invokes KnowledgeGraphBuilder.semantic_search(query)
2. If OpenAI available: embed query, vector search Chunk nodes, return ranked results
3. If no OpenAI: fallback to fulltext search on Function/Class names
4. For dependency queries: traverse IMPORTS relationships (direct + transitive)

**Git History Flow (cmd_git_sync):**

1. GitGraphIngestor.initialize() creates GitRepo node, sets up schema
2. GitGraphIngestor.sync() runs `git log` with custom format, parses commits
3. Creates Commit nodes with author, message, timestamp
4. Creates GitFileChange nodes linked to Commits
5. Optional: links commits to File/Function nodes that changed

**MCP Server Flow (serve):**

1. run_server() initializes FastMCP instance
2. init_graph() loads config, creates KnowledgeGraphBuilder
3. init_telemetry() creates TelemetryStore
4. Tool functions decorated with @log_tool_call and @rate_limit
5. Agent sends tool requests → FastMCP routes to handlers → Toolkit methods format responses
6. TelemetryStore records call metadata

**Annotation Flow (cmd_annotate_interaction):**

1. User runs `codememory --prompted "check auth"` after agent response
2. TelemetryStore.create_pending_annotation() stores annotation metadata
3. Waits up to N seconds for latest tool-use burst to settle (based on idle threshold)
4. TelemetryStore.get_latest_unannotated_burst() retrieves tool calls
5. TelemetryStore.apply_annotation_to_calls() links annotation_id to matching calls
6. Records whether tool usage was user-prompted or agent-initiated

**State Management:**

- **Graph State**: Neo4j as single source of truth; all code analysis persisted as labeled property graph
- **Configuration State**: JSON file in `.codememory/config.json`; overridable per setting via environment variables
- **Telemetry State**: SQLite database at `.codememory/telemetry.sqlite3`; immutable append-only log
- **Parser State**: Ephemeral; tree-sitter parsers initialized per KnowledgeGraphBuilder instance
- **Watch State**: In-memory debounce cache (file path → timestamp) in CodeChangeHandler

## Key Abstractions

**KnowledgeGraphBuilder:**
- Purpose: Encapsulates all graph construction logic
- Examples: `src/codememory/ingestion/graph.py`
- Pattern: Multi-pass orchestrator with circuit breaker for resilience
- Methods: setup_database(), pass_1_structure_scan(), pass_2_entity_definition(), pass_3_relationship_linking(), pass_4_embedding_and_chunking(), semantic_search()

**CircuitBreaker:**
- Purpose: Gracefully handle repeated Neo4j failures
- Pattern: State machine (CLOSED → OPEN → HALF_OPEN)
- Prevents cascading failures when database unavailable

**CodeParser:**
- Purpose: Language-agnostic AST extraction
- Examples: `src/codememory/ingestion/parser.py`
- Pattern: Factory pattern with extension-to-parser mapping
- Supports: .py (Python), .js/.jsx/.ts/.tsx (JavaScript/TypeScript)

**Config:**
- Purpose: Centralized configuration with environment variable fallbacks
- Examples: `src/codememory/config.py`
- Pattern: Single responsibility - load/save/merge config dictionaries
- Merges user config with defaults, supports nested override

**TelemetryStore:**
- Purpose: SQLite-backed event logging for tool-use analysis
- Examples: `src/codememory/telemetry.py`
- Pattern: Thread-safe append-only log with annotation linking
- Tables: tool_calls (timestamped events), manual_annotations (metadata)

**Toolkit:**
- Purpose: Bridge between graph methods and MCP tool interface
- Examples: `src/codememory/server/tools.py`
- Pattern: Adapter; wraps graph results in human-readable markdown

## Entry Points

**CLI Main:**
- Location: `src/codememory/cli.py::main()`
- Triggers: User invokes `codememory` command
- Responsibilities: Parse arguments, dispatch to command handlers, format output (human or JSON)

**Command Handlers:**
- `cmd_init()`: Interactive setup wizard
- `cmd_status()`: Query graph statistics
- `cmd_index()`: One-time full pipeline
- `cmd_watch()`: Continuous incremental updates
- `cmd_serve()`: Start MCP server
- `cmd_search()`: Semantic search
- `cmd_deps()`: File dependency analysis
- `cmd_impact()`: Transitive impact analysis
- `cmd_git_init()`, `cmd_git_sync()`, `cmd_git_status()`: Git integration
- `cmd_annotate_interaction()`: Manual annotation of tool usage

**MCP Server Entry:**
- Location: `src/codememory/server/app.py::run_server()`
- Triggers: User runs `codememory serve` or MCP client connects
- Responsibilities: Initialize FastMCP, load graph, register tools, listen for requests

## Error Handling

**Strategy:** Layered error handling with graceful degradation.

**Patterns:**

- **OpenAI Failures**: `@retry_on_openai_error` decorator with exponential backoff (3 retries, 1s delay)
  - RateLimitError, APIConnectionError, APITimeoutError caught and retried
  - On final failure: return zero-vector to allow pipeline to continue

- **Neo4j Connection Failures**: Circuit breaker pattern (CLOSED → OPEN after 5 failures, recovers after 30s timeout)
  - ServiceUnavailable and DatabaseError wrapped in circuit breaker
  - Prevents thundering herd of retries

- **File System Errors**: Logged and skipped during watch operations
  - IOError, OSError during file read caught, handler continues
  - Debounce prevents cascade of redundant updates

- **Config Errors**: Exit with human-readable message + JSON error if --json flag set
  - `_exit_with_error()` unified error handler in CLI
  - SystemExit with code 1

- **Parsing Errors**: Logged, returns empty result, pipeline continues
  - Tree-sitter failures don't block other files
  - Graceful degradation for unsupported syntax

## Cross-Cutting Concerns

**Logging:**
- Implementation: Python logging module with per-module loggers
- Pattern: logger.info/warning/error with emoji prefixes for visual scanning
- Levels: INFO (default), WARNING (recoverable issues), ERROR (failures)
- Configured in watcher.py with basicConfig

**Validation:**
- Command args: argparse for CLI validation
- File paths: fnmatch patterns for .graphignore matching
- Graph queries: Neo4j Cypher validation (handled by Neo4j driver)
- OpenAI requests: Text truncation to 24000 chars before embedding

**Authentication:**
- Neo4j: Username/password auth, stored in config or env vars (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
- OpenAI: API key in config or env var (OPENAI_API_KEY)
- Environment variable precedence: CLI args > .env file > config.json > defaults
- See `_load_repo_env()` and config getter methods for precedence

**Rate Limiting:**
- MCP server: 100 requests per 60-second window per tool
- OpenAI: Handled via SDK; circuit breaker prevents cascading failures
- Watchdog: 1-second debounce per file to prevent thrashing

---

*Architecture analysis: 2026-03-20*
