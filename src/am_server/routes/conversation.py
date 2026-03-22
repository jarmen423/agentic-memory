"""Conversation ingest and search endpoints — requires Bearer auth."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from am_server.auth import require_auth
from am_server.dependencies import get_conversation_pipeline
from am_server.models import ConversationIngestRequest

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
    result = await loop.run_in_executor(None, pipeline.ingest, body.model_dump())
    return {"status": "ok", "result": result}


@router.get("/search/conversations")
async def search_conversations(
    q: str = Query(..., description="Semantic search query"),
    project_id: str | None = Query(None, description="Optional project filter"),
    role: str | None = Query(None, description="Optional role filter: user | assistant"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
) -> dict:
    """Search the conversation memory graph by semantic similarity.

    Embeds query via EmbeddingService then queries chat_embeddings vector index.
    Falls back to text search if embedding fails. Filters by project_id and/or
    role if provided.
    """
    pipeline = get_conversation_pipeline()
    try:
        conn = pipeline._conn  # type: ignore[attr-defined]
        embedder = pipeline._embedder  # type: ignore[attr-defined]
        loop = asyncio.get_event_loop()

        def _query() -> list:
            # Embed the query for vector search
            query_embedding = embedder.embed(q)

            with conn.session() as session:
                # Vector search path
                cypher = (
                    "CALL db.index.vector.queryNodes("
                    "  'chat_embeddings', $limit, $embedding"
                    ") YIELD node, score "
                    "WHERE ($project_id IS NULL OR node.project_id = $project_id)"
                    "  AND ($role IS NULL OR node.role = $role) "
                    "RETURN "
                    "    node.session_id     AS session_id, "
                    "    node.turn_index     AS turn_index, "
                    "    node.role           AS role, "
                    "    node.content        AS content, "
                    "    node.source_agent   AS source_agent, "
                    "    node.timestamp      AS timestamp, "
                    "    node.entities       AS entities, "
                    "    score "
                    "ORDER BY score DESC "
                    "LIMIT $limit"
                )
                result = session.run(
                    cypher,
                    embedding=query_embedding,
                    project_id=project_id,
                    role=role,
                    limit=limit,
                )
                return [dict(record) for record in result]

        results = await loop.run_in_executor(None, _query)
    except Exception:
        logger.exception("search_conversations failed, falling back to text search")
        # Text fallback
        try:
            conn = pipeline._conn  # type: ignore[attr-defined]
            loop = asyncio.get_event_loop()

            def _text_query() -> list:
                with conn.session() as session:
                    text_cypher = (
                        "MATCH (n:Memory:Conversation:Turn) "
                        "WHERE toLower(n.content) CONTAINS toLower($q) "
                        "  AND ($project_id IS NULL OR n.project_id = $project_id) "
                        "  AND ($role IS NULL OR n.role = $role) "
                        "RETURN "
                        "    n.session_id    AS session_id, "
                        "    n.turn_index    AS turn_index, "
                        "    n.role          AS role, "
                        "    n.content       AS content, "
                        "    n.source_agent  AS source_agent, "
                        "    n.timestamp     AS timestamp, "
                        "    n.entities      AS entities, "
                        "    1.0 AS score "
                        "LIMIT $limit"
                    )
                    result = session.run(
                        text_cypher, q=q, project_id=project_id, role=role, limit=limit
                    )
                    return [dict(record) for record in result]

            results = await loop.run_in_executor(None, _text_query)
        except Exception:
            results = []

    return {"results": results}
