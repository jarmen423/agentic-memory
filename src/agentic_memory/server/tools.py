"""MCP tool registration, conversation/research pipelines, and the code ``Toolkit``.

This module is the main bridge between **Model Context Protocol (MCP) tool handlers**
and Agentic Memory backends (Neo4j, embedding providers, optional temporal graph).
It is organized in three layers:

1. **Private helpers** — ``_vector_conversation_search``,
   ``_text_conversation_search``, ``_fetch_conversation_*``,
   ``search_conversation_turns_sync``, etc. Implement retrieval strategies (vector
   index → optional temporal enrichment → deterministic text fallback) and shared
   hydration logic used by MCP tools and tests.

2. **Registration entrypoints** — ``register_conversation_tools`` and
   ``register_schedule_tools`` attach async handlers to a FastMCP instance at
   server startup. Handlers **offload blocking work** (Neo4j sessions, embedders,
   schedulers) via ``asyncio.get_event_loop().run_in_executor`` so the MCP event
   loop is not blocked.

3. **Toolkit** — Synchronous, framework-agnostic wrappers around
   ``KnowledgeGraphBuilder`` and ``search_code`` that return **Markdown reports**
   for LLM consumption. Used by the internal MCP app and scripts; conversation
   memory is **not** routed through ``Toolkit`` (see registration functions).

Integration:
    Imported by ``agentic_memory.server.app``, which calls ``register_*`` during
    startup and constructs ``Toolkit`` with a shared ``KnowledgeGraphBuilder``.
    Cached helpers ``_get_mcp_conversation_pipeline``,
    ``_get_mcp_research_pipeline``, and ``_get_mcp_research_scheduler`` read
    environment configuration and are **separate** from ``am_server`` process
    singletons when the MCP server runs standalone.

Error paths (conversation tools):
    * Vector search failures in ``search_conversation_turns_sync`` trigger
      structured log event ``conversation_search_fallback`` and fall back to
      substring search; ``as_of`` filtering still applies.
    * Missing temporal bridge, missing seeds, or temporal retrieve errors fall
      back to vector (or text) baselines with the same log event.
    * MCP wrappers ``search_conversations`` and ``get_conversation_context`` log
      errors and return ``[]`` / ``{"turns": []}`` rather than raising.
    * ``add_message`` logs failures and returns ``{"error": "<message>"}``.

Error paths (Toolkit):
    Neo4j ``DatabaseError`` / ``ClientError`` are caught, logged where applicable,
    and surfaced as **error strings** in the returned report (no exceptions to
    the caller).

Error paths (research schedule tools):
    If the scheduler cannot be configured (missing pipeline, keys, etc.), tools
    return JSON strings with ``status: "error"``. ``run_research_session``
    validates inputs before touching the scheduler.

Dependencies:
    Neo4j labels/indexes (e.g. ``Memory:Conversation:Turn``, vector index
    ``chat_embeddings``), ``EmbeddingService`` / ``build_embedding_service``,
    optional ``TemporalBridge``, ``ResearchScheduler`` + Brave Search for web
    schedules.
"""

from collections.abc import Callable
from typing import Any, Dict, List, Optional
import asyncio
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import neo4j
from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from agentic_memory.chat.pipeline import ConversationIngestionPipeline
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.core.entity_extraction import EntityExtractionService
from agentic_memory.core.extraction_llm import resolve_extraction_llm_config
from agentic_memory.core.request_context import get_request_id
from agentic_memory.core.retry import retry_transient
from agentic_memory.core.runtime_embedding import build_embedding_service
from agentic_memory.core.scheduler import ResearchScheduler
from agentic_memory.server.temporal_contract import TemporalRetrievalRequiredError
from agentic_memory.temporal.bridge import get_temporal_bridge
from agentic_memory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
    parse_conversation_source_id,
)
from agentic_memory.web.pipeline import ResearchIngestionPipeline
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from agentic_memory.server.code_search import SAFE_RETRIEVAL_POLICY, search_code
from agentic_memory.server.repo_identity import (
    list_known_project_ids,
    list_known_repo_ids,
    list_project_and_repo_ids_payload,
)
from agentic_memory.server.reranking import (
    build_yaml_card,
    candidate_limit_for_domain,
    rerank_documents,
)

logger = logging.getLogger(__name__)
ToolAnnotationResolver = Callable[[str], ToolAnnotations | None]


def _tool_registration_kwargs(
    tool_name: str,
    description: str,
    annotation_resolver: ToolAnnotationResolver | None,
) -> dict[str, Any]:
    """Build keyword arguments for ``@mcp.tool`` registration.

    Merges the MCP-visible ``name`` and ``description`` with optional
    ``ToolAnnotations`` when ``annotation_resolver`` returns a value. Used so
    the same handler can be registered on multiple MCP apps (internal vs public)
    with different annotation policies without duplicating handler code.

    Args:
        tool_name: Stable MCP tool identifier.
        description: MCP tool description string passed through to clients.
        annotation_resolver: Optional callback ``(name) -> annotations | None``.

    Returns:
        Dict suitable for unpacking into ``FastMCP.tool(...)``.
    """

    kwargs: dict[str, Any] = {
        "name": tool_name,
        "description": description,
    }
    if annotation_resolver is not None:
        annotations = annotation_resolver(tool_name)
        if annotations is not None:
            kwargs["annotations"] = annotations
    return kwargs


def _filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Filter conversation rows to those ingested on or before ``as_of``.

    Compares lexicographically on ISO-8601 ``ingested_at`` strings when ``as_of``
    is set; no-op when ``as_of`` is ``None``.

    Args:
        rows: Turn-shaped dicts containing optional ``ingested_at``.
        as_of: Inclusive upper bound for ``ingested_at``, or ``None``.

    Returns:
        Filtered list (may be shorter than ``rows``).
    """
    if as_of is None:
        return rows
    return [row for row in rows if (row.get("ingested_at") or "") <= as_of]


def _vector_conversation_search(
    conn: ConnectionManager,
    embedder: EmbeddingService,
    *,
    query: str,
    project_id: str | None,
    role: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Run vector retrieval over indexed conversation turns.

    Queries Neo4j index ``chat_embeddings`` via ``db.index.vector.queryNodes`` and
    applies optional ``project_id`` / ``role`` filters.

    Args:
        conn: Shared connection manager for Neo4j sessions.
        embedder: Provider used to embed ``query``.
        query: Natural language query text.
        project_id: If set, restrict to turns for this project.
        role: If set, restrict to this speaker role (e.g. ``user``).
        limit: Maximum rows to return from the index call.

    Returns:
        List of turn dicts plus a ``score`` field from vector similarity.
    """
    query_embedding = embedder.embed(query)
    with conn.session() as session:
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
            "    node.ingested_at    AS ingested_at, "
            "    node.entities       AS entities, "
            "    node.entity_types   AS entity_types, "
            "    score "
            "ORDER BY score DESC "
            "LIMIT $limit"
        )
        return [dict(r) for r in session.run(
            cypher,
            embedding=query_embedding,
            project_id=project_id,
            role=role,
            limit=limit,
        )]


