"""Cross-module memory search shared by MCP tools and HTTP-style callers.

Normalizes hits from code (``KnowledgeGraphBuilder``), web research
(``ResearchIngestionPipeline`` + temporal bridge), and conversations
(``search_conversation_turns_sync``) into ``UnifiedMemoryHit`` rows, merges
them, sorts by score with stable tie-breaks, and returns ``UnifiedSearchResponse``.

The MCP tool ``search_all_memory`` in ``codememory.server.app`` formats the
``to_dict()`` payload for LLM consumption; REST layers can use the structured
response directly.

Attributes:
    VALID_MODULES: Set of allowed module filters: ``code``, ``web``,
        ``conversation``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from codememory.chat.pipeline import ConversationIngestionPipeline
from codememory.ingestion.graph import KnowledgeGraphBuilder
from codememory.server.result_types import UnifiedMemoryHit, UnifiedSearchResponse
from codememory.server.tools import search_conversation_turns_sync
from codememory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
)
from codememory.web.pipeline import ResearchIngestionPipeline

logger = logging.getLogger(__name__)

VALID_MODULES = {"code", "web", "conversation"}


def _clip_excerpt(text: str | None, *, length: int = 300) -> str:
    """Return up to ``length`` characters of ``text`` for UI or MCP excerpts.

    Args:
        text: Source string; None becomes empty.
        length: Maximum characters (default 300).

    Returns:
        Prefix of ``text`` at most ``length`` chars.
    """
    return (text or "")[:length]


def _normalize_modules(modules: Iterable[str] | None) -> list[str]:
    """Expand None to all modules; dedupe and filter to ``VALID_MODULES`` order.

    Args:
        modules: Iterable of module names, or None for all three.

    Returns:
        Non-empty ordered list subset of code/web/conversation.
    """
    if modules is None:
        return ["code", "web", "conversation"]
    normalized: list[str] = []
    for module in modules:
        lowered = module.strip().lower()
        if lowered in VALID_MODULES and lowered not in normalized:
            normalized.append(lowered)
    return normalized or ["code", "web", "conversation"]


def _filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Keep rows with ``ingested_at`` less than or equal to ``as_of`` (string compare)."""
    if as_of is None:
        return rows
    return [row for row in rows if (row.get("ingested_at") or "") <= as_of]


def _dominant_project_id(rows: list[dict[str, Any]]) -> str | None:
    """Choose ``project_id`` with the highest sum of row ``score`` for temporal routing."""
    project_scores: dict[str, float] = {}
    for row in rows:
        project_id = row.get("project_id")
        if not project_id:
            continue
        project_scores[str(project_id)] = project_scores.get(str(project_id), 0.0) + float(
            row.get("score", 1.0) or 1.0
        )
    if not project_scores:
        return None
    return max(project_scores.items(), key=lambda item: item[1])[0]


def _normalize_code_results(
    graph: KnowledgeGraphBuilder,
    *,
    query: str,
    limit: int,
) -> list[UnifiedMemoryHit]:
    """Vector-search the code graph and map rows to ``UnifiedMemoryHit``."""
    rows = graph.semantic_search(query, limit=limit)
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        sig = str(row.get("sig") or row.get("name") or "")
        hits.append(
            UnifiedMemoryHit(
                module="code",
                source_kind="code_entity",
                source_id=sig,
                title=str(row.get("name") or sig or "Unknown"),
                excerpt=_clip_excerpt(str(row.get("text") or "")),
                score=score,
                baseline_score=score,
                temporal_applied=False,
                metadata={
                    "signature": row.get("sig"),
                    "name": row.get("name"),
                },
            )
        )
    return hits


