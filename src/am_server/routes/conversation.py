"""Conversation ingest and search endpoints — requires Bearer auth."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from am_server.auth import require_auth
from am_server.dependencies import get_conversation_pipeline
from am_server.models import ConversationIngestRequest
from codememory.server.tools import search_conversation_turns_sync

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/ingest/conversation", status_code=202)
async def ingest_conversation(body: ConversationIngestRequest) -> dict:
    """Ingest a single conversation turn into the memory graph.

    Delegates synchronous pipeline.ingest() to a thread pool executor.
    session_id MUST come from the request body — never generated server-side.
    source_key defaults to 'chat_mcp'; am-proxy should pass 'chat_proxy',
    am-ext should pass 'chat_ext'.
    """
    pipeline = get_conversation_pipeline()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, pipeline.ingest, body.model_dump())
    except ValueError as exc:
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
    """Search the conversation memory graph by semantic similarity.

    Embeds query via EmbeddingService then queries chat_embeddings vector index.
    Falls back to text search if embedding fails. Filters by project_id and/or
    role if provided.
    """
    pipeline = get_conversation_pipeline()
    try:
        loop = asyncio.get_event_loop()

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

        results = await loop.run_in_executor(None, _query)
    except Exception:
        logger.exception("search_conversations failed")
        results = []

    return {"results": results}
