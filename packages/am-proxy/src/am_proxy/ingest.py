"""Fire-and-forget HTTP ingest client for am-proxy.

Posts conversation turns to POST /ingest/conversation on am-server.
All exceptions are swallowed — ingest failure MUST NOT affect the agent session.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from am_proxy.config import ProxyConfig

logger = logging.getLogger(__name__)


class IngestClient:
    """Async HTTP client that posts conversation turns as fire-and-forget tasks.

    Maintains a strong-reference set to prevent GC of in-flight tasks on Python 3.12+.
    (asyncio.create_task() holds only a weak reference — tasks can be GC'd before
    completion if no other reference exists. CPython issue #117379.)
    """

    def __init__(self, config: ProxyConfig) -> None:
        """Initialize IngestClient.

        Args:
            config: ProxyConfig with endpoint, api_key, and timeout_seconds.
        """
        self._config = config
        self._pending: set[asyncio.Task[None]] = set()

    def fire_and_forget(self, turn: dict[str, Any]) -> None:
        """Schedule a POST without awaiting. Safe against GC on Python 3.12+.

        Args:
            turn: Dict matching ConversationIngestRequest schema.
        """
        task = asyncio.create_task(self._post(turn))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _post(self, turn: dict[str, Any]) -> None:
        """POST turn to /ingest/conversation. Never raises.

        Args:
            turn: Dict matching ConversationIngestRequest schema.
        """
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                await client.post(
                    f"{self._config.endpoint}/ingest/conversation",
                    json=turn,
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                )
        except Exception:
            pass  # Silent failure — proxy NEVER surfaces errors to caller
