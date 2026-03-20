# Coding Conventions

**Analysis Date:** 2026-03-20

## Naming Patterns

**Files:**
- Snake case for all source files: `cli.py`, `config.py`, `git_graph.py`
- Test files follow pattern: `test_<module>.py` (e.g., `test_cli.py`, `test_graph.py`)
- Classes use PascalCase: `KnowledgeGraphBuilder`, `CodeParser`, `TelemetryStore`, `CircuitBreaker`
- Module-level constants use UPPER_CASE: `DEFAULT_CONFIG`, `EMBEDDING_MODEL`, `VECTOR_DIMENSIONS`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW`

**Functions:**
- Snake case for all functions: `pass_1_structure_scan()`, `get_embedding()`, `_extract_classes()`, `_normalize_js_ts_specifier()`
- Private functions prefixed with underscore: `_init_parsers()`, `_should_ignore_dir()`, `_extract_python_import_modules()`
- Test functions prefixed with `test_`: `test_status_json_success_envelope()`, `test_semantic_search()`

**Variables:**
- Snake case for all variables: `repo_root`, `mock_builder`, `failure_threshold`, `openai_key`
- Private instance variables prefixed with underscore: `_debounce_cache`, `_request_log`, `_lock`
- Type-hinted parameters and returns throughout

**Types:**
- All function parameters and returns include type hints
- Use `Optional[Type]` for nullable values
- Use `Dict[str, Any]`, `List[str]`, `Set[str]` for collections
- Modern `dict[str, Any]` syntax used in Python 3.10+ contexts
- Union types for multiple types: `Dict[str, str] | None`

## Code Style

**Formatting:**
- Black formatter with line length: 100 characters (configured in `pyproject.toml`)
- Target versions: Python 3.10, 3.11, 3.12
- Indentation: 4 spaces

**Linting:**
- Ruff linter configured with these rule categories:
  - `E` - pycodestyle errors
  - `F` - Pyflakes
  - `I` - isort (import sorting)
  - `N` - pep8-naming
  - `W` - pycodestyle warnings
  - `UP` - pyupgrade
  - `B` - flake8-bugbear
  - `C4` - flake8-comprehensions
  - `SIM` - flake8-simplify
- Google-style docstring convention configured

**Type Checking:**
- MyPy strict mode enforced:
  - `disallow_untyped_defs = true` - all function definitions must be typed
  - `disallow_incomplete_defs = true` - must have complete type information
  - `warn_return_any = true` - warns about `Any` returns
  - `warn_unused_configs = true`
  - `check_untyped_defs = true`
  - External modules exempted: `tree_sitter.*`, `neo4j.*`, `mcp.*`

## Import Organization

**Order:**
1. Standard library imports (`os`, `sys`, `json`, `time`, `logging`, `pathlib`, `typing`)
2. Third-party imports (`neo4j`, `openai`, `tree_sitter`, `dotenv`, `mcp`)
3. Relative imports from `codememory.*` package

**Pattern Example from `src/codememory/cli.py`:**
```python
from dotenv import load_dotenv

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import neo4j

from codememory.ingestion.git_graph import GitGraphIngestor
from codememory.ingestion.graph import KnowledgeGraphBuilder
from codememory.config import Config, find_repo_root, DEFAULT_CONFIG
```

**Path Aliases:**
- No aliases configured; use relative imports from `codememory.*` package
- Imports use full module paths: `from codememory.ingestion.graph import KnowledgeGraphBuilder`

## Error Handling

**Patterns:**
- Specific exception types caught, never bare `except:` clauses
- Multiple exception types grouped: `except (json.JSONDecodeError, IOError) as e:`
- Errors logged with context: `logger.error(f"Failed to load config from {self.config_file}: {e}")`
- Re-raise with context: `raise RuntimeError(f"Failed to load config from {self.config_file}: {e}")`
- Custom exception patterns for specific domains (e.g., `neo4j.exceptions.ServiceUnavailable`)

**Circuit Breaker Pattern:**
- Implemented in `src/codememory/ingestion/graph.py` for Neo4j connection resilience
- Tracks failure state (CLOSED, OPEN, HALF_OPEN)
- Auto-recovers after timeout period

**Retry Decorator:**
- Implemented `retry_on_openai_error` decorator for API resilience
- Exponential backoff with configurable retries and delay
- Logs each attempt and final failure

## Logging

**Framework:** Python's built-in `logging` module

**Initialization Pattern:**
```python
import logging

