# Testing Patterns

**Analysis Date:** 2026-03-20

## Test Framework

**Runner:**
- pytest 7.0.0+
- Config: `pyproject.toml` with `[tool.pytest.ini_options]`

**Test Discovery:**
- Python files: `test_*.py` or `*_test.py`
- Test classes: `Test*`
- Test functions: `test_*`

**Assertion Library:**
- pytest built-in assertions with no external library

**Run Commands:**
```bash
pytest                      # Run all tests
pytest tests/test_cli.py   # Run specific file
pytest -k "test_status"    # Run tests matching pattern
pytest --cov              # Run with coverage
pytest -m unit            # Run tests with 'unit' marker
pytest -m integration     # Run integration tests (requires Neo4j)
pytest -v                 # Verbose output
pytest --tb=short         # Shorter traceback format
```

## Test File Organization

**Location:**
- Tests co-located in `tests/` directory at project root
- Structure mirrors source: `src/codememory/ingestion/graph.py` ↔ `tests/test_graph.py`
- Conftest patterns defined in `tests/conftest.py`

**Naming Convention:**
- `test_cli.py` - CLI command tests
- `test_graph.py` - KnowledgeGraphBuilder tests
- `test_parser.py` - CodeParser tests
- `test_git_graph.py` - GitGraphIngestor tests
- `test_server.py` - MCP server and tools tests

## Test Structure

**Suite Organization:**
```python
# From tests/test_graph.py
class TestKnowledgeGraphBuilder:
    """Test suite for KnowledgeGraphBuilder."""

    @pytest.fixture
    def mock_driver(self):
        """Create a mock Neo4j driver."""
        driver = Mock()
        session = Mock()
        driver.session.return_value.__enter__ = Mock(return_value=session)
        driver.session.return_value.__exit__ = Mock(return_value=False)
        return driver, session

    @pytest.fixture
    def builder(self, mock_driver):
        """Create a KnowledgeGraphBuilder with mocked dependencies."""
        driver, session = mock_driver
        with patch('neo4j.GraphDatabase.driver', return_value=driver), \
             patch.object(KnowledgeGraphBuilder, '_init_parsers'), \
             patch('codememory.ingestion.graph.OpenAI'):

            builder = KnowledgeGraphBuilder(
                uri="bolt://localhost:7687",
                user="neo4j",
                password="test",
                openai_key="sk-test"
            )
            builder.driver = driver
            return builder

    def test_initialization(self, builder):
        """Test that builder initializes correctly."""
        assert builder.EMBEDDING_MODEL == "text-embedding-3-large"
        assert builder.driver is not None
```

**Patterns:**
- Classes group related tests using `class Test*:` convention
- Fixtures with `@pytest.fixture` provide test dependencies
- Fixtures accept other fixtures as parameters for composition
- Each test method focuses on single behavior (single assert or related assertions)

## Mocking

**Framework:** `unittest.mock` with `Mock`, `patch`, `MagicMock`

**Mocking Strategy:**
- Mock external dependencies: Neo4j driver, OpenAI API, file I/O
- Avoid mocking internal implementations; test real code paths
- Use `patch()` for module-level replacements, `patch.object()` for method-level

**Pattern Examples:**

**Mock Neo4j Driver:**
```python
mock_driver = Mock()
session = Mock()
mock_driver.session.return_value.__enter__ = Mock(return_value=session)
mock_driver.session.return_value.__exit__ = Mock(return_value=False)
```

**Mock Configuration:**
```python
def _mock_config(
    *,
    exists=True,
    openai_key="test-openai-key",
    indexing=None,
    git_config=None,
):
    """Create a mock Config object for CLI tests."""
    config = Mock()
    config.exists.return_value = exists
    config.config_file = Path("/tmp/repo/.codememory/config.json")
    config.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    # ... more configuration
    return config
```

**Patch in Context:**
```python
with patch('neo4j.GraphDatabase.driver', return_value=driver), \
     patch.object(KnowledgeGraphBuilder, '_init_parsers'), \
     patch('codememory.ingestion.graph.OpenAI'):
    # Test code
```

**What to Mock:**
- External API clients (OpenAI, Neo4j)
- File system operations
- Database connections
- Third-party services

**What NOT to Mock:**
- Core business logic (parsers, graph builders)
- Configuration management
- Logging
- Internal helper methods

## Fixtures and Factories

**Test Data Patterns:**

**Mock Builder Factory:**
```python
@pytest.fixture
def builder(self, mock_driver):
    """Create a KnowledgeGraphBuilder with mocked dependencies."""
    from codememory.ingestion.graph import KnowledgeGraphBuilder

    driver, session = mock_driver
    with patch('neo4j.GraphDatabase.driver', return_value=driver), \
         patch.object(KnowledgeGraphBuilder, '_init_parsers'), \
         patch('codememory.ingestion.graph.OpenAI'):

        builder = KnowledgeGraphBuilder(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="test",
            openai_key="sk-test"
        )
        builder.driver = driver
        return builder
```