def _text_conversation_search(
    conn: ConnectionManager,
    *,
    query: str,
    project_id: str | None,
    role: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Substring fallback search over conversation content.

    Used when embedding or vector index access fails so callers still get
    deterministic matches. Assigns a constant ``score`` of ``1.0`` (no ranking
    beyond Neo4j row order / limit).

    Args:
        conn: Neo4j connection manager.
        query: Substring matched case-insensitively against ``n.content``.
        project_id: Optional project filter.
        role: Optional role filter.
        limit: Maximum number of turns.

    Returns:
        Matching turn dicts with synthetic ``score``.
    """
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
            "    n.ingested_at   AS ingested_at, "
            "    n.entities      AS entities, "
            "    n.entity_types  AS entity_types, "
            "    1.0 AS score "
            "LIMIT $limit"
        )
        return [dict(record) for record in session.run(
            text_cypher,
            q=query,
            project_id=project_id,
            role=role,
            limit=limit,
        )]


def _fetch_conversation_turn(
    conn: ConnectionManager,
    *,
    session_id: str,
    turn_index: int,
) -> dict[str, Any] | None:
    """Load a single turn by ``session_id`` and ``turn_index``.

    Args:
        conn: Neo4j connection manager.
        session_id: Conversation session identifier.
        turn_index: Zero-based turn index within the session.

    Returns:
        Turn fields as a dict, or ``None`` if no node matches.
    """
    with conn.session() as session:
        result = session.run(
            (
                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id, turn_index: $turn_index}) "
                "RETURN "
                "    t.session_id AS session_id, "
                "    t.turn_index AS turn_index, "
                "    t.role AS role, "
                "    t.content AS content, "
                "    t.source_agent AS source_agent, "
                "    t.timestamp AS timestamp, "
                "    t.ingested_at AS ingested_at, "
                "    t.entities AS entities"
            ),
            session_id=session_id,
            turn_index=turn_index,
        ).single()
    return dict(result) if result else None


def _fetch_conversation_context_window(
    conn: ConnectionManager,
    *,
    session_id: str,
    turn_index: int,
    as_of: str | None,
) -> list[dict[str, Any]]:
    """Fetch neighboring turns at ``turn_index - 1`` and ``turn_index + 1``.

    Used to supply local dialog context around a hit. Results respect ``as_of``
    via :func:`_filter_rows_as_of` (neighbor turns after the cutoff are dropped).

    Args:
        conn: Neo4j connection manager.
        session_id: Session containing the matched turn.
        turn_index: Index of the matched turn (neighbors are ±1).
        as_of: Optional ingested-at ceiling for context rows.

    Returns:
        Up to two turn dicts ordered by ``turn_index``.
    """
    with conn.session() as session:
        ctx_result = session.run(
            (
                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id}) "
                "WHERE t.turn_index IN [$prev_index, $next_index] "
                "  AND t.turn_index <> $matched_turn_index "
                "RETURN "
                "    t.turn_index AS turn_index, "
                "    t.role AS role, "
                "    t.content AS content, "
                "    t.ingested_at AS ingested_at "
                "ORDER BY t.turn_index"
            ),
            session_id=session_id,
            prev_index=turn_index - 1,
            next_index=turn_index + 1,
            matched_turn_index=turn_index,
        )
        window = [dict(r) for r in ctx_result]
    return _filter_rows_as_of(window, as_of)


def _hydrate_temporal_conversation_results(
    conn: ConnectionManager,
    temporal_results: list[dict[str, Any]],
    *,
    limit: int,
    role: str | None,
    as_of: str | None,
) -> list[dict[str, Any]]:
    """Turn temporal bridge ``evidence`` entries into hydrated turn dicts.

    Skips non-conversation evidence, malformed ``sourceId`` values, duplicates,
    role mismatches, and turns after ``as_of``. Scores are derived from temporal
    ``confidence`` and ``relevance`` on the parent ranked result.

    Args:
        conn: Neo4j connection manager.
        temporal_results: ``results`` list from ``TemporalBridge.retrieve``.
        limit: Maximum hydrated turns to return.
        role: If set, exclude turns whose ``role`` differs.
        as_of: Optional ingested-at ceiling.

    Returns:
        Hydrated turns (with ``score``), newest-first by processing order, capped
        at ``limit``.
    """
    hydrated: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for ranked in temporal_results:
        temporal_score = float(ranked.get("confidence", 0.0) or 0.0) * float(
            ranked.get("relevance", 1.0) or 1.0
        )
        for evidence in ranked.get("evidence") or []:
            if evidence.get("sourceKind") != "conversation_turn":
                continue
            try:
                session_id, turn_index = parse_conversation_source_id(
                    str(evidence.get("sourceId", ""))
                )
            except (ValueError, TypeError):
                continue
            key = (session_id, turn_index)
            if key in seen:
                continue
            turn = _fetch_conversation_turn(
                conn,
                session_id=session_id,
                turn_index=turn_index,
            )
            if turn is None:
                continue
            if role is not None and turn.get("role") != role:
                continue
            if as_of is not None and (turn.get("ingested_at") or "") > as_of:
                continue
            turn["score"] = temporal_score
            hydrated.append(turn)
            seen.add(key)
            if len(hydrated) >= limit:
                return hydrated

    return hydrated


def _serialize_conversation_card(row: dict[str, Any]) -> str:
    """Serialize one conversation turn candidate for reranking."""

    return build_yaml_card(
        [
            ("domain", "conversation"),
            ("candidate_kind", "conversation_turn"),
            ("project_id", row.get("project_id")),
            ("session_id", row.get("session_id")),
            ("turn_index", row.get("turn_index")),
            ("role", row.get("role")),
            ("source_agent", row.get("source_agent")),
            ("timestamp", row.get("timestamp")),
            ("entities", row.get("entities") or []),
            ("content", row.get("content") or ""),
        ]
    )


def _apply_conversation_rerank(
    *,
    query: str,
    rows: list[dict[str, Any]],
    limit: int,
    temporal_applied: bool,
) -> tuple[list[dict[str, Any]], Any]:
    """Apply learned reranking to conversation turn rows."""

    if not rows:
        return [], rerank_documents(query, [])

    serialized = [_serialize_conversation_card(row) for row in rows]
    response = rerank_documents(query, serialized, high_stakes=False)
    if not response.applied or response.abstained or not response.scores:
        return rows[:limit], response

    rerank_scores = {score.index: score.relevance_score for score in response.scores}
    reranked_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index not in rerank_scores:
            continue
        enriched = dict(row)
        if temporal_applied:
            enriched.setdefault("temporal_score", float(row.get("score", 0.0) or 0.0))
            enriched.setdefault("baseline_score", None)
        else:
            enriched.setdefault("baseline_score", float(row.get("score", 0.0) or 0.0))
            enriched.setdefault("temporal_score", None)
        enriched["rerank_score"] = rerank_scores[index]
        enriched["score"] = rerank_scores[index]
        reranked_rows.append(enriched)

    ordered = sorted(
        reranked_rows,
        key=lambda row: (
            -float(row.get("rerank_score", 0.0) or 0.0),
            -float(row.get("temporal_score", 0.0) or 0.0),
            -float(row.get("baseline_score", 0.0) or 0.0),
            str(row.get("session_id") or ""),
            int(row.get("turn_index") or 0),
        ),
    )
    return ordered[:limit], response


def _annotate_conversation_rows(
    rows: list[dict[str, Any]],
    *,
    mode: str,
    temporal_applied: bool,
    candidate_sources: list[str],
    rerank_response: Any,
    notes: list[str],
) -> list[dict[str, Any]]:
    """Attach retrieval provenance to conversation rows."""

    annotated: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched["retrieval_provenance"] = {
            "module": "conversation",
            "mode": mode,
            "temporal_applied": temporal_applied,
            "candidate_sources": list(candidate_sources),
            "reranker_applied": bool(rerank_response.applied),
            "reranker_provider": getattr(rerank_response, "provider", None),
            "reranker_model": getattr(rerank_response, "model", None),
            "reranker_fallback_reason": getattr(rerank_response, "fallback_reason", None),
            "reranker_abstained": bool(getattr(rerank_response, "abstained", False)),
            "notes": list(notes),
        }
        annotated.append(enriched)
    return annotated


def search_conversation_turns_sync(
    pipeline: ConversationIngestionPipeline,
    *,
    query: str,
    project_id: str | None,
    role: str | None,
    limit: int,
    as_of: str | None,
    log_prefix: str,
    temporal_required: bool = False,
) -> list[dict[str, Any]]:
    """Search conversation turns with an optional temporal-first contract.

    Public hosted surfaces should pass ``temporal_required=True`` so
    conversation retrieval fails closed instead of quietly degrading to dense
    or text-only search. Internal callers can still use the best-effort path.

    Implements a three-tier retrieval strategy:
    1. Vector search via ``chat_embeddings`` Neo4j index.
    2. Temporal graph enrichment via ``TemporalBridge`` (if available and
       ``project_id`` is provided), which resolves entity-relationship paths
       through the knowledge graph for more contextually relevant results.
    3. Full-text keyword fallback if vector search fails completely.

    The ``as_of`` cutoff is applied at each tier to support time-bounded
    memory retrieval (e.g., "what did we know before this date?").

    Error handling:
        Any exception from the initial vector search triggers a warning log and
        switches to :func:`_text_conversation_search` only when
        ``temporal_required`` is ``False``. When ``temporal_required`` is
        ``True``, missing project scope, bridge unavailability, missing seeds,
        temporal retrieve failures, and empty temporal payloads raise
        :class:`TemporalRetrievalRequiredError` after structured logging.

    Args:
        pipeline: A ``ConversationIngestionPipeline`` instance that provides
            ``_conn`` (ConnectionManager), ``_embedder`` (EmbeddingService),
            and ``_extractor`` (EntityExtractionService) attributes.
        query: Natural language search string.
        project_id: If provided, restricts search to this project and enables
            temporal graph enrichment.  Pass ``None`` to search all projects
            (temporal enrichment is skipped when project_id is absent).
        role: Optional speaker role filter ("user" | "assistant").
        limit: Maximum number of turns to return.
        as_of: Optional ISO-8601 timestamp ceiling for ``ingested_at`` filtering.
        log_prefix: Label for log messages (caller identity, e.g. tool name).
        temporal_required: When ``True``, enforce temporal graph retrieval as a
            hard contract for this call and fail closed when it cannot be
            satisfied.

    Returns:
        List of conversation turn dicts ordered by relevance score descending.
        Each dict contains: session_id, turn_index, role, content, source_agent,
        timestamp, ingested_at, entities, score.
    """
    conn = pipeline._conn  # type: ignore[attr-defined]
    embedder = pipeline._embedder  # type: ignore[attr-defined]
    extractor = pipeline._extractor  # type: ignore[attr-defined]
    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
    candidate_limit = candidate_limit_for_domain("conversation", default=limit)

    def _raise_temporal_error(*, reason: str, message: str, error_type: str | None = None) -> None:
        """Log the temporal contract miss, then raise one stable public error."""
        logger.warning(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": reason,
                "error_type": error_type,
            },
        )
        raise TemporalRetrievalRequiredError(
            module="conversation",
            reason=reason,
            message=message,
            details={
                "project_id": project_id,
                "as_of": as_of,
            },
        )

    try:
        baseline_rows = _vector_conversation_search(
            conn,
            embedder,
            query=query,
            project_id=project_id,
            role=role,
            limit=candidate_limit,
        )
    except Exception as exc:
        if temporal_required:
            _raise_temporal_error(
                reason="vector_retrieve_failed",
                message=(
                    "Temporal-first conversation retrieval is required for this surface, "
                    "but the baseline vector stage failed before temporal graph expansion could run."
                ),
                error_type=type(exc).__name__,
            )
        # Embedding or vector index failure: deterministic text search still works.
        logger.warning(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "text_search_after_vector_failure",
                "error_type": type(exc).__name__,
            },
        )
        text_rows = _filter_rows_as_of(
            _text_conversation_search(
                conn,
                query=query,
                project_id=project_id,
                role=role,
                limit=candidate_limit,
            ),
            as_of,
        )
        reranked_rows, rerank_response = _apply_conversation_rerank(
            query=query,
            rows=text_rows,
            limit=limit,
            temporal_applied=False,
        )
        return _annotate_conversation_rows(
            reranked_rows,
            mode="text_fallback",
            temporal_applied=False,
            candidate_sources=["text"],
            rerank_response=rerank_response,
            notes=["Vector retrieval failed; deterministic text search was used."],
        )

    filtered_baseline = _filter_rows_as_of(baseline_rows, as_of)
    if project_id is None:
        if temporal_required:
            _raise_temporal_error(
                reason="missing_project_scope",
                message=(
                    "Temporal-first conversation retrieval requires a project_id so the temporal "
                    "graph can resolve the correct project scope."
                ),
            )
        reranked_rows, rerank_response = _apply_conversation_rerank(
            query=query,
            rows=filtered_baseline,
            limit=limit,
            temporal_applied=False,
        )
        return _annotate_conversation_rows(
            reranked_rows,
            mode="dense_only",
            temporal_applied=False,
            candidate_sources=["dense"],
            rerank_response=rerank_response,
            notes=["Project scope missing; temporal enrichment was skipped."],
        )
    if bridge is None or not bridge.is_available():
        if temporal_required:
            _raise_temporal_error(
                reason="temporal_bridge_unavailable",
                message=(
                    "Temporal-first conversation retrieval is required for this surface, "
                    "but the temporal bridge is unavailable."
                ),
            )
        logger.info(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "temporal_bridge_unavailable",
                "error_type": None,
            },
        )
        reranked_rows, rerank_response = _apply_conversation_rerank(
            query=query,
            rows=filtered_baseline,
            limit=limit,
            temporal_applied=False,
        )
        return _annotate_conversation_rows(
            reranked_rows,
            mode="dense_only",
            temporal_applied=False,
            candidate_sources=["dense"],
            rerank_response=rerank_response,
            notes=["Temporal bridge unavailable; dense baseline was used."],
        )

    seeds = collect_seed_entities(filtered_baseline, limit=5)
    if not seeds:
        try:
            seeds = extract_query_seed_entities(query, extractor)
        except Exception as exc:
            logger.warning("%s query seed extraction failed: %s", log_prefix, exc)
            seeds = []

    if not seeds:
        if temporal_required:
            _raise_temporal_error(
                reason="no_temporal_seeds",
                message=(
                    "Temporal-first conversation retrieval could not derive any temporal seeds "
                    "from the baseline candidates or query."
                ),
            )
        logger.info(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "no_temporal_seeds",
                "error_type": None,
            },
        )
        reranked_rows, rerank_response = _apply_conversation_rerank(
            query=query,
            rows=filtered_baseline,
            limit=limit,
            temporal_applied=False,
        )
        return _annotate_conversation_rows(
            reranked_rows,
            mode="dense_only",
            temporal_applied=False,
            candidate_sources=["dense"],
            rerank_response=rerank_response,
            notes=["No temporal seeds were available; dense baseline was used."],
        )

    try:
        temporal_payload = retry_transient(
            lambda: bridge.retrieve(
                project_id=project_id,
                seed_entities=seeds,
                as_of_us=parse_as_of_to_micros(as_of),
                max_edges=max(limit * 2, limit),
            )
        )
    except Exception as exc:
        if temporal_required:
            _raise_temporal_error(
                reason="temporal_retrieve_failed",
                message=(
                    "Temporal-first conversation retrieval is required for this surface, "
                    "but the temporal graph query failed."
                ),
                error_type=type(exc).__name__,
            )
        logger.warning(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "temporal_retrieve_failed",
                "error_type": type(exc).__name__,
            },
        )
        reranked_rows, rerank_response = _apply_conversation_rerank(
            query=query,
            rows=filtered_baseline,
            limit=limit,
            temporal_applied=False,
        )
        return _annotate_conversation_rows(
            reranked_rows,
            mode="dense_only",
            temporal_applied=False,
            candidate_sources=["dense"],
            rerank_response=rerank_response,
            notes=["Temporal retrieval failed; dense baseline was used."],
        )

    temporal_hits = _hydrate_temporal_conversation_results(
        conn,
        temporal_payload.get("results") or [],
        limit=candidate_limit,
        role=role,
        as_of=as_of,
    )
    if temporal_hits:
        reranked_rows, rerank_response = _apply_conversation_rerank(
            query=query,
            rows=temporal_hits,
            limit=limit,
            temporal_applied=True,
        )
        return _annotate_conversation_rows(
            reranked_rows,
            mode="temporal_graph",
            temporal_applied=True,
            candidate_sources=["temporal_graph"],
            rerank_response=rerank_response,
            notes=["Temporal graph enrichment supplied the candidate set."],
        )

    if temporal_required:
        _raise_temporal_error(
            reason="empty_temporal_result",
            message=(
                "Temporal-first conversation retrieval is required for this surface, "
                "but the temporal graph returned no usable results."
            ),
        )

    logger.info(
        "conversation_search_fallback",
        extra={
            "event": "temporal_fallback",
            "request_id": get_request_id(),
            "memory_module": "conversation",
            "provider": getattr(embedder, "provider", None),
            "fallback": "empty_temporal_result",
            "error_type": None,
        },
    )
    reranked_rows, rerank_response = _apply_conversation_rerank(
        query=query,
        rows=filtered_baseline,
        limit=limit,
        temporal_applied=False,
    )
    return _annotate_conversation_rows(
        reranked_rows,
        mode="dense_only",
        temporal_applied=False,
        candidate_sources=["dense"],
        rerank_response=rerank_response,
        notes=["Temporal graph returned no results; dense baseline was used."],
    )


def _build_conversation_pipeline_for_repo_root(repo_root: Path) -> ConversationIngestionPipeline:
    """Construct a chat pipeline for one repo (Neo4j from that repo's config when present)."""
    from agentic_memory.server.app import neo4j_connection_triple_for_repo

    uri, user, password = neo4j_connection_triple_for_repo(repo_root)
    conn = ConnectionManager(uri, user, password)
    embedder = build_embedding_service("chat")
    extractor = EntityExtractionService.from_env()
    return ConversationIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


def _get_mcp_conversation_pipeline() -> ConversationIngestionPipeline:
    """Return a ``ConversationIngestionPipeline`` for the MCP-bound (or default) repo.

    Cached per repository path so multi-root Cursor workspaces can coexist in one
    MCP process without ``CODEMEMORY_REPO`` churn in global MCP JSON.
    """
    from agentic_memory import mcp_workspace as mw

    rr = mw.effective_repo_root_for_mcp()
    return mw.get_or_create_cached(
        rr,
        _build_conversation_pipeline_for_repo_root,
        mw.conversation_pipeline_cache(),
    )


def _get_mcp_research_pipeline() -> ResearchIngestionPipeline | None:
    """Delegate to :func:`agentic_memory.server.app._get_research_pipeline` (per-repo cache)."""
    from agentic_memory.server import app as app_mod

    return app_mod._get_research_pipeline()


@lru_cache(maxsize=1)
def _get_mcp_research_scheduler() -> ResearchScheduler | None:
    """Return a cached :class:`ResearchScheduler` for MCP, or ``None``.

    Depends on :func:`_get_mcp_research_pipeline`, extraction LLM configuration,
    and a Brave Search API key (``BRAVE_SEARCH_API_KEY`` or ``BRAVE_API_KEY``).
    Logs and returns ``None`` when any dependency is absent.

    Returns:
        Scheduler instance, or ``None`` if research automation cannot start.
    """
    pipeline = _get_mcp_research_pipeline()
    extraction_llm = resolve_extraction_llm_config()
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
    if pipeline is None or not extraction_llm.api_key or not brave_api_key:
        logger.warning("Research scheduler unavailable: missing pipeline or API keys.")
        return None

    return ResearchScheduler(
        connection_manager=pipeline._conn,  # type: ignore[attr-defined]
        extraction_llm_api_key=extraction_llm.api_key,
        extraction_llm_model=extraction_llm.model,
        extraction_llm_provider=extraction_llm.provider,
        extraction_llm_base_url=extraction_llm.base_url,
        brave_api_key=brave_api_key,
        pipeline=pipeline,
    )

class Toolkit:
    """Synchronous code-graph and git reporting for MCP tools and scripts.

    Wraps :class:`KnowledgeGraphBuilder` and :func:`search_code` to produce
    Markdown strings suitable for LLM context. Callers include the internal MCP
    server and tests; this class does **not** perform async I/O and does **not**
    implement conversation memory (those tools use
    :func:`register_conversation_tools`).

    Error contract:
        Neo4j client/database errors are caught and returned as human-readable
        error lines inside the Markdown string so MCP layers can forward them
        without stack traces.

    Attributes:
        graph: Shared graph builder (driver lifecycle owned by the caller).
    """

    def __init__(self, graph: KnowledgeGraphBuilder):
        """Initialize Toolkit with a pre-connected graph builder.

        Args:
            graph: An initialized ``KnowledgeGraphBuilder`` instance.  The caller
                is responsible for its lifecycle (``graph.close()`` on shutdown).
        """
        self.graph = graph

    def semantic_search(
        self,
        query: str,
        limit: int = 5,
        repo_id: str | None = None,
        retrieval_policy: str = SAFE_RETRIEVAL_POLICY,
    ) -> str:
        """Search the code graph and format hits as a Markdown report.

        Delegates retrieval to :func:`agentic_memory.server.code_search.search_code`,
        then appends **provenance** lines (policy, mode, structural edges used)
        so agents understand how results were produced. Default ``retrieval_policy``
        is ``safe`` to keep callers on the supported path unless they opt into
        graph reranking.

        Args:
            query: Natural-language code search request.
            limit: Maximum number of code results to return.
            repo_id: Optional repo scope override.
            retrieval_policy: ``safe`` by default; ``graph_reranked`` enables
                structural reranking without ``CALLS`` edges.

        Returns:
            Markdown report, ``No relevant code found...`` when empty, or
            ``Error executing search: ...`` on Neo4j ``DatabaseError`` /
            ``ClientError``.
        """
        try:
            results = search_code(
                self.graph,
                query=query,
                limit=limit,
                repo_id=repo_id,
                retrieval_policy=retrieval_policy,
            )
            if not results:
                return "No relevant code found in the graph."

            report = f"### Found {len(results)} relevant code snippets for '{query}':\n\n"
            provenance = dict((results[0].get("retrieval_provenance") or {}))
            if provenance:
                graph_edges = provenance.get("graph_edge_types_used") or []
                report += f"**Retrieval policy:** `{provenance.get('policy', 'unknown')}`\n"
                report += f"**Mode:** `{provenance.get('mode', 'unknown')}`\n"
                report += (
                    f"**Graph reranking applied:** "
                    f"`{bool(provenance.get('graph_reranking_applied', False))}`\n"
                )
                report += (
                    f"**Structural edges used:** "
                    f"{', '.join(f'`{edge}`' for edge in graph_edges) if graph_edges else '`none`'}\n"
                )
                report += "**CALLS used for ranking:** `False`\n"
                for note in provenance.get("notes") or []:
                    report += f"**Note:** {note}\n"
                report += "\n"
            for r in results:
                report += f"#### 📄 {r['name']} (Score: {r['score']:.2f})\n"
                report += f"**Signature:** `{r['sig']}`\n"
                if r.get("path"):
                    report += f"**Path:** `{r['path']}`\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            logger.error(f"search failed:{e}")
            return f"Error executing search: {str(e)}"
    
    def get_file_dependencies(self, file_path: str, repo_id: str | None = None) -> str:
        """Summarize import edges for a single file.

        Calls :meth:`KnowledgeGraphBuilder.get_file_dependencies` and formats
        outgoing imports and incoming ``imported_by`` paths for the model.

        Args:
            file_path: Repository-relative path of the file to analyze.
            repo_id: Optional multi-repo scope.

        Returns:
            Markdown dependency report, or ``Error analyzing dependencies: ...``
            when Neo4j raises ``DatabaseError`` / ``ClientError``.
        """
        try:
            deps = self.graph.get_file_dependencies(
                file_path,
                repo_id=repo_id,
            )
            dep_list = deps.get("imports", [])
            caller_list = deps.get("imported_by", [])

            return (
                f"### Dependency Report for `{file_path}`\n"
                f"**Imports (outgoing):** {dep_list if dep_list else 'None'}\n"
                f"**Used By (incoming):** {caller_list if caller_list else 'None'}"
            )
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error analyzing dependencies: {str(e)}"

    def get_git_file_history(self, file_path: str, limit: int = 20) -> str:
        """List recent commits touching ``file_path`` using ingested git graph data.

        Args:
            file_path: Path as stored in the git graph.
            limit: Maximum commits to include.

        Returns:
            Markdown bullet list of short SHAs and subjects, a message when no
            git graph exists, ``No git history found...`` when the query is empty,
            or ``Error getting git file history: ...`` on Neo4j errors.
        """
        try:
            if not self.graph.has_git_graph_data():
                return "No git graph data found. Run git ingestion first."

            history = self.graph.get_git_file_history(file_path, limit=limit)
            if not history:
                return f"No git history found for `{file_path}`."

            report = f"### Git History for `{file_path}`\n"
            report += f"Found {len(history)} commit(s):\n"
            for row in history:
                sha = row.get("sha", "unknown")
                short_sha = sha[:12] if isinstance(sha, str) else "unknown"
                subject = row.get("message_subject", "(no subject)")
                report += f"- `{short_sha}` {subject}\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error getting git file history: {str(e)}"

    def get_commit_context(self, sha: str, include_diff_stats: bool = True) -> str:
        """Show metadata (and optional diff stats) for one commit SHA.

        Args:
            sha: Commit identifier as stored in the graph (prefixes are resolved
                by the graph layer).
            include_diff_stats: When ``True``, append file/addition/deletion counts.

        Returns:
            Markdown summary, guidance when git data is missing, ``No commit found``
            when unknown, or ``Error getting commit context: ...`` on Neo4j errors.
        """
        try:
            if not self.graph.has_git_graph_data():
                return "No git graph data found. Run git ingestion first."

            context: Optional[Dict[str, Any]] = self.graph.get_commit_context(
                sha, include_diff_stats=include_diff_stats
            )
            if not context:
                return f"No commit found for `{sha}`."

            report = f"### Commit `{context.get('sha', sha)}`\n"
            report += f"Subject: {context.get('message_subject', '(no subject)')}\n"
            report += f"Author: {context.get('author_name', 'unknown')}\n"
            report += f"Committed: {context.get('committed_at', 'unknown')}\n"

            if include_diff_stats:
                stats = context.get("stats", {})
                report += (
                    f"Files Changed: {stats.get('files_changed', 0)}, "
                    f"Additions: {stats.get('additions', 0)}, "
                    f"Deletions: {stats.get('deletions', 0)}\n"
                )

            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error getting commit context: {str(e)}"


# ---------------------------------------------------------------------------
# Phase 4: Conversation MCP Tools
# ---------------------------------------------------------------------------


async def _workspace_bind_token(ctx: Context | None):
    """Run MCP ``roots/list`` binding for async tools (no ``log_tool_call`` wrapper)."""
    from agentic_memory.mcp_workspace import bind_workspace_for_tool_call

    _, token = await bind_workspace_for_tool_call(ctx)
    return token


def register_conversation_tools(
    mcp: object,  # type: ignore[type-arg]
    *,
    annotation_resolver: ToolAnnotationResolver | None = None,
) -> None:
    """Attach conversation search, context, and ingestion tools to ``mcp``.

    Registers ``search_conversations``, ``get_conversation_context``, and
    ``add_message``. Each async handler resolves the cached pipeline then runs
    blocking Neo4j / embedding work in the default thread pool executor so the
    MCP server remains responsive.

    Args:
        mcp: FastMCP application instance (supports ``@mcp.tool``).
        annotation_resolver: Optional callback passed to
            :func:`_tool_registration_kwargs` to attach per-tool
            ``ToolAnnotations`` (used by the public MCP profile).

    Note:
        MCP-visible ``description`` strings are defined at registration sites
        below; Python docstrings document runtime behavior for maintainers.
    """

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "search_conversations",
            "Search past conversations for relevant exchanges. Use when you need to find "
            "prior context, check what was discussed about a topic, or retrieve conversation "
            "history by semantic similarity.",
            annotation_resolver,
        )
    )
    async def search_conversations(
        query: str,
        project_id: str | None = None,
        role: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict]:
        """Semantic search over conversation memory with a temporal-first contract.

        Public MCP conversation search must not silently degrade to a dense-only
        success shape. This tool therefore delegates to
        :func:`search_conversation_turns_sync` with ``temporal_required=True``
        and lets temporal contract failures propagate as MCP tool errors.

        Args:
            query: Natural language search query.
            project_id: Optional project filter; ``None`` searches all projects.
            role: Optional role filter (``user`` / ``assistant``); ``None`` keeps
                all roles.
            limit: Maximum number of results to return (bounded by the Cypher
                ``LIMIT``).
            as_of: Optional ISO-8601 ceiling on ``ingested_at`` applied to rows
                after the query returns.

        Returns:
            List of turn dicts ranked by the temporal-first retrieval path.
        """
        from agentic_memory.mcp_workspace import reset_repo_binding

        reset_token = await _workspace_bind_token(ctx)
        try:
            pipeline = _get_mcp_conversation_pipeline()
            loop = asyncio.get_event_loop()

            def _run() -> list[dict]:
                return search_conversation_turns_sync(
                    pipeline,
                    query=query,
                    project_id=project_id,
                    role=role,
                    limit=limit,
                    as_of=as_of,
                    log_prefix="search_conversations",
                    temporal_required=True,
                )

            # Blocking embed + Neo4j session: keep off the asyncio event loop.
            return await loop.run_in_executor(None, _run)
        finally:
            reset_repo_binding(reset_token)

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "get_conversation_context",
            "Retrieve the most relevant past conversation context for a given query or task. "
            "Returns a compact, structured bundle of prior exchanges ranked by relevance. "
            "Use this to ground responses in prior conversation history before answering a "
            "user's question.",
            annotation_resolver,
        )
    )
    async def get_conversation_context(
        query: str,
        project_id: str,
        limit: int = 5,
        include_session_context: bool = True,
        as_of: str | None = None,
        ctx: Context | None = None,
    ) -> dict:
        """Retrieve structured conversation context for LLM grounding.

        Uses :func:`search_conversation_turns_sync` with
        ``temporal_required=True`` so this public MCP surface fails closed when
        temporal retrieval is unavailable. Optionally hydrates a ±1 **context
        window** per hit via :func:`_fetch_conversation_context_window`.

        Args:
            query: Natural language query describing what context is needed.
            project_id: Required project scope (temporal path needs a project).
            limit: Number of primary turns to return (keep small for LLM windows).
            include_session_context: When ``True``, attach neighboring turns
                (respecting ``as_of``) for each match.
            as_of: Optional ingested-at ceiling forwarded to search and window
                hydration.

        Returns:
            Dict with ``query`` and ``turns`` (each turn may include
            ``context_window``).
        """
        from agentic_memory.mcp_workspace import reset_repo_binding

        reset_token = await _workspace_bind_token(ctx)
        try:
            pipeline = _get_mcp_conversation_pipeline()
            conn = pipeline._conn  # type: ignore[attr-defined]

            loop = asyncio.get_event_loop()

            def _run() -> dict:
                matched_turns = search_conversation_turns_sync(
                    pipeline,
                    query=query,
                    project_id=project_id,
                    role=None,
                    limit=limit,
                    as_of=as_of,
                    log_prefix="get_conversation_context",
                    temporal_required=True,
                )
                turns_with_context = []
                for turn in matched_turns:
                    turn_data = dict(turn)
                    context_window: list[dict] = []

                    if include_session_context:
                        context_window = _fetch_conversation_context_window(
                            conn,
                            session_id=turn["session_id"],
                            turn_index=turn["turn_index"],
                            as_of=as_of,
                        )

                    turn_data["context_window"] = context_window
                    turns_with_context.append(turn_data)

                return {"query": query, "turns": turns_with_context}

            # search_conversation_turns_sync + Neo4j window reads are synchronous.
            return await loop.run_in_executor(None, _run)
        finally:
            reset_repo_binding(reset_token)

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "add_message",
            "Explicitly save a conversation turn to memory. Use this when you want to ensure "
            "a specific message is persisted, or when passive capture is not configured. "
            "Provide turn_index=0 for single messages; use sequential indexes for multi-turn writes.",
            annotation_resolver,
        )
    )
    async def add_message(
        role: str,
        content: str,
        session_id: str,
        project_id: str,
        turn_index: int = 0,
        source_agent: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        timestamp: str | None = None,
        ctx: Context | None = None,
    ) -> dict:
        """Persist a single conversation turn to the memory graph.

        Builds a turn payload with fixed ``source_key="chat_mcp"`` and
        ``ingestion_mode="active"`` so downstream ingestion can distinguish
        explicit MCP writes from passive capture. Executes
        :meth:`ConversationIngestionPipeline.ingest` in a worker thread.

        Args:
            role: Turn role: ``user`` | ``assistant`` | ``system`` | ``tool``.
            content: Turn text content.
            session_id: Caller-owned session boundary identifier.
            project_id: Project this conversation belongs to.
            turn_index: 0-based position within the session (default ``0``).
            source_agent: AI that produced this turn (e.g. ``claude``).
            model: Specific model variant (e.g. ``claude-opus-4-6``).
            tool_name: For ``role="tool"``: the tool that was called.
            tool_call_id: Request/response pairing for tool turns.
            tokens_input: Input token count if known.
            tokens_output: Output token count if known.
            timestamp: ISO-8601 turn timestamp; ingestion fills timing if omitted.

        Returns:
            Ingestion summary dict (hashes, embedding/entity counts, ids) on
            success, or ``{"error": "<message>"}`` if ingestion raises.
        """
        from agentic_memory.mcp_workspace import (
            WriteTargetUnresolved,
            reset_repo_binding,
            resolve_write_target_repo_id,
        )

        reset_token = await _workspace_bind_token(ctx)
        try:
            # Let an active /project write override an empty caller value, and
            # give OpenClaw sessions a crisp "pin a project first" error
            # instead of silently tagging memory to cwd. When project_id is
            # non-empty, it passes through unchanged so agents that already
            # know the target stay in control.
            try:
                resolved_project_id = resolve_write_target_repo_id(explicit=project_id)
            except WriteTargetUnresolved as exc:
                return {"error": str(exc)}

            pipeline = _get_mcp_conversation_pipeline()
            loop = asyncio.get_event_loop()

            turn = {
                "role": role,
                "content": content,
                "session_id": session_id,
                "project_id": resolved_project_id,
                "turn_index": turn_index,
                "source_agent": source_agent,
                "model": model,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "tokens_input": tokens_input,
                "tokens_output": tokens_output,
                "timestamp": timestamp,
                "ingestion_mode": "active",
                "source_key": "chat_mcp",
            }

            try:
                # Ingestion performs Neo4j writes and embedding work; keep it off the loop.
                result: dict = await loop.run_in_executor(None, pipeline.ingest, turn)
                return result
            except Exception as exc:
                logger.error("add_message failed: %s", exc)
                return {"error": str(exc)}
        finally:
            reset_repo_binding(reset_token)