logger = logging.getLogger(__name__)
```

**Patterns:**
- Log level hierarchy observed:
  - `logger.info()` - major operation checkpoints and status updates
  - `logger.warning()` - recoverable issues and fallback behavior
  - `logger.error()` - failures and exceptions
  - `logger.debug()` - detailed diagnostic information
- Use emoji indicators for status in info logs: "🚀", "✅", "🧹", "🧠", "🕸️"
- Provide context in every log: `logger.info(f"✅ [Pass 1] Processed {count} new/modified files.")`
- Suppress noisy external libraries: `logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)`

**Example from `src/codememory/ingestion/graph.py`:**
```python
logger.info("📂 [Pass 1] Scanning Directory Structure...")
logger.warning(f"⚠️ Failed to parse Python imports: {e}")
logger.error(f"Circuit breaker OPENED after {self.failure_count} failures")
```

## Comments

**When to Comment:**
- Docstrings required for all public classes and functions
- Explain "why" not "what" - code should be self-documenting for "what"
- Document complex algorithms and non-obvious intent
- No inline comments for simple, self-explanatory code

**Docstring Style:** Google-style docstrings (configured via `tool.ruff.pydocstyle`)

**Example from `src/codememory/config.py`:**
```python
def __init__(self, repo_root: Path):
    """
    Initialize config for a repository.

    Args:
        repo_root: Path to the repository root
    """
    self.repo_root = repo_root
    self.config_dir = repo_root / ".codememory"
```

**JSDoc/TSDoc:**
- Not applicable for Python codebase

## Function Design

**Size:** Functions kept concise; complex operations broken into helper methods prefixed with `_`

**Parameters:**
- Limit to 3-5 parameters typically
- Use dataclass or dict for related parameter groups
- Type hints mandatory for all parameters
- Default values used sparingly and documented

**Return Values:**
- Explicit return type hints on all functions
- Return `Optional[Type]` for nullable returns
- Return dicts for multiple related values: `Dict[str, Any]`
- Never implicit `None` returns; make return type explicit

**Example from `src/codememory/ingestion/graph.py`:**
```python
def get_embedding(self, text: str) -> List[float]:
    """Generate embedding vector for text."""
    # Implementation
    return embedding
```

## Module Design

**Exports:**
- Public API defined implicitly (functions/classes not prefixed with `_`)
- No `__all__` used; rely on naming convention
- Modules designed for single responsibility

**Organization Pattern:**
- `src/codememory/` - core package
- `src/codememory/ingestion/` - graph building and file parsing
- `src/codememory/server/` - MCP server and tools
- Each module imports only what it needs (no star imports)

## Context Managers

**Pattern:**
- Used extensively with Neo4j sessions and file operations
- Example from tests: `with patch(...): ...`
- Database connections use: `with self.driver.session() as session:`

## Decorators

**Patterns Observed:**
- `@wraps` from `functools` for wrapper functions preserving metadata
- `@pytest.fixture` for test fixtures
- `@pytest.mark.unit`, `@pytest.mark.integration` for test categorization
- `@mcp.tool()` for MCP server tool registration (in `src/codememory/server/app.py`)
- Custom decorators: `@rate_limit`, `@log_tool_call`, `@retry_on_openai_error`

## Constants & Configuration

**Pattern:**
- Global defaults defined at module level: `DEFAULT_CONFIG` dictionary
- Environment variables used for overrides with `os.getenv()`
- Priority hierarchy: env vars > config file > defaults
- Configuration managed through `Config` class in `src/codememory/config.py`

---

*Convention analysis: 2026-03-20*
