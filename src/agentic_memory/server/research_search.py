"""Research/web retrieval helpers for temporal-first public retrieval.

The public product contract for research memory is now:

- dense/vector retrieval may still seed the candidate set,
- temporal graph retrieval is the authoritative ranking path, and
- public/hosted callers must receive an explicit failure when the temporal path
  cannot run instead of a success-looking dense fallback.

Internal callers can still decide how to handle the raised
``TemporalRetrievalRequiredError``; this module no longer hides that failure by
quietly returning baseline rows.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic_memory.core.request_context import get_request_id
from agentic_memory.server.reranking import (
    build_yaml_card,
    candidate_limit_for_domain,
    rerank_documents,
)
from agentic_memory.server.temporal_contract import TemporalRetrievalRequiredError
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
    """Run research retrieval with temporal graph ranking as the required path.

    Dense/vector search still generates the initial candidate window because the
    temporal graph needs seeds to walk from. Once that baseline exists, the
    temporal path is required for any caller relying on the public research
    retrieval contract. If the bridge is unavailable, no project scope can be
    inferred, no temporal seeds can be produced, or the bridge returns no
    results, this function raises ``TemporalRetrievalRequiredError``.
    """

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
    candidate_rows: list[dict[str, Any]] = []
    mode = "temporal_graph"
    temporal_applied = True
    notes: list[str] = []

    def _raise_temporal_error(*, reason: str, message: str, error_type: str | None = None) -> None:
        logger.info(
            "web_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "web",
                "provider": getattr(pipeline._embedder, "provider", None),
                "fallback": reason,
                "error_type": error_type,
            },
        )
        raise TemporalRetrievalRequiredError(
            module="web",
            reason=reason,
            message=message,
            details={
                "project_id": project_id,
                "as_of": as_of,
            },
        )

    if bridge is None or not bridge.is_available():
        _raise_temporal_error(
            reason="temporal_bridge_unavailable",
            message="Temporal research retrieval is required, but the temporal bridge is unavailable.",
        )

    if project_id is None:
        _raise_temporal_error(
            reason="missing_project_scope",
            message="Temporal research retrieval is required, but no project-scoped research context could be inferred.",
        )

    seeds = collect_seed_entities(baseline_rows, limit=5)
    if not seeds:
        try:
            seeds = extract_query_seed_entities(query, pipeline._extractor)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_research query seed extraction failed: %s", exc)
            seeds = []

    if not seeds:
        _raise_temporal_error(
            reason="no_temporal_seeds",
            message="Temporal research retrieval is required, but no temporal seed entities were available for the query.",
        )

    try:
        temporal_payload = bridge.retrieve(
            project_id=project_id,
            seed_entities=seeds,
            as_of_us=parse_as_of_to_micros(as_of),
            max_edges=max(candidate_limit * 2, candidate_limit),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_research failed during temporal retrieval: %s", exc)
        _raise_temporal_error(
            reason="temporal_retrieve_failed",
            message="Temporal research retrieval failed before a ranked result set could be produced.",
            error_type=type(exc).__name__,
        )

    temporal_results = temporal_payload.get("results") or []
    if not temporal_results:
        _raise_temporal_error(
            reason="empty_temporal_result",
            message="Temporal research retrieval completed but returned no temporal results for this query.",
        )

    candidate_rows = _normalize_temporal_results(
        temporal_results,
        project_id=project_id,
    )
    notes.append("Temporal graph enrichment supplied the rerank candidate set.")

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