def _normalize_research_temporal_results(
    rows: list[dict[str, Any]],
) -> list[UnifiedMemoryHit]:
    """Convert temporal bridge research rows into ``UnifiedMemoryHit`` (web module)."""
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        confidence = float(row.get("confidence", 0.0) or 0.0)
        relevance = float(row.get("relevance", 0.0) or 0.0)
        evidence = (row.get("evidence") or [{}])[0]
        subject = (row.get("subject") or {}).get("name", "unknown")
        predicate = row.get("predicate", "RELATED_TO")
        obj = (row.get("object") or {}).get("name", "unknown")
        hits.append(
            UnifiedMemoryHit(
                module="web",
                source_kind=str(evidence.get("sourceKind") or "research"),
                source_id=str(evidence.get("sourceId") or f"{subject}:{predicate}:{obj}"),
                title=f"{subject} -[{predicate}]-> {obj}",
                excerpt=_clip_excerpt(str(evidence.get("rawExcerpt") or "")),
                score=confidence * relevance,
                temporal_score=confidence * relevance,
                temporal_applied=True,
                metadata={
                    "subject": row.get("subject"),
                    "predicate": predicate,
                    "object": row.get("object"),
                    "confidence": confidence,
                    "relevance": relevance,
                    "evidence": row.get("evidence") or [],
                },
            )
        )
    return hits


def _normalize_research_baseline_results(
    rows: list[dict[str, Any]],
) -> list[UnifiedMemoryHit]:
    """Convert vector baseline research rows into ``UnifiedMemoryHit`` (web module)."""
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        labels = row.get("node_labels", []) or []
        source_kind = (
            "research_finding" if "Finding" in labels else "research_chunk" if "Chunk" in labels else "research"
        )
        score = float(row.get("score", 0.0) or 0.0)
        source_id = str(row.get("content_hash") or row.get("text") or row.get("research_question") or "")
        hits.append(
            UnifiedMemoryHit(
                module="web",
                source_kind=source_kind,
                source_id=source_id,
                title=row.get("research_question"),
                excerpt=_clip_excerpt(str(row.get("text") or "")),
                score=score,
                baseline_score=score,
                temporal_applied=False,
                metadata={
                    "source_agent": row.get("source_agent"),
                    "confidence": row.get("confidence"),
                    "source_key": row.get("source_key"),
                    "project_id": row.get("project_id"),
                    "node_labels": labels,
                },
            )
        )
    return hits


def _normalize_conversation_results(
    rows: list[dict[str, Any]],
    *,
    temporal_applied: bool,
) -> list[UnifiedMemoryHit]:
    """Map conversation turn dicts to ``UnifiedMemoryHit`` with temporal flags."""
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        session_id = str(row.get("session_id") or "")
        turn_index = int(row.get("turn_index") or 0)
        hits.append(
            UnifiedMemoryHit(
                module="conversation",
                source_kind="conversation_turn",
                source_id=f"{session_id}:{turn_index}",
                title=f"{row.get('role', 'unknown')} turn",
                excerpt=_clip_excerpt(str(row.get("content") or "")),
                score=score,
                baseline_score=None if temporal_applied else score,
                temporal_score=score if temporal_applied else None,
                temporal_applied=temporal_applied,
                metadata={
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "role": row.get("role"),
                    "source_agent": row.get("source_agent"),
                    "timestamp": row.get("timestamp"),
                    "ingested_at": row.get("ingested_at"),
                    "entities": row.get("entities") or [],
                    "entity_types": row.get("entity_types") or [],
                },
            )
        )
    return hits


def _search_research_structured(
    pipeline: ResearchIngestionPipeline,
    *,
    query: str,
    limit: int,
    as_of: str | None,
) -> list[UnifiedMemoryHit]:
    """Research vector query plus optional temporal rerank; returns unified hits."""
    embedding = pipeline._embedder.embed(query)
    with pipeline._conn.session() as session:  # type: ignore[attr-defined]
        baseline_results = session.run(
            """
            CALL db.index.vector.queryNodes('research_embeddings', $limit, $embedding)
            YIELD node, score
            RETURN
                node.text AS text,
                node.source_agent AS source_agent,
                node.research_question AS research_question,
                node.confidence AS confidence,
                node.source_key AS source_key,
                node.content_hash AS content_hash,
                node.project_id AS project_id,
                node.ingested_at AS ingested_at,
                node.entities AS entities,
                node.entity_types AS entity_types,
                labels(node) AS node_labels,
                score
            ORDER BY score DESC
            """,
            limit=max(1, int(limit)),
            embedding=embedding,
        ).data()

    baseline_results = _filter_rows_as_of(baseline_results, as_of)
    if not baseline_results:
        return []

    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
    project_id = _dominant_project_id(baseline_results)
    if bridge is not None and bridge.is_available() and project_id is not None:
        seeds = collect_seed_entities(baseline_results, limit=5)
        if not seeds:
            try:
                seeds = extract_query_seed_entities(query, pipeline._extractor)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.warning("search_all_memory web query seed extraction failed: %s", exc)
                seeds = []
        if seeds:
            try:
                temporal_payload = bridge.retrieve(
                    project_id=project_id,
                    seed_entities=seeds,
                    as_of_us=parse_as_of_to_micros(as_of),
                    max_edges=max(limit * 2, limit),
                )
                temporal_results = temporal_payload.get("results") or []
                if temporal_results:
                    return _normalize_research_temporal_results(temporal_results)[:limit]
            except Exception as exc:  # noqa: BLE001
                logger.warning("search_all_memory web module falling back after temporal failure: %s", exc)

    return _normalize_research_baseline_results(baseline_results)[:limit]


