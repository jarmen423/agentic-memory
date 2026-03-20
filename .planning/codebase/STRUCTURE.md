# Codebase Structure

**Analysis Date:** 2026-03-20

## Directory Layout

```
agentic-memory/
├── src/codememory/              # Main package
│   ├── __init__.py              # Package marker (empty)
│   ├── cli.py                   # CLI entry point with 12+ command handlers
│   ├── config.py                # Configuration management and defaults
│   ├── telemetry.py             # SQLite-based tool-use telemetry
│   ├── ingestion/               # Code analysis and graph construction
│   │   ├── __init__.py
│   │   ├── graph.py             # KnowledgeGraphBuilder (4-pass pipeline)
│   │   ├── parser.py            # CodeParser using tree-sitter
│   │   ├── git_graph.py         # GitGraphIngestor for commit history
│   │   └── watcher.py           # FileSystemEventHandler for incremental updates
│   └── server/                  # MCP server interface
│       ├── __init__.py
│       ├── app.py               # FastMCP server initialization
│       └── tools.py             # Toolkit class with LLM-friendly methods
├── tests/                       # Test suite
│   ├── __init__.py
│   ├── conftest.py              # pytest fixtures
│   ├── test_cli.py              # CLI command tests
│   ├── test_graph.py            # KnowledgeGraphBuilder tests
│   ├── test_parser.py           # CodeParser tests
│   ├── test_server.py           # MCP server tests
│   └── test_git_graph.py        # GitGraphIngestor tests
├── .planning/codebase/          # GSD codebase documentation
├── pyproject.toml               # Package metadata, dependencies, tool config
├── README.md                    # User documentation
├── SPEC.md                      # Feature specification
└── AGENTS.md                    # Agent integration guides
```

## Directory Purposes

**src/codememory/:**
- Purpose: Main package containing all runtime code
- Contains: CLI, config, ingestion, server, telemetry modules
- Key files: `cli.py` (entry point), `config.py` (configuration), `telemetry.py` (logging)

**src/codememory/ingestion/:**
- Purpose: Code analysis and graph construction pipeline
- Contains: AST parsing, multi-pass ingestion, incremental updates, git history sync
- Key files: `graph.py` (main orchestrator), `parser.py` (language support), `git_graph.py` (commits), `watcher.py` (file monitoring)

**src/codememory/server/:**
- Purpose: MCP server and tool interface for AI agents
- Contains: FastMCP setup, tool registration, rate limiting, logging
- Key files: `app.py` (server), `tools.py` (toolkit methods)

**tests/:**
- Purpose: Pytest test suite for all modules
- Contains: Unit and integration tests
- Test naming: `test_*.py` files with `test_*` functions inside
- Markers: @pytest.mark.unit, @pytest.mark.integration, @pytest.mark.slow

**.planning/codebase/:**
- Purpose: GSD (golden source documents) for codebase navigation
- Contains: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md
- Consumed by: GSD planner and executor commands

## Key File Locations

**Entry Points:**
- `src/codememory/cli.py`: Main CLI entry point; `main()` parses args and dispatches commands
- `src/codememory/server/app.py`: MCP server entry; `run_server(port)` starts FastMCP instance
- `pyproject.toml`: Project metadata; defines `codememory` console script pointing to `cli:main`

**Configuration:**
- `src/codememory/config.py`: Config class, DEFAULT_CONFIG dict, `find_repo_root()`, environment variable resolution
- `<repo>/.codememory/config.json`: Per-repository configuration (Neo4j, OpenAI, indexing)
- `<repo>/.codememory/.graphignore`: Per-repository ignore patterns (glob-style)

**Core Logic:**
- `src/codememory/ingestion/graph.py`: KnowledgeGraphBuilder class with 4-pass pipeline, semantic search, impact analysis
- `src/codememory/ingestion/parser.py`: CodeParser class using tree-sitter for AST extraction
- `src/codememory/ingestion/git_graph.py`: GitGraphIngestor for git commit history
- `src/codememory/ingestion/watcher.py`: CodeChangeHandler for file system monitoring

**MCP Interface:**
- `src/codememory/server/app.py`: `init_graph()`, `init_telemetry()`, MCP tool registration
- `src/codememory/server/tools.py`: Toolkit class with high-level semantic operations

**Telemetry:**
- `src/codememory/telemetry.py`: TelemetryStore class with tool_calls and manual_annotations tables
- `<repo>/.codememory/telemetry.sqlite3`: SQLite database for telemetry (auto-created)

**Testing:**
- `tests/conftest.py`: Pytest fixtures (mock Neo4j driver, sample files, etc.)
- `tests/test_graph.py`: KnowledgeGraphBuilder tests
- `tests/test_parser.py`: CodeParser language support tests
- `tests/test_cli.py`: CLI command handler tests
- `tests/test_server.py`: MCP server and tool tests

## Naming Conventions

**Files:**
- Modules: lowercase with underscores (e.g., `graph.py`, `git_graph.py`, `test_graph.py`)
- Classes: PascalCase (e.g., `KnowledgeGraphBuilder`, `CodeParser`, `TelemetryStore`, `CircuitBreaker`)
- Functions: snake_case (e.g., `cmd_init()`, `pass_1_structure_scan()`, `get_embedding()`)

