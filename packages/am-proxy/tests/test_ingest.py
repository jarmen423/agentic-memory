"""Unit tests for IngestClient fire-and-forget behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from am_proxy.config import ProxyConfig
from am_proxy.ingest import IngestClient


async def test_fire_and_forget_adds_task_to_pending(test_config: ProxyConfig) -> None:
    """Task is added to _pending set before completion (GC safety)."""
    client = IngestClient(test_config)
    with patch.object(IngestClient, "_post", new_callable=AsyncMock):
        client.fire_and_forget({"role": "user", "content": "hello"})
        # Task is in _pending immediately after scheduling
        assert len(client._pending) == 1
    # After awaiting all tasks, _pending is empty
    await asyncio.gather(*list(client._pending))
    # _pending may or may not be empty depending on timing — just assert no exception


async def test_fire_and_forget_task_removed_after_completion(test_config: ProxyConfig) -> None:
    """Task is removed from _pending after it completes."""
    client = IngestClient(test_config)
    with patch.object(IngestClient, "_post", new_callable=AsyncMock) as mock_post:
        client.fire_and_forget({"role": "user", "content": "hello"})
        # Give the event loop a chance to run the task
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        mock_post.assert_awaited_once()
    # After task completes, _pending should be empty
    assert len(client._pending) == 0


async def test_post_sends_correct_payload(test_config: ProxyConfig) -> None:
    """_post sends turn dict as JSON to /ingest/conversation."""
    client = IngestClient(test_config)
    turn = {
        "role": "user",
        "content": "test message",
        "session_id": "sess-001",
        "project_id": "proj-001",
        "turn_index": 0,
        "source_key": "chat_proxy",
        "ingestion_mode": "passive",
    }
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await client._post(turn)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args
        assert "/ingest/conversation" in call_args.args[0]
        assert call_args.kwargs["json"] == turn
        assert "Bearer test-api-key" in call_args.kwargs["headers"]["Authorization"]


async def test_post_swallows_http_exception(test_config: ProxyConfig) -> None:
    """_post never raises — exceptions are silently swallowed."""
    client = IngestClient(test_config)
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("connection refused")
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        # Must not raise
        await client._post({"role": "user", "content": "x"})


async def test_post_swallows_network_timeout(test_config: ProxyConfig) -> None:
    """_post swallows timeouts without raising."""
    import httpx

    client = IngestClient(test_config)
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await client._post({"role": "user", "content": "x"})
