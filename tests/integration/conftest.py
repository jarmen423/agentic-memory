"""Integration fixtures for full-stack search coverage."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server.app import create_app
from am_server.dependencies import get_conversation_pipeline, get_pipeline


@pytest.fixture(scope="module")
def integration_client():
    """Boot the FastAPI app with auth and deterministic dependency surfaces."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("AM_SERVER_API_KEY", "integration-key")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")

    get_pipeline.cache_clear()
    get_conversation_pipeline.cache_clear()

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    monkeypatch.undo()


@pytest.fixture(scope="module")
def integration_auth_headers() -> dict[str, str]:
    """Valid bearer auth for integration app tests."""
    return {"Authorization": "Bearer integration-key"}


def result_iter(rows):
    """Build a session.run return object that supports iteration."""
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    return result


def result_data(rows):
    """Build a session.run return object that supports .data()."""
    result = MagicMock()
    result.data.return_value = rows
    return result


def result_single(row):
    """Build a session.run return object that supports .single()."""
    result = MagicMock()
    result.single.return_value = row
    return result
