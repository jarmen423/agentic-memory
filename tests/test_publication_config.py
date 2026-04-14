"""Tests for deploy-time publication URL configuration."""

from __future__ import annotations

from fastapi.testclient import TestClient

from am_server.app import create_app
from am_server.publication_config import MCP_OPENAI_PATH, PUBLICATION_PRIVACY_PATH, absolute_public_url


def test_absolute_public_url_returns_relative_path_when_base_url_unset(monkeypatch):
    """Local environments should not require a fake public hostname."""

    monkeypatch.delenv("AM_PUBLIC_BASE_URL", raising=False)

    assert absolute_public_url(PUBLICATION_PRIVACY_PATH) == "/publication/privacy"


def test_absolute_public_url_uses_configured_public_base_url(monkeypatch):
    """Hosted deployments should advertise absolute reviewer-facing URLs."""

    monkeypatch.setenv("AM_PUBLIC_BASE_URL", "https://mcp.example.com/")

    assert absolute_public_url(MCP_OPENAI_PATH) == "https://mcp.example.com/mcp-openai"


def test_publication_overview_uses_absolute_urls_when_public_base_url_is_set(monkeypatch):
    """Publication HTML should reflect the externally reachable review endpoints."""

    monkeypatch.setenv("AM_PUBLIC_BASE_URL", "https://mcp.example.com")
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get("/publication/agentic-memory")

    assert response.status_code == 200
    assert "https://mcp.example.com/mcp-openai" in response.text
    assert "https://mcp.example.com/publication/privacy" in response.text
