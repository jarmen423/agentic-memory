"""Code-domain retrieval helpers, including optional graph-aware reranking.

The code graph already has a strong baseline retriever: semantic ANN search over
embedded code chunks. This module adds a second-stage graph reranker that uses a
non-temporal Personalized PageRank (PPR) walk over a high-confidence structural
subgraph.

Why the extra layer lives here instead of in ``KnowledgeGraphBuilder``:
- the graph builder is primarily an ingestion/write surface
- PPR is query-time ranking logic
- the rollout is intentionally guarded by a feature flag so baseline search can
  stay unchanged while graph quality hardening lands

The most important operational rule for agent-facing retrieval today is that
``CALLS`` edges are not trusted enough to drive ranking across repositories.
This module therefore exposes a retrieval-policy concept:

- ``safe``: semantic search only, no graph reranking
- ``graph_reranked``: semantic search plus graph reranking over
  ``IMPORTS``, ``DEFINES``, and ``HAS_METHOD``
- ``auto``: legacy behavior controlled by the feature flag

Every returned row carries a ``retrieval_provenance`` dictionary so MCP tools
and future agent surfaces can explain exactly what structural evidence was used.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from typing import Any, Iterable

from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from agentic_memory.server.reranking import (
    build_yaml_card,
    candidate_limit_for_domain,
    rerank_documents,
)

PPR_EDGE_WEIGHTS: dict[str, float] = {
    "IMPORTS": 1.0,
    "HAS_METHOD": 0.9,
    "DEFINES": 0.7,
}
PPR_RESTART_ALPHA = 0.2
PPR_MAX_ITERATIONS = 12
PPR_CONVERGENCE_EPSILON = 1e-6
PPR_MAX_HOPS = 2
AUTO_RETRIEVAL_POLICY = "auto"
SAFE_RETRIEVAL_POLICY = "safe"
GRAPH_RERANKED_POLICY = "graph_reranked"
VALID_RETRIEVAL_POLICIES = {
    AUTO_RETRIEVAL_POLICY,
    SAFE_RETRIEVAL_POLICY,
    GRAPH_RERANKED_POLICY,
}
SAFE_GRAPH_EDGE_TYPES = tuple(PPR_EDGE_WEIGHTS.keys())


def is_code_ppr_enabled() -> bool:
    """Return ``True`` when the code-side graph reranker is enabled."""
    raw = os.getenv("ENABLE_CODE_PPR", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def normalize_retrieval_policy(
    policy: str | None,
    *,
    allow_auto: bool,
) -> str | None:
    """Normalize one retrieval-policy string for agent-safe code search.

    Args:
        policy: Raw user-facing or internal policy string.
        allow_auto: Whether the internal ``auto`` policy is accepted.

    Returns:
        The normalized policy string, or ``None`` when invalid.
    """
    normalized = str(policy or SAFE_RETRIEVAL_POLICY).strip().lower()
    if normalized == AUTO_RETRIEVAL_POLICY and not allow_auto:
        return None
    if normalized in VALID_RETRIEVAL_POLICIES:
        return normalized
    return None


def search_code(
    graph: KnowledgeGraphBuilder,
    *,
    query: str,
    limit: int,
    repo_id: str | None = None,
    use_ppr: bool | None = None,
    retrieval_policy: str = AUTO_RETRIEVAL_POLICY,
) -> list[dict[str, Any]]:
    """Return code results using baseline semantic search or baseline + PPR.

    Args:
        graph: Live code graph builder used for baseline retrieval and Neo4j access.
        query: Natural-language code search query.
        limit: Maximum number of rows to return.
        repo_id: Optional explicit repo scope. Defaults to the graph builder repo.
        use_ppr: Optional override for the feature flag. Tests use this so they
            can exercise the PPR path deterministically.
        retrieval_policy: ``safe`` for semantic-only agent-safe retrieval,
            ``graph_reranked`` for structural reranking without ``CALLS``, or
            ``auto`` to preserve legacy feature-flag behavior.
    """
    normalized_policy = normalize_retrieval_policy(
        retrieval_policy,
        allow_auto=True,
    )
    if normalized_policy is None:
        valid = ", ".join(sorted(VALID_RETRIEVAL_POLICIES))
        raise ValueError(f"Invalid retrieval_policy '{retrieval_policy}'. Valid values: {valid}")

    resolved_repo_id = repo_id or graph.repo_id
    ppr_requested = _resolve_ppr_requested(
        retrieval_policy=normalized_policy,
        use_ppr=use_ppr,
    )
    ppr_enabled = ppr_requested and resolved_repo_id is not None
    baseline_limit = limit
    if ppr_enabled:
        baseline_limit = max(limit * 3, baseline_limit)
    baseline_limit = candidate_limit_for_domain("code", default=baseline_limit)
    baseline_rows = _run_baseline_search(
        graph,
        query=query,
        limit=baseline_limit,
        # Baseline semantic retrieval must stay inside the resolved repo scope,
        # even when the caller relies on the graph's default repo_id.
        repo_id=resolved_repo_id,
    )
    if not baseline_rows:
        return []

    if not ppr_enabled:
        notes = ["CALLS edges are excluded from ranking in safe retrieval."]
        if ppr_requested and resolved_repo_id is None:
            notes.append("Graph reranking was requested but no repo scope was available.")
        baseline_rows, rerank_response = _apply_code_rerank(
            query=query,
            rows=baseline_rows,
            limit=limit,
        )
        return _annotate_rows(
            baseline_rows[:limit],
            retrieval_policy=normalized_policy,
            retrieval_mode="semantic_only",
            graph_reranking_applied=False,
            graph_edge_types_used=[],
            notes=notes,
            rerank_response=rerank_response,
        )

    seed_refs = _seed_refs_from_baseline(baseline_rows)
    if not seed_refs:
        baseline_rows, rerank_response = _apply_code_rerank(
            query=query,
            rows=baseline_rows,
            limit=limit,
        )
        return _annotate_rows(
            baseline_rows[:limit],
            retrieval_policy=normalized_policy,
            retrieval_mode="semantic_only_fallback",
            graph_reranking_applied=False,
            graph_edge_types_used=[],
            notes=[
                "Graph reranking was requested, but the semantic hits did not map to graph seeds.",
                "CALLS edges remain excluded from ranking.",
            ],
            rerank_response=rerank_response,
        )

    neighborhood = _load_code_neighborhood(
        graph,
        repo_id=resolved_repo_id,
        seed_refs=seed_refs,
        max_hops=PPR_MAX_HOPS,
    )
    seed_ids = neighborhood["seed_ids"]
    adjacency = neighborhood["adjacency"]
    node_meta = neighborhood["node_meta"]
    if not seed_ids or not adjacency:
        baseline_rows, rerank_response = _apply_code_rerank(
            query=query,
            rows=baseline_rows,
            limit=limit,
        )
        return _annotate_rows(
            baseline_rows[:limit],
            retrieval_policy=normalized_policy,
            retrieval_mode="semantic_only_fallback",
            graph_reranking_applied=False,
            graph_edge_types_used=[],
            notes=[
                "Graph reranking was requested, but no structural neighborhood was available.",
                "CALLS edges remain excluded from ranking.",
            ],
            rerank_response=rerank_response,
        )

    ppr_scores = _run_personalized_page_rank(
        seed_ids=seed_ids,
        adjacency=adjacency,
        alpha=PPR_RESTART_ALPHA,
        max_iterations=PPR_MAX_ITERATIONS,
        epsilon=PPR_CONVERGENCE_EPSILON,
    )
    reranked_rows = _materialize_ranked_rows(
        baseline_rows=baseline_rows,
        node_meta=node_meta,
        ppr_scores=ppr_scores,
        repo_id=resolved_repo_id,
        limit=limit,
    )
    if reranked_rows:
        reranked_rows, rerank_response = _apply_code_rerank(
            query=query,
            rows=reranked_rows,
            limit=limit,
        )
        return _annotate_rows(
            reranked_rows,
            retrieval_policy=normalized_policy,
            retrieval_mode="semantic_plus_graph_rerank",
            graph_reranking_applied=True,
            graph_edge_types_used=list(SAFE_GRAPH_EDGE_TYPES),
            notes=[
                "Graph reranking used only high-confidence structural edges.",
                "CALLS edges are excluded from ranking until analyzer-backed coverage improves.",
            ],
            rerank_response=rerank_response,
        )
    baseline_rows, rerank_response = _apply_code_rerank(
        query=query,
        rows=baseline_rows,
        limit=limit,
    )
    return _annotate_rows(
        baseline_rows[:limit],
        retrieval_policy=normalized_policy,
        retrieval_mode="semantic_only_fallback",
        graph_reranking_applied=False,
        graph_edge_types_used=[],
        notes=[
            "Graph reranking produced no ranked rows, so semantic fallback was used.",
            "CALLS edges remain excluded from ranking.",
        ],
        rerank_response=rerank_response,
    )


def _resolve_ppr_requested(
    *,
    retrieval_policy: str,
    use_ppr: bool | None,
) -> bool:
    """Resolve whether graph reranking should be attempted for this request."""
    if use_ppr is not None:
        return bool(use_ppr)
    if retrieval_policy == SAFE_RETRIEVAL_POLICY:
        return False
    if retrieval_policy == GRAPH_RERANKED_POLICY:
        return True
    return is_code_ppr_enabled()


def _annotate_rows(
    rows: Iterable[dict[str, Any]],
    *,
    retrieval_policy: str,
    retrieval_mode: str,
    graph_reranking_applied: bool,
    graph_edge_types_used: list[str],
    notes: list[str],
    rerank_response: Any,
) -> list[dict[str, Any]]:
    """Attach retrieval provenance to every row for agent-facing inspection."""
    annotated_rows: list[dict[str, Any]] = []
    provenance = {
        "policy": retrieval_policy,
        "mode": retrieval_mode,
        "graph_reranking_applied": graph_reranking_applied,
        "graph_edge_types_used": list(graph_edge_types_used),
        "call_edges_used": False,
        "call_edge_policy": "excluded_from_ranking",
        "reranker_applied": bool(getattr(rerank_response, "applied", False)),
        "reranker_provider": getattr(rerank_response, "provider", None),
        "reranker_model": getattr(rerank_response, "model", None),
        "reranker_fallback_reason": getattr(rerank_response, "fallback_reason", None),
        "reranker_abstained": bool(getattr(rerank_response, "abstained", False)),
        "notes": list(notes),
    }
    for row in rows:
        enriched_row = dict(row)
        row_provenance = dict(provenance)
        candidate_sources = list(enriched_row.pop("_candidate_sources", []) or [])
        if candidate_sources:
            row_provenance["candidate_sources"] = candidate_sources
        if enriched_row.get("_dense_score") is not None:
            row_provenance["dense_score"] = float(enriched_row.get("_dense_score", 0.0) or 0.0)
        if enriched_row.get("_lexical_score") is not None:
            row_provenance["lexical_score"] = float(enriched_row.get("_lexical_score", 0.0) or 0.0)
        if enriched_row.get("rerank_score") is not None:
            row_provenance["rerank_score"] = float(enriched_row.get("rerank_score", 0.0) or 0.0)
        for hidden_key in ("_dense_rank", "_dense_rrf", "_lexical_rank", "_lexical_rrf", "_dense_score", "_lexical_score"):
            enriched_row.pop(hidden_key, None)
        enriched_row["retrieval_provenance"] = row_provenance
        annotated_rows.append(enriched_row)
    return annotated_rows


def _serialize_code_card(row: dict[str, Any]) -> str:
    """Serialize one code candidate into a compact YAML-like card."""

    labels = [str(label) for label in (row.get("labels") or [])]
    candidate_kind = labels[0] if labels else "Code"
    return build_yaml_card(
        [
            ("domain", "code"),
            ("candidate_kind", candidate_kind),
            ("name", row.get("name")),
            ("signature", row.get("sig")),
            ("path", row.get("path")),
            ("labels", labels),
            ("snippet", str(row.get("text") or "")[:800]),
        ]
    )


def _apply_code_rerank(
    *,
    query: str,
    rows: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], Any]:
    """Apply learned reranking to code rows while preserving baseline fields."""

    if not rows:
        return [], rerank_documents(query, [])

    serialized = [_serialize_code_card(row) for row in rows]
    response = rerank_documents(query, serialized, high_stakes=False)
    if not response.applied or response.abstained or not response.scores:
        return rows[:limit], response

    rerank_scores = {score.index: score.relevance_score for score in response.scores}
    reranked_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index not in rerank_scores:
            continue
        enriched = dict(row)
        enriched.setdefault("baseline_score", float(row.get("score", 0.0) or 0.0))
        enriched["rerank_score"] = rerank_scores[index]
        enriched["score"] = rerank_scores[index]
        reranked_rows.append(enriched)

    ordered = sorted(
        reranked_rows,
        key=lambda row: (
            -float(row.get("rerank_score", 0.0) or 0.0),
            -float(row.get("ppr_score", 0.0) or 0.0),
            -float(row.get("baseline_score", row.get("score", 0.0)) or 0.0),
            str(row.get("sig") or row.get("path") or ""),
        ),
    )
    return ordered[:limit], response


def _seed_refs_from_baseline(rows: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    """Convert baseline semantic hits into repo-scoped graph seed references."""
    refs: dict[str, list[str]] = {"functions": [], "classes": [], "files": []}
    for row in rows:
        labels = {str(label) for label in (row.get("labels") or [])}
        signature = str(row.get("sig") or "").strip()
        path = str(row.get("path") or "").strip()
        if "Function" in labels and signature:
            refs["functions"].append(signature)
        elif "Class" in labels and signature:
            refs["classes"].append(signature)
        elif path:
            refs["files"].append(path)
    return {key: _stable_dedupe(values) for key, values in refs.items()}


def _run_baseline_search(
    graph: KnowledgeGraphBuilder,
    *,
    query: str,
    limit: int,
    repo_id: str | None,
) -> list[dict[str, Any]]:
    """Run the underlying semantic search while preserving old call semantics."""
    if repo_id is None:
        return graph.semantic_search(query, limit=limit)
    return graph.semantic_search(query, limit=limit, repo_id=repo_id)


def _load_code_neighborhood(
    graph: KnowledgeGraphBuilder,
    *,
    repo_id: str,
    seed_refs: dict[str, list[str]],
    max_hops: int,
) -> dict[str, Any]:
    """Load a small repo-scoped structural neighborhood around the seed nodes."""
    node_meta: dict[int, dict[str, Any]] = {}
    adjacency: dict[int, list[tuple[int, float]]] = defaultdict(list)

    with graph.driver.session() as session:
        seed_rows = session.run(
            """
            MATCH (n)
            WHERE n.repo_id = $repo_id AND (
                (n:Function AND n.signature IN $function_sigs) OR
                (n:Class AND n.qualified_name IN $class_sigs) OR
                (n:File AND n.path IN $file_paths)
            )
            RETURN id(n) as node_id, labels(n) as labels, properties(n) as props
            """,
            repo_id=repo_id,
            function_sigs=seed_refs["functions"],
            class_sigs=seed_refs["classes"],
            file_paths=seed_refs["files"],
        )
        seed_ids = []
        for row in seed_rows:
            node_id = int(row["node_id"])
            seed_ids.append(node_id)
            node_meta[node_id] = {
                "labels": list(row["labels"] or []),
                "props": dict(row["props"] or {}),
            }

        frontier = list(seed_ids)
        visited = set(seed_ids)
        for _ in range(max_hops):
            if not frontier:
                break
            edge_rows = session.run(
                """
                UNWIND $frontier as frontier_id
                MATCH (a)-[r:IMPORTS|DEFINES|HAS_METHOD]-(b)
                WHERE a.repo_id = $repo_id
                  AND b.repo_id = $repo_id
                  AND (id(a) = frontier_id OR id(b) = frontier_id)
                RETURN DISTINCT
                    id(a) as source_id,
                    labels(a) as source_labels,
                    properties(a) as source_props,
                    type(r) as rel_type,
                    id(b) as target_id,
                    labels(b) as target_labels,
                    properties(b) as target_props
                """,
                repo_id=repo_id,
                frontier=frontier,
            )

            next_frontier: list[int] = []
            for row in edge_rows:
                source_id = int(row["source_id"])
                target_id = int(row["target_id"])
                rel_type = str(row["rel_type"])
                weight = PPR_EDGE_WEIGHTS.get(rel_type, 0.0)
                if weight <= 0:
                    continue

                node_meta.setdefault(
                    source_id,
                    {
                        "labels": list(row["source_labels"] or []),
                        "props": dict(row["source_props"] or {}),
                    },
                )
                node_meta.setdefault(
                    target_id,
                    {
                        "labels": list(row["target_labels"] or []),
                        "props": dict(row["target_props"] or {}),
                    },
                )
                adjacency[source_id].append((target_id, weight))
                adjacency[target_id].append((source_id, weight))

                if source_id not in visited:
                    visited.add(source_id)
                    next_frontier.append(source_id)
                if target_id not in visited:
                    visited.add(target_id)
                    next_frontier.append(target_id)

            frontier = next_frontier

    return {
        "seed_ids": seed_ids,
        "adjacency": dict(adjacency),
        "node_meta": node_meta,
    }


def _run_personalized_page_rank(
    *,
    seed_ids: list[int],
    adjacency: dict[int, list[tuple[int, float]]],
    alpha: float,
    max_iterations: int,
    epsilon: float,
) -> dict[int, float]:
    """Run a small in-memory Personalized PageRank walk."""
    if not seed_ids:
        return {}

    personalization = {node_id: 1.0 / len(seed_ids) for node_id in seed_ids}
    ranks = dict(personalization)
    all_nodes = set(adjacency) | set(seed_ids)

    for _ in range(max_iterations):
        next_ranks = {node_id: alpha * personalization.get(node_id, 0.0) for node_id in all_nodes}
        dangling_mass = 0.0

        for node_id in all_nodes:
            node_rank = ranks.get(node_id, 0.0)
            neighbors = adjacency.get(node_id, [])
            total_weight = sum(weight for _, weight in neighbors)
            if total_weight <= 0:
                dangling_mass += node_rank
                continue

            walk_mass = (1.0 - alpha) * node_rank
            for neighbor_id, weight in neighbors:
                next_ranks[neighbor_id] = next_ranks.get(neighbor_id, 0.0) + (
                    walk_mass * (weight / total_weight)
                )

        if dangling_mass:
            redistributed = (1.0 - alpha) * dangling_mass
            for node_id, seed_weight in personalization.items():
                next_ranks[node_id] = next_ranks.get(node_id, 0.0) + redistributed * seed_weight

        delta = sum(abs(next_ranks.get(node_id, 0.0) - ranks.get(node_id, 0.0)) for node_id in all_nodes)
        ranks = next_ranks
        if math.isfinite(delta) and delta < epsilon:
            break

    return ranks


def _materialize_ranked_rows(
    *,
    baseline_rows: list[dict[str, Any]],
    node_meta: dict[int, dict[str, Any]],
    ppr_scores: dict[int, float],
    repo_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Merge baseline scores and PPR scores into one ranked result list."""
    baseline_by_source: dict[str, dict[str, Any]] = {}
    max_baseline = max(float(row.get("score", 0.0) or 0.0) for row in baseline_rows) or 1.0
    max_ppr = max(ppr_scores.values()) if ppr_scores else 1.0

    for row in baseline_rows:
        source_id = _row_source_id(row)
        if source_id:
            baseline_by_source[source_id] = row

    ranked_rows: list[dict[str, Any]] = []
    for node_id, ppr_score in sorted(ppr_scores.items(), key=lambda item: item[1], reverse=True):
        meta = node_meta.get(node_id)
        if not meta:
            continue

        props = dict(meta.get("props") or {})
        labels = list(meta.get("labels") or [])
        source_id = _props_source_id(props, labels)
        if not source_id:
            continue

        baseline_row = baseline_by_source.get(source_id, {})
        baseline_score = float(baseline_row.get("score", 0.0) or 0.0)
        baseline_norm = baseline_score / max_baseline if max_baseline else 0.0
        ppr_norm = ppr_score / max_ppr if max_ppr else 0.0
        # Fixed blend: semantic remains primary; PPR nudges order without drowning ANN scores.
        combined_score = (0.6 * baseline_norm) + (0.4 * ppr_norm)

        ranked_rows.append(
            {
                "name": props.get("name") or props.get("path") or source_id,
                "sig": props.get("signature") or props.get("qualified_name") or props.get("path") or source_id,
                "score": combined_score,
                "baseline_score": baseline_score,
                "ppr_score": ppr_score,
                "text": baseline_row.get("text") or props.get("code") or props.get("path") or "",
                "path": props.get("path"),
                "repo_id": repo_id,
                "labels": labels,
            }
        )

    deduped: dict[str, dict[str, Any]] = {}
    for row in ranked_rows:
        source_id = _row_source_id(row)
        existing = deduped.get(source_id)
        if existing is None or float(row.get("score", 0.0)) > float(existing.get("score", 0.0)):
            deduped[source_id] = row

    ordered = sorted(
        deduped.values(),
        key=lambda row: (
            -float(row.get("score", 0.0) or 0.0),
            -float(row.get("baseline_score", 0.0) or 0.0),
            str(row.get("sig") or ""),
        ),
    )
    return ordered[:limit]


def _row_source_id(row: dict[str, Any]) -> str:
    """Return the canonical identifier for one result row."""
    return str(row.get("sig") or row.get("path") or row.get("name") or "").strip()


def _props_source_id(props: dict[str, Any], labels: list[str]) -> str:
    """Return the canonical identifier for one graph node."""
    if "Function" in labels:
        return str(props.get("signature") or "").strip()
    if "Class" in labels:
        return str(props.get("qualified_name") or "").strip()
    return str(props.get("path") or "").strip()


def _stable_dedupe(values: Iterable[str]) -> list[str]:
    """Return values with duplicates removed while preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
