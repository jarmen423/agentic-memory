"""Research/web retrieval helpers with optional learned reranking."""

from __future__ import annotations

import logging
from typing import Any

from agentic_memory.core.request_context import get_request_id
from agentic_memory.server.reranking import (
    build_yaml_card,
    candidate_limit_for_domain,
    rerank_documents,
)
from agentic_memory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
)
from agentic_memory.web.pipeline import ResearchIngestionPipeline

logger = logging.getLogger(__name__)


def filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Filter research rows by string compare on ``ingested_at``."""

    if as_of is None:
        return rows
    return [row for row in rows if (row.get("ingested_at") or "") <= as_of]


def dominant_project_id(rows: list[dict[str, Any]]) -> str | None:
    """Pick the project_id with the strongest cumulative score."""

    project_scores: dict[str, float] = {}
    for row in rows:
        project_id = row.get("project_id")
        if not project_id:
            continue
        key = str(project_id)
        project_scores[key] = project_scores.get(key, 0.0) + float(row.get("score", 1.0) or 1.0)
    if not project_scores:
        return None
    return max(project_scores.items(), key=lambda item: item[1])[0]


def _annotate_rows(
    rows: list[dict[str, Any]],
    *,
    mode: str,
    temporal_applied: bool,
    candidate_sources: list[str],
    rerank_response,
    notes: list[str],
) -> list[dict[str, Any]]:
    """Attach stable retrieval provenance to research rows."""

    annotated: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched["retrieval_provenance"] = {
            "module": "web",
            "mode": mode,
            "temporal_applied": temporal_applied,
            "candidate_sources": list(candidate_sources),
            "reranker_applied": bool(rerank_response.applied),
            "reranker_provider": rerank_response.provider,
            "reranker_model": rerank_response.model,
            "reranker_fallback_reason": rerank_response.fallback_reason,
            "reranker_abstained": bool(rerank_response.abstained),
            "notes": list(notes),
        }
        annotated.append(enriched)
    return annotated


def _serialize_research_card(row: dict[str, Any]) -> str:
    """Serialize one research candidate for hosted reranking."""

    if row.get("temporal_applied"):
        return build_yaml_card(
            [
                ("domain", "research"),
                ("candidate_kind", row.get("source_kind") or "research_temporal_hit"),
                ("subject", (row.get("subject") or {}).get("name")),
                ("predicate", row.get("predicate")),
                ("object", (row.get("object") or {}).get("name")),
                ("source_id", row.get("source_id")),
                ("source_authority", row.get("source_authority")),
                ("effective_date", row.get("effective_date")),
                ("jurisdiction", row.get("jurisdiction")),
                ("excerpt", row.get("text") or ""),
            ]
        )

    return build_yaml_card(
        [
            ("domain", "research"),
            ("candidate_kind", row.get("source_kind") or "research_baseline_hit"),
            ("question", row.get("research_question")),
            ("source_agent", row.get("source_agent")),
            ("source_key", row.get("source_key")),
            ("project_id", row.get("project_id")),
            ("source_authority", row.get("source_authority")),
            ("effective_date", row.get("effective_date")),
            ("jurisdiction", row.get("jurisdiction")),
            ("node_labels", row.get("node_labels") or []),
            ("excerpt", row.get("text") or ""),
        ]
    )


def _apply_research_rerank(
    query: str,
    rows: list[dict[str, Any]],
    *,
    limit: int,
    high_stakes: bool = False,
) -> tuple[list[dict[str, Any]], Any]:
    """Rerank research rows and preserve baseline/temporal provenance."""

    if not rows:
        response = rerank_documents(query, [])
        return [], response

    serialized = [_serialize_research_card(row) for row in rows]
    response = rerank_documents(query, serialized, high_stakes=high_stakes)
    if not response.applied or response.abstained or not response.scores:
        return rows[:limit], response

    scored_rows: list[dict[str, Any]] = []
    by_index = {score.index: score.relevance_score for score in response.scores}
    for index, row in enumerate(rows):
        if index not in by_index:
            continue
        enriched = dict(row)
        enriched["rerank_score"] = by_index[index]
        enriched["score"] = by_index[index]
        scored_rows.append(enriched)

    ordered = sorted(
        scored_rows,
        key=lambda row: (
            -float(row.get("rerank_score", 0.0) or 0.0),
            -float(row.get("temporal_score", 0.0) or 0.0),
            -float(row.get("baseline_score", 0.0) or 0.0),
            str(row.get("source_id") or row.get("content_hash") or ""),
        ),
    )
    return ordered[:limit], response


def _normalize_temporal_results(
    temporal_results: list[dict[str, Any]],
    *,
    project_id: str | None,
) -> list[dict[str, Any]]:
    """Normalize temporal graph payloads into a stable research-row shape."""

    normalized: list[dict[str, Any]] = []
    for ranked in temporal_results:
        confidence = float(ranked.get("confidence", 0.0) or 0.0)
        relevance = float(ranked.get("relevance", 0.0) or 0.0)
        evidence = (ranked.get("evidence") or [{}])[0]
        normalized.append(
            {
                "text": str(evidence.get("rawExcerpt") or ""),
                "score": confidence * relevance,
                "temporal_score": confidence * relevance,
                "baseline_score": None,
                "temporal_applied": True,
                "subject": ranked.get("subject") or {},
                "predicate": ranked.get("predicate") or "RELATED_TO",
                "object": ranked.get("object") or {},
                "confidence": confidence,
                "relevance": relevance,
                "source_kind": str(evidence.get("sourceKind") or "research"),
                "source_id": str(
                    evidence.get("sourceId")
                    or f"{(ranked.get('subject') or {}).get('name', 'unknown')}:{ranked.get('predicate', 'RELATED_TO')}:{(ranked.get('object') or {}).get('name', 'unknown')}"
                ),
                "project_id": project_id,
                "source_authority": evidence.get("authority"),
                "effective_date": evidence.get("effectiveDate"),
                "jurisdiction": evidence.get("jurisdiction"),
            }
        )
    return normalized


def search_research(
    pipeline: ResearchIngestionPipeline,
    *,
    query: str,
    limit: int,
    as_of: str | None,
    high_stakes: bool = False,
) -> list[dict[str, Any]]:
    """Run research retrieval with temporal enrichment and optional reranking."""

    safe_limit = max(1, int(limit))
    candidate_limit = candidate_limit_for_domain("web", default=max(safe_limit, 30))

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
            limit=candidate_limit,
            embedding=embedding,
        ).data()

    baseline_results = filter_rows_as_of(baseline_results, as_of)
    if not baseline_results:
        return []

    baseline_rows = []
    for row in baseline_results:
        enriched = dict(row)
        enriched["baseline_score"] = float(row.get("score", 0.0) or 0.0)
        enriched["temporal_score"] = None
        enriched["temporal_applied"] = False
        enriched["source_kind"] = (
            "research_finding"
            if "Finding" in (row.get("node_labels") or [])
            else "research_chunk"
        )
        enriched["source_id"] = str(
            row.get("content_hash") or row.get("research_question") or row.get("text") or ""
        )
        baseline_rows.append(enriched)

    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
    project_id = dominant_project_id(baseline_rows)
    candidate_rows = baseline_rows
    mode = "dense_only"
    temporal_applied = False
    notes: list[str] = []

    if bridge is not None and bridge.is_available() and project_id is not None:
        seeds = collect_seed_entities(baseline_rows, limit=5)
        if not seeds:
            try:
                seeds = extract_query_seed_entities(query, pipeline._extractor)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.warning("search_research query seed extraction failed: %s", exc)
                seeds = []

        if seeds:
            try:
                temporal_payload = bridge.retrieve(
                    project_id=project_id,
                    seed_entities=seeds,
                    as_of_us=parse_as_of_to_micros(as_of),
                    max_edges=max(candidate_limit * 2, candidate_limit),
                )
                temporal_results = temporal_payload.get("results") or []
                if temporal_results:
                    candidate_rows = _normalize_temporal_results(
                        temporal_results,
                        project_id=project_id,
                    )
                    mode = "temporal_graph"
                    temporal_applied = True
                    notes.append("Temporal graph enrichment supplied the rerank candidate set.")
                else:
                    logger.info(
                        "web_search_fallback",
                        extra={
                            "event": "temporal_fallback",
                            "request_id": get_request_id(),
                            "memory_module": "web",
                            "provider": getattr(pipeline._embedder, "provider", None),
                            "fallback": "empty_temporal_result",
                            "error_type": None,
                        },
                    )
                    notes.append("Temporal graph returned no results; dense baseline was used.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("search_research falling back after temporal failure: %s", exc)
                logger.warning(
                    "web_search_fallback",
                    extra={
                        "event": "temporal_fallback",
                        "request_id": get_request_id(),
                        "memory_module": "web",
                        "provider": getattr(pipeline._embedder, "provider", None),
                        "fallback": "temporal_retrieve_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                notes.append(f"Temporal retrieval failed; dense baseline was used ({type(exc).__name__}).")
        else:
            logger.info(
                "web_search_fallback",
                extra={
                    "event": "temporal_fallback",
                    "request_id": get_request_id(),
                    "memory_module": "web",
                    "provider": getattr(pipeline._embedder, "provider", None),
                    "fallback": "no_temporal_seeds",
                    "error_type": None,
                },
            )
            notes.append("No temporal seeds were available; dense baseline was used.")
    else:
        logger.info(
            "web_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "web",
                "provider": getattr(pipeline._embedder, "provider", None),
                "fallback": "temporal_bridge_unavailable",
                "error_type": None,
            },
        )
        notes.append("Temporal bridge unavailable or project scope missing; dense baseline was used.")

    reranked_rows, rerank_response = _apply_research_rerank(
        query,
        candidate_rows,
        limit=safe_limit,
        high_stakes=high_stakes,
    )
    return _annotate_rows(
        reranked_rows,
        mode=mode,
        temporal_applied=temporal_applied,
        candidate_sources=["dense"] if not temporal_applied else ["temporal_graph"],
        rerank_response=rerank_response,
        notes=notes,
    )