def register_schedule_tools(
    mcp: object,  # type: ignore[type-arg]
    connection_manager: ConnectionManager | None = None,
    groq_api_key: str | None = None,
    brave_api_key: str | None = None,
    pipeline: ResearchIngestionPipeline | None = None,
) -> None:
    """Register recurring web-research scheduling tools on the MCP instance.

    Registers three MCP tools: ``schedule_research``, ``run_research_session``,
    and ``list_research_schedules``.  These allow AI agents to create persistent
    research schedules backed by APScheduler and Neo4j, trigger ad hoc research
    sessions, and inspect what schedules are active.

    A lazy scheduler singleton is created on first tool invocation.  If the
    caller provides explicit ``connection_manager``, ``groq_api_key``,
    ``brave_api_key``, and ``pipeline``, those are used; otherwise the function
    falls back to ``_get_mcp_research_scheduler()`` which reads from environment
    variables.  If either the embedding service or Brave Search API key is
    unavailable, all three tools return an error string rather than raising.

    Call this once during MCP server startup, after the FastMCP instance is created.

    Args:
        mcp: The FastMCP instance to register tools on.
        connection_manager: Optional pre-built Neo4j ConnectionManager.
        groq_api_key: Optional Groq API key for the extraction LLM.
        brave_api_key: Optional Brave Search API key for web research.
        pipeline: Optional pre-built ResearchIngestionPipeline.

    Note:
        Tool ``description=`` strings are defined on decorators below; they are
        the MCP-facing summaries. Python docstrings describe return contracts
        and validation behavior.
    """

    scheduler_singleton: ResearchScheduler | None = None

    def _get_scheduler():
        """Lazily construct or return the shared :class:`ResearchScheduler`."""
        nonlocal scheduler_singleton
        if scheduler_singleton is not None:
            return scheduler_singleton

        if connection_manager and pipeline and groq_api_key and brave_api_key:
            extraction_llm = resolve_extraction_llm_config(api_key=groq_api_key)
            scheduler_singleton = ResearchScheduler(
                connection_manager=connection_manager,
                extraction_llm_api_key=extraction_llm.api_key,
                extraction_llm_model=extraction_llm.model,
                extraction_llm_provider=extraction_llm.provider,
                extraction_llm_base_url=extraction_llm.base_url,
                brave_api_key=brave_api_key,
                pipeline=pipeline,
            )
            return scheduler_singleton

        scheduler_singleton = _get_mcp_research_scheduler()
        return scheduler_singleton

    # Resolve scheduler once at import/registration time when possible so logs
    # appear early; tools call _get_scheduler() again idempotently.
    _get_scheduler()

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Create a recurring research schedule backed by APScheduler and Neo4j. "
            "Use this when you want ongoing automated research for a project."
        )
    )
    async def schedule_research(
        template: str,
        variables: list[str],
        cron_expr: str,
        project_id: str,
        max_runs_per_day: int = 5,
    ) -> str:
        """Create and persist a recurring research schedule.

        Args:
            template: Prompt / URL pattern template for scheduled runs.
            variables: Template variable names or values as required by scheduler.
            cron_expr: Cron expression consumed by APScheduler.
            project_id: Owning project identifier in Neo4j.
            max_runs_per_day: Safety cap forwarded to the scheduler.

        Returns:
            JSON string ``{"status": "ok", "schedule_id": ...}`` on success, or
            ``{"status": "error", "error": "Research scheduler is not configured."}``
            when dependencies are missing.
        """
        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()

        def _run() -> str:
            return scheduler.create_schedule(
                template=template,
                variables=variables,
                cron_expr=cron_expr,
                project_id=project_id,
                max_runs_per_day=max_runs_per_day,
            )

        schedule_id = await loop.run_in_executor(None, _run)
        return json.dumps({"status": "ok", "schedule_id": schedule_id})

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Run a recurring research session now. Use an existing schedule_id or provide "
            "an ad hoc project/template/variables tuple."
        )
    )
    async def run_research_session(
        schedule_id: str | None = None,
        project_id: str | None = None,
        template: str | None = None,
        variables: list[str] | None = None,
    ) -> str:
        """Trigger one scheduled or ad hoc research session.

        Validates inputs before touching the scheduler: callers must supply either
        ``schedule_id`` **or** both ``project_id`` and ``template`` for ad hoc
        runs. Delegates to :meth:`ResearchScheduler.run_research_session` inside
        a worker thread.

        Args:
            schedule_id: Existing schedule to run, if any.
            project_id: Required for ad hoc runs together with ``template``.
            template: Ad hoc template when no ``schedule_id`` is provided.
            variables: Optional template variables for ad hoc execution.

        Returns:
            JSON-encoded dict from the scheduler (structure defined by
            ``ResearchScheduler``), or a JSON error object when validation fails
            or the scheduler is unavailable.
        """
        if not schedule_id and not (project_id and template):
            return json.dumps(
                {
                    "status": "error",
                    "error": "Provide schedule_id or (project_id + template).",
                }
            )

        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()

        def _run() -> dict[str, Any]:
            return scheduler.run_research_session(
                schedule_id=schedule_id,
                ad_hoc_template=template,
                ad_hoc_variables=variables,
                project_id=project_id,
            )

        result = await loop.run_in_executor(None, _run)
        return json.dumps(result)

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "List the stored recurring research schedules for a project."
        )
    )
    async def list_research_schedules(project_id: str) -> str:
        """List recurring research schedules for a project.

        Args:
            project_id: Project key whose schedules are loaded from Neo4j.

        Returns:
            JSON ``{"status": "ok", "schedules": [...]}`` on success, or a JSON
            error payload when the scheduler is not configured.
        """
        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()
        schedules = await loop.run_in_executor(None, scheduler.list_schedules, project_id)
        return json.dumps({"status": "ok", "schedules": schedules})


