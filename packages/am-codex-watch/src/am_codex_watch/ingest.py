"""HTTP client posting turns to am-server."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from am_codex_watch.config import WatchConfig

logger = logging.getLogger(__name__)


def post_turn(config: WatchConfig, body: dict[str, Any]) -> bool:
    """POST one turn to ``/ingest/conversation``. Returns True on HTTP 2xx."""
    url = f"{config.endpoint.rstrip('/')}/ingest/conversation"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    try:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            r = client.post(url, json=body, headers=headers)
            if config.debug:
                logger.info("ingest %s %s", r.status_code, url)
            return 200 <= r.status_code < 300
    except Exception as exc:
        if config.debug:
            logger.warning("ingest failed: %s", exc)
        return False


def build_turn_payload(
    *,
    config: WatchConfig,
    source_key: str,
    source_agent: str,
    session_id: str,
    turn_index: int,
    role: str,
    content: str,
    timestamp: str | None,
) -> dict[str, Any]:
    """Build ``ConversationIngestRequest``-compatible dict."""
    payload: dict[str, Any] = {
        "role": role,
        "content": content,
        "session_id": session_id,
        "turn_index": turn_index,
        "source_key": source_key,
        "source_agent": source_agent,
        "ingestion_mode": "passive",
    }
    if config.default_project_id is not None:
        payload["project_id"] = config.default_project_id
    if timestamp:
        payload["timestamp"] = timestamp
    return payload
