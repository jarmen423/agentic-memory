# Contributing Guide

Thank you for your interest in contributing to Agentic Memory! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Code Style Guidelines](#code-style-guidelines)
- [Testing Approach](#testing-approach)
- [Pull Request Process](#pull-request-process)
- [Feature Contribution Ideas](#feature-contribution-ideas)

---

## Code of Conduct

### Our Pledge

We are committed to making participation in this project a harassment-free experience for everyone, regardless of level of experience, gender, gender identity and expression, sexual orientation, disability, personal appearance, body size, race, ethnicity, age, religion, or nationality.

### Our Standards

**Positive behavior includes:**
- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behavior includes:**
- Sexualized language or imagery
- Trolling or insulting/derogatory comments
- Personal or political attacks
- Public or private harassment
- Publishing others' private information without explicit permission

### Reporting Issues

If you experience or witness unacceptable behavior, please contact the project maintainers privately.

---

## Development Setup

### Prerequisites

- Python 3.10+
- Neo4j 5.18+ (Docker recommended)
- OpenAI API key (for testing embeddings)
- Git

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/yourusername/agentic-memory.git
cd agentic-memory

# Add upstream remote
git remote add upstream https://github.com/original-owner/agentic-memory.git
```

### 2. Create Virtual Environment

```bash
# Create venv
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### 3. Install Development Dependencies

```bash
# Install in editable mode
pip install -e .

# Install development tools (when tests exist)
pip install pytest pytest-cov mypy ruff black
```

### 4. Start Neo4j

```bash
# Using Docker Compose
docker-compose up -d neo4j

# Verify
docker ps | grep neo4j
```

### 5. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit with your values
# - NEO4J_URI=bolt://localhost:7687
# - NEO4J_USER=neo4j
# - NEO4J_PASSWORD=password
# - OPENAI_API_KEY=sk-...
```

### 6. Verify Installation

```bash
# Run help command
codememory --help

# Test in a sample repository
cd /path/to/test/repo
codememory init
codememory status
```

### 7. Create Development Branch

```bash
# Sync with upstream
git fetch upstream
git checkout main
git merge upstream/main

# Create feature branch
git checkout -b feature/your-feature-name
```

---

## Code Style Guidelines

### Python Style Guide

We follow **PEP 8** with some modifications.

#### Formatting

Use **Black** for code formatting:

```bash
# Install Black
pip install black

# Format code
black src/codememory

# Check without modifying
black --check src/codememory
```

**Line length:** 100 characters (Black default)

#### Type Hints

Use type hints for all public functions:

```python
from typing import List, Dict, Optional

def semantic_search(
    self,
    query: str,
    limit: int = 5
) -> List[Dict[str, any]]:
    """Perform semantic search."""
    ...
```

**We recommend but don't require:**
- `mypy` for static type checking
- `strict` mode for new code

#### Docstrings

Use **Google-style docstrings**:

```python
def identify_impact(
    self,
    file_path: str,
    max_depth: int = 3
) -> Dict[str, List[Dict]]:
    """Identify the blast radius of changes to a file.

    Args:
        file_path: Relative path to the file
        max_depth: Maximum depth to traverse for transitive dependencies

    Returns:
        Dict with 'affected_files' list containing path, depth, and impact_type

    Raises:
        FileNotFoundError: If file_path not found in graph

    Example:
        >>> impact = builder.identify_impact("src/models/user.py")
        >>> print(impact['total_count'])
        8
    """
```

#### Imports

**Order:**
1. Standard library
2. Third-party imports
3. Local imports

**Example:**
```python
# Standard library
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional

# Third-party
import neo4j
from openai import OpenAI
from tree_sitter import Language, Parser

# Local
from codememory.config import Config
from codememory.ingestion.graph import KnowledgeGraphBuilder
```

**Avoid:**
```python
from module import *  # ❌ Don't use wildcard imports
```

#### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Variables | snake_case | `user_name`, `file_path` |
| Functions | snake_case | `get_embedding()`, `parse_file()` |
| Classes | PascalCase | `KnowledgeGraphBuilder`, `Config` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRIES`, `DEFAULT_PORT` |
| Private methods | _leading_underscore | `_internal_method()` |

#### Error Handling

**Be specific with exceptions:**

```python
# Good
try:
    result = session.run(query)
except neo4j.ServiceUnavailable as e:
    logger.error(f"Neo4j connection failed: {e}")
    raise RuntimeError("Cannot connect to Neo4j") from e

# Avoid
try:
    result = session.run(query)
except Exception:  # ❌ Too broad
    pass
```

**Use context managers:**

```python
# Good
with self.driver.session() as session:
    result = session.run(query)

# Avoid
session = self.driver.session()
result = session.run(query)
session.close()
```

#### Logging

Use the `logging` module (no `print()` in production code):

```python
import logging

logger = logging.getLogger(__name__)

# Usage
logger.info("Processing file: %s", file_path)
logger.warning("File not found: %s", file_path)
logger.error("Failed to connect: %s", error)
logger.debug("Parsing AST node: %s", node.type)
```

**Log levels:**
- `DEBUG` - Detailed diagnostic information
- `INFO` - General informational messages
- `WARNING` - Something unexpected but recoverable
- `ERROR` - Error occurred, operation failed
- `CRITICAL` - Serious error, program may crash

---

## Testing Approach

### Current Status

**Note:** Agentic Memory does not yet have automated tests. This is a known limitation and priority for v1.0.

### Manual Testing

For now, we rely on manual testing:

1. **CLI Testing:**
```bash
cd /path/to/test/repo
codememory init
codememory index
codememory status
codememory search "test query"
```

2. **MCP Server Testing:**
```bash
codememory serve

# In another terminal
curl http://localhost:8000/tools/search_codebase \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "limit": 1}'
```

3. **Parser Testing:**
```bash
python debug_extraction.py /path/to/test/file.py
```

### Future Test Structure (Planned)

```python
# tests/test_graph_builder.py
import pytest
from codememory.ingestion.graph import KnowledgeGraphBuilder

@pytest.fixture
def builder():
    return KnowledgeGraphBuilder(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="test",
        openai_key="test-key",
        repo_root=Path("/tmp/test")
    )

def test_setup_database(builder):
    """Test database constraint creation."""
    builder.setup_database()
    # Verify constraints exist
    ...

def test_semantic_search(builder):
    """Test vector similarity search."""
    results = builder.semantic_search("test query")
    assert len(results) > 0
    assert "score" in results[0]
```

### Test Coverage Goals

**Target:** 70%+ code coverage before v1.0

**Priority areas:**
1. Parser accuracy (tree-sitter extraction)
2. Cypher query generation
3. MCP tool responses
4. Configuration loading

### Writing Tests (When Ready)

```bash
# Install pytest
pip install pytest pytest-cov

# Run all tests
pytest

# Run with coverage
pytest --cov=src/codememory --cov-report=html

# Run specific test file
pytest tests/test_graph_builder.py

# Run with verbose output
pytest -v
```

---

## Pull Request Process

### 1. Before Creating a PR

**Ensure:**
- [ ] Code follows style guidelines (run `black`)
- [ ] All tests pass (when tests exist)
- [ ] Documentation is updated (if applicable)
- [ ] Commit messages are clear
- [ ] Branch is up-to-date with main

**Update documentation:**
- **API changes:** Update `docs/API.md`
- **New features:** Update `README.md`
- **Bug fixes:** Update `docs/INSTALLATION.md` troubleshooting section

### 2. Commit Message Guidelines

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation change
- `style` - Code style change (formatting, etc.)
- `refactor` - Code refactoring
- `test` - Adding or updating tests
- `chore` - Maintenance tasks

**Example:**
```
feat(ingestion): Add support for Go language

- Install tree-sitter-go binding
- Add Go-specific Tree-sitter queries
- Update documentation with Go examples

Closes #123
```

### 3. Create Pull Request

**Title:** Summarize changes
```
feat(ingestion): Add support for Go language
```

**Description template:**
```markdown
## Summary
Brief description of changes.

## Changes
- Added Go language support
- Updated docs
- Fixed minor bug in parser

## Testing
Tested with sample Go repository.

## Checklist
- [x] Code follows style guidelines
- [x] Documentation updated
- [x] All tests pass
```

### 4. PR Review Process

**What happens:**
1. Automated checks (CI) run
2. Maintainer reviews code
3. Feedback requested if needed
4. Changes addressed
5. Approval and merge

**Timeline:**
- Expect response within 3-5 days
- Follow up politely if no response after 1 week

### 5. Addressing Feedback

**Common requests:**
- "Add tests for this function"
- "Clarify this docstring"
- "Split this into smaller functions"
- "Add error handling for edge case"

**How to respond:**
1. Make requested changes
2. Push to same branch
3. Comment on PR with "Updated, please review again"

### 6. Merge

**After approval:**
- Maintainer squashes and merges to main
- Your branch is deleted
- You're credited in commit

---

## Feature Contribution Ideas

Looking for something to work on? Here are some ideas:

### High Priority

#### 1. Add Test Suite

**Difficulty:** High
**Impact:** Critical

- Write unit tests for parser
- Add integration tests with test Neo4j instance
- Mock OpenAI API for unit tests
- Set up CI/CD pipeline

**Files to modify:**
- Create `tests/` directory
- Add `pytest.ini`, `.github/workflows/tests.yml`

---

#### 2. Additional Language Support

**Difficulty:** Medium
**Impact:** High

Add support for new languages:

- Go
- Rust
- Java
- C/C++
- Ruby

**Implementation:**
```python
# In _init_parsers()
go_lang = Language(tree_sitter_go.language())
parsers[".go"] = Parser(go_lang)

# Add queries
if extension == ".go":
    query_scm = """
    (function_declaration name: (identifier) @name) @function
    ...
    """
```

**Files to modify:**
- `src/codememory/ingestion/graph.py`
- `docs/INSTALLATION.md` (document new support)

---

#### 3. Improved Import Resolution

**Difficulty:** Medium
**Impact:** Medium

**Current:** Fuzzy matching with `CONTAINS`

**Improvement:** Use Python's module resolution

```python
import importlib.util
import sys

def resolve_import(module_name: str, repo_root: Path) -> Optional[Path]:
    """Resolve Python import to file path."""
    spec = importlib.util.find_spec(module_name)
    if spec and spec.origin:
        return Path(spec.origin)
    return None
```

**Files to modify:**
- `src/codememory/ingestion/graph.py` (Pass 3)

---

### Medium Priority

#### 4. Progress Bars for Ingestion

**Difficulty:** Low
**Impact:** Medium

Add progress bars using `tqdm` or `rich`:

```python
from tqdm import tqdm

for i, file in enumerate(tqdm(files)):
    process_file(file)
```

**Files to modify:**
- `src/codememory/ingestion/graph.py`
- `pyproject.toml` (add dependency)

---

#### 5. Retry Logic for OpenAI API

**Difficulty:** Low
**Impact:** Medium

Add retry with exponential backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def get_embedding(self, text: str) -> List[float]:
    response = self.openai_client.embeddings.create(...)
    return response.data[0].embedding
```

**Files to modify:**
- `src/codememory/ingestion/graph.py`
- `requirements.txt` (add `tenacity`)

---

#### 6. Configuration Validation

**Difficulty:** Low
**Impact:** Medium

Validate config file on load:

```python
def validate_config(config: Dict) -> List[str]:
    """Validate configuration and return errors."""
    errors = []

    if not config.get("neo4j", {}).get("uri"):
        errors.append("neo4j.uri is required")

    if not config.get("indexing", {}).get("extensions"):
        errors.append("indexing.extensions must not be empty")

    return errors
```

**Files to modify:**
- `src/codememory/config.py`

---

### Low Priority

#### 7. CLI Auto-completion

**Difficulty:** Medium
**Impact:** Low

Add shell completion for commands:

```bash
codememory <TAB>  # Show: init, status, index, watch, serve, search
codememory search <TAB>  # Show previous queries
```

**Tools to use:**
- `argparse` with `argcomplete`
- Or `click` instead of `argparse`

---

#### 8. Export Graph to JSON

**Difficulty:** Low
**Impact:** Low

Add command to export graph:

```bash
codememory export graph.json
```

**Implementation:**
```python
def export_graph(output_path: Path):
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN n")
        nodes = [dict(record["n"]) for record in result]
        # Write to JSON
```

**Files to modify:**
- `src/codememory/cli.py` (add export command)
- `src/codememory/ingestion/graph.py` (add export method)

---

## Questions?

### Getting Help

1. **Read documentation:**
   - [INSTALLATION.md](docs/INSTALLATION.md)
   - [ARCHITECTURE.md](docs/ARCHITECTURE.md)
   - [API.md](docs/API.md)

2. **Check existing issues:**
   - GitHub Issues: https://github.com/yourusername/agentic-memory/issues

3. **Start a discussion:**
   - GitHub Discussions: https://github.com/yourusername/agentic-memory/discussions

4. **Contact maintainers:**
   - Create an issue with "question" label

### Reporting Bugs

When reporting bugs, include:

1. **Environment:**
   - OS and version
   - Python version
   - Neo4j version

2. **Steps to reproduce:**
   ```bash
   # Commands you ran
   codememory init
   # ...
   ```

3. **Expected vs actual behavior:**
   - What you expected to happen
   - What actually happened

4. **Logs:**
   ```bash
   # Run with debug logging
   LOG_LEVEL=DEBUG codememory index
   ```

5. **Minimal reproduction:**
   - Smallest code snippet that reproduces the issue

---

## Recognition

Contributors will be:
- Listed in `CONTRIBUTORS.md`
- Credited in release notes
- Mentioned in relevant documentation

Thank you for contributing to Agentic Memory!

---

**Contributor License Agreement (CLA):**

By contributing, you agree that your contributions will be licensed under the MIT License (same as the project).