def _list_known_repo_ids() -> list[str]:
    """Return the sorted list of distinct ``repo_id`` values stored in the graph.

    Queries Neo4j for every non-null ``repo_id`` property on any node. Used by
    ``/project list`` to render known projects and by the scope-setter tools
    (:func:`register_project_scope_tools`) to validate that user-supplied
    ``repo_id`` arguments refer to something that actually exists. Also
    includes any ``(:Project {repo_id})`` marker nodes created via
    :func:`_create_project_marker`, so a freshly registered project shows up
    before it has any other memory attached.

    Returns an empty list when the graph is unreachable; the caller is
    expected to render a helpful error rather than silently accepting any id.

    The query is intentionally broad (``MATCH (n)``) so we surface every repo
    that has any memory at all (code, chat, research, or bare Project
    marker). On a populated graph this is a cheap scan because ``repo_id`` is
    indexed; on an empty graph it returns instantly.

    Returns:
        Alphabetically sorted list of distinct ``repo_id`` strings.
    """
    from agentic_memory.server.app import get_graph

    graph = get_graph()
    if graph is None:
        logger.warning("_list_known_repo_ids: graph unavailable; returning [].")
        return []
    try:
        with graph.driver.session() as session:
            result = session.run(
                "MATCH (n) WHERE n.repo_id IS NOT NULL "
                "RETURN DISTINCT n.repo_id AS repo_id ORDER BY repo_id"
            )
            return [row["repo_id"] for row in result if row.get("repo_id")]
    except Exception as exc:
        logger.warning("_list_known_repo_ids query failed: %s", exc)
        return []