def _search_conversation_structured(
    pipeline: ConversationIngestionPipeline,
    *,
    query: str,
    project_id: str | None,
    limit: int,
    as_of: str | None,
) -> list[UnifiedMemoryHit]:
    """Run ``search_conversation_turns_sync`` and normalize rows for unified ranking."""
    results = search_conversation_turns_sync(
        pipeline,
        query=query,
        project_id=project_id,
        role=None,
        limit=limit,
        as_of=as_of,
        log_prefix="search_all_memory.conversation",
    )
    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
    temporal_applied = bool(project_id and bridge is not None and bridge.is_available())
    return _normalize_conversation_results(results, temporal_applied=temporal_applied)


def _sort_hits(hits: list[UnifiedMemoryHit], limit: int) -> list[UnifiedMemoryHit]:
    """Sort by descending score, then temporal preference, module, and ``source_id``."""
    ordered = sorted(
        hits,
        key=lambda hit: (
            -float(hit.score),
            0 if hit.temporal_applied else 1,
            hit.module,
            hit.source_id,
        ),
    )
    return ordered[:limit]


def search_all_memory_sync(
    *,
    query: str,
    limit: int = 10,
    project_id: str | None = None,
    as_of: str | None = None,
    modules: Iterable[str] | None = None,
    graph: KnowledgeGraphBuilder | None = None,
    research_pipeline: ResearchIngestionPipeline | None = None,
    conversation_pipeline: ConversationIngestionPipeline | None = None,
) -> UnifiedSearchResponse:
    """Query selected modules, merge hits, sort, and record non-fatal failures.

    A module is skipped when its dependency (``graph``, ``research_pipeline``,
    or ``conversation_pipeline``) is None. Exceptions inside a module's
    ``try`` block are logged and appended to ``errors`` without aborting other
    modules.

    Args:
        query: Shared natural language query for all modules.
        limit: Cap on returned hits after global sort (minimum 1).
        project_id: Conversation/temporal scope; may be None for code-only use.
        as_of: Optional ISO timestamp string for ingested-at filtering.
        modules: Iterable of module names or None for all ``VALID_MODULES``.
        graph: Code graph builder; required for code hits.
        research_pipeline: Web pipeline; required for web hits.
        conversation_pipeline: Chat pipeline; required for conversation hits.

    Returns:
        ``UnifiedSearchResponse`` with sorted ``results`` and any ``errors``.
    """
    safe_limit = max(1, int(limit))
    selected_modules = _normalize_modules(modules)
    hits: list[UnifiedMemoryHit] = []
    errors: list[dict[str, str]] = []

    if "code" in selected_modules and graph is not None:
        try:
            hits.extend(_normalize_code_results(graph, query=query, limit=safe_limit))
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_all_memory code module failed: %s", exc)
            errors.append({"module": "code", "message": str(exc)})

    if "web" in selected_modules and research_pipeline is not None:
        try:
            hits.extend(
                _search_research_structured(
                    research_pipeline,
                    query=query,
                    limit=safe_limit,
                    as_of=as_of,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_all_memory web module failed: %s", exc)
            errors.append({"module": "web", "message": str(exc)})

    if "conversation" in selected_modules and conversation_pipeline is not None:
        try:
            hits.extend(
                _search_conversation_structured(
                    conversation_pipeline,
                    query=query,
                    project_id=project_id,
                    limit=safe_limit,
                    as_of=as_of,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_all_memory conversation module failed: %s", exc)
            errors.append({"module": "conversation", "message": str(exc)})

    return UnifiedSearchResponse(results=_sort_hits(hits, safe_limit), errors=errors)
