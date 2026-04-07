"""Unit tests for ConnectionManager."""

from unittest.mock import MagicMock, call, patch

import pytest

from agentic_memory.core.connection import ConnectionManager


@pytest.mark.unit
def test_init_creates_driver():
    """ConnectionManager.__init__ creates neo4j.GraphDatabase.driver with correct args."""
    with patch("agentic_memory.core.connection.neo4j.GraphDatabase.driver") as mock_driver:
        conn = ConnectionManager("bolt://localhost:7687", "neo4j", "password")
        mock_driver.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "password"),
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
            connection_timeout=30,
            max_transaction_retry_time=30.0,
        )
        assert conn.driver is mock_driver.return_value


@pytest.mark.unit
def test_session_context_manager():
    """conn.session() yields a neo4j session via driver.session()."""
    with patch("agentic_memory.core.connection.neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        conn = ConnectionManager("bolt://localhost:7687", "neo4j", "password")
        with conn.session() as s:
            # session context manager was entered
            assert s is mock_session


@pytest.mark.unit
def test_setup_database_runs_all_queries():
    """setup_database() executes all vector index CREATE statements and entity uniqueness constraint."""
    with patch("agentic_memory.core.connection.neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        conn = ConnectionManager("bolt://localhost:7687", "neo4j", "password")
        conn.setup_database()

        # Collect all executed Cypher strings
        executed = [str(c.args[0]) for c in mock_session.run.call_args_list]
        executed_joined = " ".join(executed)

        assert "code_embeddings" in executed_joined
        assert "research_embeddings" in executed_joined
        assert "chat_embeddings" in executed_joined
        assert "entity_unique" in executed_joined
        assert mock_session.run.call_count == 4


@pytest.mark.unit
def test_close_closes_driver():
    """conn.close() calls driver.close()."""
    with patch("agentic_memory.core.connection.neo4j.GraphDatabase.driver") as mock_driver:
        conn = ConnectionManager("bolt://localhost:7687", "neo4j", "password")
        conn.close()
        mock_driver.return_value.close.assert_called_once()


@pytest.mark.unit
def test_from_config(monkeypatch):
    """ConnectionManager.from_config reads uri/user/password from config dict."""
    # Unset any env vars that might be set by other tests or .env files
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    config = {
        "neo4j": {
            "uri": "bolt://myhost:7687",
            "user": "admin",
            "password": "secret",
        }
    }
    with patch("agentic_memory.core.connection.neo4j.GraphDatabase.driver") as mock_driver:
        conn = ConnectionManager.from_config(config)
        mock_driver.assert_called_once_with(
            "bolt://myhost:7687",
            auth=("admin", "secret"),
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
            connection_timeout=30,
            max_transaction_retry_time=30.0,
        )


@pytest.mark.unit
def test_from_config_env_var_fallback(monkeypatch):
    """from_config uses env vars when they are set, overriding config values."""
    monkeypatch.setenv("NEO4J_URI", "bolt://envhost:7687")
    monkeypatch.setenv("NEO4J_USER", "envuser")
    monkeypatch.setenv("NEO4J_PASSWORD", "envpass")

    config = {
        "neo4j": {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "password",
        }
    }
    with patch("agentic_memory.core.connection.neo4j.GraphDatabase.driver") as mock_driver:
        conn = ConnectionManager.from_config(config)
        mock_driver.assert_called_once_with(
            "bolt://envhost:7687",
            auth=("envuser", "envpass"),
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
            connection_timeout=30,
            max_transaction_retry_time=30.0,
        )