def _list_known_project_ids() -> list[str]:
    """Return the sorted list of distinct ``project_id`` values stored in the graph."""

    from agentic_memory.server.app import get_graph

    graph = get_graph()
    if graph is None:
        logger.warning("_list_known_project_ids: graph unavailable; returning [].")
        return []
    return list_known_project_ids(graph)


def list_project_and_repo_ids() -> dict[str, Any]:
    """Return the simple discovery payload for agent-facing repo/project lookup.

    This helper backs the MCP tool and any adapter layer that needs the same
    outward contract without re-querying the graph differently.
    """

    from agentic_memory.server.app import get_graph

    graph = get_graph()
    if graph is None:
        return {
            "status": "error",
            "message": "graph unavailable; cannot list project and repo ids.",
            "project_ids": [],
            "repo_ids": [],
        }
    return list_project_and_repo_ids_payload(graph)


def _create_project_marker(repo_id: str, display_name: str | None = None) -> dict:
    """Upsert a ``(:Project {repo_id})`` marker so ``repo_id`` is a known id.

    A ``Project`` marker is a lightweight node that exists purely to register
    a new ``repo_id`` in the graph's enum without requiring any actual memory
    to be ingested first. This lets ``/project focus``, ``/project write``,
    and ``/project isolate`` accept the id on subsequent calls (they validate
    against ``_list_known_repo_ids``).

    The upsert is idempotent: calling with an existing ``repo_id`` only
    updates ``display_name`` / ``updated_at`` and does not create duplicate
    nodes. A ``created`` boolean in the return dict tells the tool layer
    whether this was the first registration (so it can render "Created …"
    vs "Already registered …").

    Args:
        repo_id: The stable project identifier the user wants to pin writes
            to and read from. No normalization beyond ``strip()`` is done —
            callers should pre-validate.
        display_name: Optional human-friendly name rendered in status lines.

    Returns:
        ``{"repo_id": str, "display_name": str | None, "created": bool}``.

    Raises:
        RuntimeError: If the graph is unavailable or the Cypher write fails.
            Tool handlers should catch and convert to ``{"error": ...}``.
    """
    from agentic_memory.server.app import get_graph

    graph = get_graph()
    if graph is None:
        raise RuntimeError("graph unavailable; cannot create project marker")
    with graph.driver.session() as session:
        result = session.run(
            """
            MERGE (p:Project {repo_id: $repo_id})
            ON CREATE SET p.created_at = datetime(), p._is_new = true
            ON MATCH SET p._is_new = false
            SET p.display_name = coalesce($display_name, p.display_name),
                p.updated_at = datetime()
            WITH p, p._is_new AS is_new
            REMOVE p._is_new
            RETURN p.repo_id AS repo_id, p.display_name AS display_name, is_new AS created
            """,
            repo_id=repo_id,
            display_name=display_name,
        )
        row = result.single()
        if row is None:
            raise RuntimeError("project marker upsert returned no row")
        return {
            "repo_id": row["repo_id"],
            "display_name": row["display_name"],
            "created": bool(row["created"]),
        }


