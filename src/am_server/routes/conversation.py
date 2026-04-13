"""HTTP routes for conversation memory ingest and semantic search.

Registers authenticated endpoints that persist conversation turns to the memory
graph and query them via embedding-backed search. The router applies
``require_auth`` so every handler expects a valid Bearer token.

Typical clients: MCP chat surfaces and proxies that forward turns with a
client-supplied ``session_id`` (never generated server-side).
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import copy_context

from fastapi import APIRouter, Depends, HTTPException, Query

from am_server.auth import require_auth
from am_server.dependencies import get_conversation_pipeline
from am_server.models import ConversationIngestRequest
from agentic_memory.server.tools import search_conversation_turns_sync

logger = logging.getLogger(__name__)

# Auth boundary: Bearer token required for all routes on this router.
router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/ingest/conversation", status_code=202)
async def ingest_conversation(body: ConversationIngestRequest) -> dict:
    """Enqueue ingestion of one conversation turn into the memory graph.

    Runs the blocking ``pipeline.ingest`` in a worker thread while preserving
    ``contextvars`` via ``copy_context``. The client must send ``session_id``;
    the server does not invent one. ``source_key`` defaults suit ``chat_mcp``;
    ``am-proxy`` / ``am-ext`` should pass ``chat_proxy`` or ``chat_ext``.

    Args:
        body: Validated turn payload (``ConversationIngestRequest``).

    Returns:
        Dict with ``status`` ``"ok"`` and pipeline ``result``.

    Raises:
        HTTPException: 422 when ingestion raises ``ValueError`` (invalid input).
    """
    pipeline = get_conversation_pipeline()
    loop = asyncio.get_event_loop()
    try:
        ctx = copy_context()
        result = await loop.run_in_executor(None, lambda: ctx.run(pipeline.ingest, body.model_dump()))
    except ValueError as exc:
        # Validation boundary: pipeline ValueError → HTTP 422 for clients.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@router.get("/search/conversations")
async def search_conversations(
    q: str = Query(..., description="Semantic search query"),
    project_id: str | None = Query(None, description="Optional project filter"),
    role: str | None = Query(None, description="Optional role filter: user | assistant"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
    as_of: str | None = Query(None, description="Optional ISO-8601 temporal cutoff"),
) -> dict:
    """Search conversation turns by semantic similarity (vector + fallback).

    Embeds ``q`` through the pipeline embedding service, queries the
    ``chat_embeddings`` index, and falls back to text search if embedding
    fails. Optional filters narrow results by project, speaker role, or time.

    Args:
        q: Natural-language query string.
        project_id: If set, restrict to this project.
        role: If set, filter to ``"user"`` or ``"assistant"``.
        limit: Maximum number of hits (1–50).
        as_of: Optional ISO-8601 cutoff for temporal queries.

    Returns:
        Dict with key ``results`` (list of hits). On unexpected errors, logs
        and returns an empty ``results`` list without raising.
    """
    pipeline = get_conversation_pipeline()
    try:
        loop = asyncio.get_event_loop()
        ctx = copy_context()

        def _query() -> list:
            return search_conversation_turns_sync(
                pipeline,
                query=q,
                project_id=project_id,
                role=role,
                limit=limit,
                as_of=as_of,
                log_prefix="/search/conversations",
            )

        results = await loop.run_in_executor(None, lambda: ctx.run(_query))
    except Exception:
        logger.exception("search_conversations failed")
        results = []

    return {"results": results}