**Directories:**
- Packages: lowercase plural when logical (e.g., `ingestion/`, `server/`, `tests/`)
- Config directories: dot-prefixed (e.g., `.codememory/`, `.planning/`, `.git/`)

**Classes in source:**
- **Ingestion layer**: `KnowledgeGraphBuilder`, `CodeParser`, `GitGraphIngestor`, `CodeChangeHandler`, `CircuitBreaker`
- **Config layer**: `Config`
- **Server layer**: Toolkit, FastMCP (from mcp library)
- **Telemetry layer**: `TelemetryStore`

**Functions in source:**
- **CLI commands**: `cmd_init()`, `cmd_status()`, `cmd_index()`, `cmd_watch()`, `cmd_serve()`, `cmd_search()`, `cmd_deps()`, `cmd_impact()`, `cmd_git_init()`, `cmd_git_sync()`, `cmd_git_status()`, `cmd_annotate_interaction()`
- **Graph passes**: `pass_1_structure_scan()`, `pass_2_entity_definition()`, `pass_3_relationship_linking()`, `pass_4_embedding_and_chunking()`
- **Decorators**: `@retry_on_openai_error`, `@rate_limit`, `@log_tool_call`
- **Private methods**: `_init_parsers()`, `_should_ignore_dir()`, `_should_ignore_path()`, `_delete_file_subgraph()`

## Where to Add New Code

**New Feature (e.g., new query type):**
- Primary code: `src/codememory/ingestion/graph.py` (add method to KnowledgeGraphBuilder)
- CLI handler: `src/codememory/cli.py` (add cmd_* function and subparser)
- MCP tool: `src/codememory/server/tools.py` (add method to Toolkit)
- MCP registration: `src/codememory/server/app.py` (add @mcp.tool decorator)
- Tests: `tests/test_graph.py`, `tests/test_cli.py`, `tests/test_server.py`

**New Language Support (e.g., add Rust parsing):**
- Parser logic: `src/codememory/ingestion/parser.py` (add language to CodeParser._init_parsers())
- Extension mapping: Update `.parsers` dict and supported_extensions sets
- Query strings: Add language-specific TreeSitter queries in `_extract_classes()`, `_extract_functions()`
- Configuration: Update `DEFAULT_CONFIG["indexing"]["extensions"]` in `config.py`
- Tests: `tests/test_parser.py` (add test for new language)

**New Configuration Option:**
- Default: Add to `DEFAULT_CONFIG` dict in `src/codememory/config.py`
- Loader: Add getter method in Config class (e.g., `get_*_config()`)
- Validator: Add validation in `cmd_init()` if interactive
- Environment override: Add env var check in getter method (follow NEO4J_*, OPENAI_* pattern)

**New CLI Command:**
- Handler: Add `cmd_*()` function in `src/codememory/cli.py`
- Parser setup: Create subparser in `main()` via `subparsers.add_parser()`
- Dispatcher: Add elif branch in command dispatch (end of main())
- Tests: `tests/test_cli.py` with mocked dependencies

**New Database Node Type or Relationship:**
- Schema: Update constraints/indexes in `KnowledgeGraphBuilder.setup_database()`
- Creation: Add creation logic in relevant pass (pass_2, pass_3, or pass_4)
- Querying: Add method to KnowledgeGraphBuilder and/or Toolkit
- Tests: `tests/test_graph.py` with graph assertions

**New Tool/Skill for MCP agents:**
- Toolkit method: Add method to `src/codememory/server/tools.py`
- MCP registration: Add `@mcp.tool()` decorator in `src/codememory/server/app.py`
- Description: Document tool purpose in docstring
- Rate limiting: Applies automatically via `@rate_limit` decorator on tool handler
- Telemetry: Applies automatically via `@log_tool_call` on tool handler

**New Test:**
- Location: `tests/test_*.py` matching the module under test
- Naming: `test_*()` function with descriptive name
- Fixtures: Use conftest.py fixtures (mock_builder, sample_code, etc.)
- Markers: Add @pytest.mark.unit or @pytest.mark.integration as appropriate

## Special Directories

**<repo>/.codememory/:**
- Purpose: Per-repository configuration and state
- Generated: Yes (created by cmd_init)
- Committed: No (in .gitignore)
- Contents:
  - `config.json`: Configuration (Neo4j, OpenAI, indexing)
  - `.graphignore`: Ignore patterns
  - `telemetry.sqlite3`: Tool-use telemetry database

**.planning/codebase/:**
- Purpose: Golden source documents for code generation
- Generated: Yes (created by /gsd:map-codebase command)
- Committed: Yes (tracked in git)
- Contents:
  - `ARCHITECTURE.md`: Overall architecture and data flows
  - `STRUCTURE.md`: Directory layout and file organization
  - `CONVENTIONS.md`: Coding style and patterns
  - `TESTING.md`: Test patterns and coverage
  - `CONCERNS.md`: Technical debt and issues

**tests/:**
- Purpose: Pytest test suite
- Generated: No (manually created)
- Committed: Yes (tracked in git)
- Structure: Mirrors src/ structure for parallel tests

---

*Structure analysis: 2026-03-20*