def _require_known_repo_ids(requested: list[str]) -> dict | None:
    """Return an error payload when any ``requested`` repo_id is unknown.

    Used by ``/project focus``, ``/project isolate``, and ``/project write``
    to stop typos and stale ids from silently shaping the session. The graph
    is checked on every call rather than cached because the known-repo set
    can grow mid-session (another agent writing memory, a sibling CLI
    ingestion running). Empty graphs still block unknown ids — callers must
    run ``create_project`` first to bootstrap.

    Args:
        requested: Non-empty list of ``repo_id`` values the caller wants to
            apply.

    Returns:
        ``None`` when every id is known (and the caller should proceed), or
        an error dict in the canonical tool-response shape:
        ``{"status": "error", "message": "...", "unknown": [...],
        "known_repos": [...]}``.
    """
    if not requested:
        return None
    known = set(_list_known_repo_ids())
    unknown = [r for r in requested if r not in known]
    if not unknown:
        return None
    return {
        "status": "error",
        "message": (
            "Unknown project id(s): "
            + ", ".join(repr(r) for r in unknown)
            + ". Run /project list to see what exists, or create_project "
            "<repo_id> to register a new one."
        ),
        "unknown": unknown,
        "known_repos": sorted(known),
    }


def _scopes_payload(message: str | None = None) -> dict[str, Any]:
    """Build the canonical response shape returned by every ``/project`` tool.

    Keeping a single shape across status / focus / isolate / write / clear
    makes it easy for OpenClaw's status line to render the latest state from
    any tool's response without branching. ``known_repos`` supplies
    autocompletion hints without a second round trip. ``resolved_write_target``
    shows the ``repo_id`` new memory would be tagged with **right now** if an
    ingestion call fired without an explicit ``project_id``: this makes the
    OpenClaw "no active project" case visible in the status line before a
    write fails.

    Args:
        message: Optional human-readable sentence describing what just changed.
            Rendered by the client beside the new status.

    Returns:
        ``{"status": "ok", "scopes": {...}, "known_repos": [...],
        "resolved_write_target": "<repo_id>" | None, "message": "..."}``.
    """
    from agentic_memory.mcp_workspace import (
        WriteTargetUnresolved,
        get_active_scopes,
        resolve_write_target_repo_id,
    )

    scopes = get_active_scopes()
    try:
        resolved = resolve_write_target_repo_id()
        resolved_error: str | None = None
    except WriteTargetUnresolved as exc:
        resolved = None
        resolved_error = str(exc)

    payload: dict[str, Any] = {
        "status": "ok",
        "scopes": scopes.as_dict(),
        "known_repos": _list_known_repo_ids(),
        "resolved_write_target": resolved,
    }
    if resolved_error is not None:
        payload["resolved_write_target_error"] = resolved_error
    if message:
        payload["message"] = message
    return payload