**Mock Result Builder:**
```python
def _result(payload):
    """Build a mock Neo4j result object with a single() payload."""
    result = Mock()
    result.single.return_value = payload
    return result
```

**Mock Config Factory:**
```python
def _mock_config(
    *,
    exists=True,
    openai_key="test-openai-key",
    indexing=None,
    git_config=None,
):
    """Create a mock Config object for CLI tests."""
    config = Mock()
    config.exists.return_value = exists
    # ... setup config
    return config
```

**Location:**
- Fixtures defined within test classes or at module level in test files
- Helper functions (like `_mock_config`, `_result`) defined as module-level functions in test files
- `conftest.py` used for shared fixtures across multiple test files

## Test Markers

**Markers Configured:**
- `@pytest.mark.unit` - Unit tests (default, requires no external services)
- `@pytest.mark.integration` - Integration tests (requires Neo4j and other services)
- `@pytest.mark.slow` - Slow-running tests

**Usage:**
```python
pytestmark = [pytest.mark.unit]  # All tests in module are unit tests

@pytest.mark.integration
class TestDatabaseIntegration:
    """Integration tests requiring Neo4j."""
    pass

@pytest.mark.slow
def test_expensive_operation():
    """This test takes significant time."""
    pass
```

## Coverage

**Requirements:** 70% minimum (configured `fail_under = 70` in `pyproject.toml`)

**Configuration:**
```toml
[tool.coverage.run]
source = ["src/codememory"]
omit = ["*/tests/*", "*/__pycache__/*"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if self.debug:",
    "if settings.DEBUG",
    "raise AssertionError",
    "raise NotImplementedError",
    "if 0:",
    "if __name__ == .__main__.:",
    "class .*\\bProtocol\\):",
    "@(abc\\.)?abstractmethod",
]
fail_under = 70
```

**View Coverage:**
```bash
pytest --cov=src/codememory --cov-report=html
# Opens htmlcov/index.html in browser
```

## Test Types

**Unit Tests:**
- Scope: Individual classes and functions in isolation
- Approach: Mock all external dependencies, test single responsibility
- Location: `tests/test_*.py` marked with `@pytest.mark.unit`
- Examples: `test_initialization()`, `test_get_embedding()`, `test_extract_js_classes()`

**Integration Tests:**
- Scope: Multiple components working together
- Approach: Real Neo4j driver (requires live database) or mocked for CI
- Location: Marked with `@pytest.mark.integration` in same files
- Examples: `test_setup_database_integration()`, `test_sync_updates_checkpoint_after_incremental_path()`
- Run with: `pytest -m integration`

**E2E Tests:**
- Framework: Not used in this codebase
- CLI testing uses subprocess approach via mocks of actual command handlers

## Common Patterns

**Async Testing:**
- Not applicable; codebase uses synchronous patterns with asyncio support optional
- `pytest-asyncio>=0.21.0` available as dev dependency but not currently used

**Error Testing:**
```python
def test_get_embedding_error_handling(self, builder):
    """Test unexpected embedding errors propagate."""
    builder.openai_client = Mock()
    builder.openai_client.embeddings.create.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        builder.get_embedding("test text")
```

**JSON Output Validation (CLI):**
```python
def test_status_json_success_envelope(monkeypatch, capsys, tmp_path):
    """Status command emits deterministic JSON envelope on success."""
    # Setup mocks
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))

    # Execute
    cli.cmd_status(argparse.Namespace(json=True))

    # Verify
    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
```

**Helper Function Pattern:**
```python
def _parse_json_stdout(capsys):
    """Parse JSON output from stdout."""
    stdout = capsys.readouterr().out.strip()
    assert stdout, "expected JSON on stdout"
    return json.loads(stdout)
```

**Monkeypatch for Dependency Injection:**
```python
def test_example(monkeypatch, tmp_path):
    """Demonstrate monkeypatch for injectable dependencies."""
    mock_config = _mock_config(exists=True)

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=tmp_path))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_config))
```

## Test Execution

**Configuration in `pyproject.toml`:**
```toml
[tool.pytest.ini_options]
minversion = "7.0"
addopts = "-ra -q --strict-markers --tb=short"
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "integration: marks tests as integration tests (requires Neo4j)",
    "slow: marks tests as slow",
    "unit: marks tests as unit tests",
]
```

**Key Flags:**
- `-ra` - Show summary of all test outcomes
- `-q` - Quiet mode (minimal output)
- `--strict-markers` - Fail on unknown markers
- `--tb=short` - Short traceback format

---

*Testing analysis: 2026-03-20*
