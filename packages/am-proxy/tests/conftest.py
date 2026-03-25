"""Shared pytest fixtures for am-proxy tests."""

from __future__ import annotations

import pytest

from am_proxy.config import ProxyConfig


@pytest.fixture
def test_config() -> ProxyConfig:
    """ProxyConfig with safe test values (no real network calls)."""
    return ProxyConfig(
        endpoint="http://test-server:9999",
        api_key="test-api-key",
        default_project_id="test-project",
        timeout_seconds=1.0,
        buffer_ttl_seconds=10.0,
        debug=False,
    )


@pytest.fixture
def debug_config() -> ProxyConfig:
    """ProxyConfig with debug=True for testing debug code paths."""
    return ProxyConfig(
        endpoint="http://test-server:9999",
        api_key="test-api-key",
        default_project_id="test-project",
        timeout_seconds=1.0,
        buffer_ttl_seconds=10.0,
        debug=True,
    )