def register_project_scope_tools(
    mcp: object,  # type: ignore[type-arg]
    *,
    annotation_resolver: ToolAnnotationResolver | None = None,
) -> None:
    """Attach the ``/project``-family scope management tools to ``mcp``.

    Registers eight MCP tools that let the user (or the agent on the user's
    behalf) steer three session-level scopes: **focus** (ranking hint, not
    yet wired into retrieval — stored only), **isolate** (hard read/injection
    filter), and **write_target** (which ``repo_id`` new memory is tagged
    with). See :mod:`agentic_memory.mcp_workspace` for the underlying state
    machine and its semantics.

    The tools are designed to double as slash commands in clients that map
    tools to ``/name`` UI (Cursor, OpenClaw). Every tool returns the same
    response shape (see :func:`_scopes_payload`) so the status line can render
    the latest snapshot from any response without branching.

    None of these tools change retrieval today; wiring the focus list into
    ranking is a separate, research-gated task
    (see ``.claude/plans/decision-doc-rerankers.md`` and the follow-up
    doc stub in ``.planning``). Isolation and write targeting take effect
    once tasks 6–7 land (write-target resolution / read enum validation).

    Args:
        mcp: FastMCP application instance (supports ``@mcp.tool``).
        annotation_resolver: Optional callback passed to
            :func:`_tool_registration_kwargs` to attach per-tool
            ``ToolAnnotations`` (public profile uses this to mark these tools
            as side-effecting state changes rather than reads).
    """

    @mcp.resource(  # type: ignore[attr-defined]
        "resource://agentic-memory/active-scopes",
        name="active-scopes",
        title="Agentic Memory: Active Project Scopes",
        description=(
            "Current project scope snapshot (focus, isolate, write_target, "
            "resolved write repo_id, known repos). OpenClaw polls this resource "
            "to render the status line above the prompt; other clients can read "
            "it as a JSON blob. The same structure is returned by /project_status."
        ),
        mime_type="application/json",
    )
    def active_scopes_resource() -> str:
        """Serialize the current scope snapshot as JSON for status-line rendering.

        The host reads this resource instead of calling :func:`project_status` so
        the UI can refresh on its own cadence without consuming a tool-call slot.
        We return a JSON string (mime ``application/json``) because FastMCP
        forwards strings verbatim; dict returns get wrapped into an ad-hoc
        schema that status-line renderers would have to unwrap.

        The payload shape matches :func:`_scopes_payload` minus the ``message``
        key (status-line UIs have nothing to do with the per-call message). A
        top-level ``resolved_write_target_error`` key, when present, tells the
        UI to render a warning badge (typically: OpenClaw with no project set).
        """
        payload = _scopes_payload()
        payload.pop("message", None)
        return json.dumps(payload, sort_keys=True)

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_status",
            "Show the current memory scopes: which project(s) are in focus, whether reads "
            "are isolated to a subset, and which project new memory is being written to.",
            annotation_resolver,
        )
    )
    async def project_status(ctx: Context | None = None) -> dict:
        """Return the current :class:`ActiveScopes` snapshot plus known repo ids."""
        return _scopes_payload()

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_list",
            "List every project (repo_id) that has memory stored in the graph. Use before "
            "calling project_focus / project_isolate / project_write to pick a valid id.",
            annotation_resolver,
        )
    )
    async def project_list(ctx: Context | None = None) -> dict:
        """Enumerate distinct ``repo_id`` values available in the shared graph."""
        return {
            "status": "ok",
            "known_repos": _list_known_repo_ids(),
        }

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "list_project_and_repo_ids",
            "List the currently known project_id and repo_id values so agents can pick an exact scope.",
            annotation_resolver,
        )
    )
    async def list_project_and_repo_ids_tool(ctx: Context | None = None) -> dict:
        """Enumerate outward-facing repo ids plus project ids for agent discovery."""

        return list_project_and_repo_ids()

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_focus",
            "Add one or more projects (repo_ids) to the focus list. Focus is a soft ranking "
            "hint (informational today; a ranking boost is a separate follow-up). Accepts a "
            "comma- or space-separated string, or a list of ids.",
            annotation_resolver,
        )
    )
    async def project_focus(repo_ids: str | list[str], ctx: Context | None = None) -> dict:
        """Replace the focus list with ``repo_ids`` and return the new snapshot."""
        from agentic_memory.mcp_workspace import _normalize_repo_ids, set_focus

        requested = list(_normalize_repo_ids(repo_ids))
        err = _require_known_repo_ids(requested)
        if err is not None:
            return err
        set_focus(requested)
        return _scopes_payload(message=f"Focus set to {_scopes_payload()['scopes']['focus']}.")

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_unfocus",
            "Remove a project from the focus list, or clear focus entirely when repo_id is "
            "omitted. Does not affect isolation or write target.",
            annotation_resolver,
        )
    )
    async def project_unfocus(repo_id: str | None = None, ctx: Context | None = None) -> dict:
        """Remove ``repo_id`` from focus, or clear the whole list when omitted."""
        from agentic_memory.mcp_workspace import clear_focus, remove_focus

        if repo_id and repo_id.strip():
            remove_focus(repo_id.strip())
            return _scopes_payload(message=f"Removed {repo_id.strip()!r} from focus.")
        clear_focus()
        return _scopes_payload(message="Focus cleared.")

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_isolate",
            "Hard-filter every search and automatic context injection to the given project(s). "
            "Use for focused work sessions where cross-project context would be noise. Pass a "
            "comma- or space-separated string, or a list of ids.",
            annotation_resolver,
        )
    )
    async def project_isolate(repo_ids: str | list[str], ctx: Context | None = None) -> dict:
        """Turn on isolation: reads and injection will only see these ``repo_ids``."""
        from agentic_memory.mcp_workspace import _normalize_repo_ids, set_isolate

        requested = list(_normalize_repo_ids(repo_ids))
        err = _require_known_repo_ids(requested)
        if err is not None:
            return err
        set_isolate(requested)
        return _scopes_payload(
            message=f"Isolation active for {_scopes_payload()['scopes']['isolate']}.",
        )

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_unisolate",
            "Turn off isolation so searches and automatic injection see every project again.",
            annotation_resolver,
        )
    )
    async def project_unisolate(ctx: Context | None = None) -> dict:
        """Drop the isolation list."""
        from agentic_memory.mcp_workspace import clear_isolate

        clear_isolate()
        return _scopes_payload(message="Isolation cleared; reads span every project.")

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_write",
            "Pin new memory writes to a specific project (repo_id). Recommended for OpenClaw "
            "sessions where the client has no implicit workspace root. Pass an empty string "
            "to fall back to auto-detection.",
            annotation_resolver,
        )
    )
    async def project_write(repo_id: str, ctx: Context | None = None) -> dict:
        """Pin the write target to ``repo_id`` or clear it when empty."""
        from agentic_memory.mcp_workspace import set_write_target

        target = repo_id.strip() if isinstance(repo_id, str) else None
        if target:
            # Stop typos from silently tagging new memory to a phantom project.
            # Users who want a brand-new repo_id should call create_project
            # first; the error message nudges them there.
            err = _require_known_repo_ids([target])
            if err is not None:
                return err
        set_write_target(target or None)
        if target:
            return _scopes_payload(message=f"New writes will be tagged with {target!r}.")
        return _scopes_payload(message="Write target cleared; writes use auto-detection.")

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "project_clear",
            "Reset every scope: clears focus, isolation, and write target in one call.",
            annotation_resolver,
        )
    )
    async def project_clear(ctx: Context | None = None) -> dict:
        """Reset all three scopes to their default ('no override') values."""
        from agentic_memory.mcp_workspace import clear_all_scopes

        clear_all_scopes()
        return _scopes_payload(message="All project scopes cleared.")

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "create_project",
            "Register a new project (repo_id) in the graph. Required before /project focus, "
            "/project write, or /project isolate will accept it. Does not ingest memory; it "
            "only creates a marker node so the new id is recognized.",
            annotation_resolver,
        )
    )
    async def create_project(
        repo_id: str,
        display_name: str | None = None,
        ctx: Context | None = None,
    ) -> dict:
        """Upsert a Project marker and return the resulting enum entry.

        Using a dedicated tool (instead of auto-creating on first write)
        matches the user's preference for explicit project setup: typos fail
        loudly, and a fresh graph cannot accumulate unintended partitions.
        The upsert is idempotent, so re-calling with the same ``repo_id``
        is safe and only updates the optional ``display_name``.

        Args:
            repo_id: Stable identifier for the project (e.g. ``my-service``).
                Whitespace is trimmed; an empty value is rejected.
            display_name: Optional human-readable name rendered by status
                lines and project lists.

        Returns:
            ``{"status": "ok", "project": {...}, "known_repos": [...],
            "message": "..."}`` on success, or ``{"status": "error", ...}``.
        """
        cleaned = repo_id.strip() if isinstance(repo_id, str) else ""
        if not cleaned:
            return {
                "status": "error",
                "message": "repo_id is required and must not be empty.",
            }
        try:
            project = _create_project_marker(cleaned, display_name=display_name)
        except RuntimeError as exc:
            logger.error("create_project failed: %s", exc)
            return {"status": "error", "message": str(exc)}
        return {
            "status": "ok",
            "project": project,
            "known_repos": _list_known_repo_ids(),
            "message": (
                f"Registered new project {cleaned!r}."
                if project["created"]
                else f"Project {cleaned!r} already existed; display_name refreshed."
            ),
        }
