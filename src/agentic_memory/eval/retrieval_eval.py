"""Gold-query retrieval evaluation for Agentic Memory.

This module provides the legitimate retrieval-quality evaluation path discussed
in the reranking plan. It is intentionally different from unit tests:

- unit tests verify logic and contracts
- this module measures retrieval outcomes against labeled queries

Two evaluation tracks are supported:

1. ``smoke``: deterministic fixture-backed corpora, safe for CI
2. ``live``: runs against the current configured repo/pipelines and whatever
   memory has already been ingested into Neo4j
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import math
import statistics
import time
from typing import Any, Sequence
from unittest.mock import patch

from agentic_memory.chat.pipeline import ConversationIngestionPipeline
from agentic_memory.cli import _build_code_graph_builder, _resolve_repo_and_config
from agentic_memory.server import code_search, research_search, tools
from agentic_memory.server.reranking import RerankResponse, RerankScore
from agentic_memory.web.pipeline import ResearchIngestionPipeline
from am_server.dependencies import get_conversation_pipeline, get_pipeline

DEFAULT_POOL_LIMIT = 10
DEFAULT_MODE_BY_DOMAIN = {
    "code": "graph_rerank",
    "research": "temporal_rerank",
    "conversation": "temporal_rerank",
}
SMOKE_CORPUS_PATH = Path("bench/fixtures/eval/smoke-corpus.json")
EVAL_FIXTURE_DIR = Path("bench/fixtures/eval")


@dataclass(slots=True)
class EvalQuery:
    """One gold query row loaded from JSONL."""

    query_id: str
    domain: str
    query: str
    expected_ids: list[str]
    project_id: str | None = None
    as_of: str | None = None
    high_stakes: bool = False
    graded_relevance: dict[str, int] = field(default_factory=dict)
    notes: str | None = None
    authority: str | None = None
    effective_date: str | None = None
    jurisdiction: str | None = None
    expect_no_result: bool = False


@dataclass(slots=True)
class EvalMetrics:
    """Metrics for one query under one retrieval mode."""

    recall_at_10: float
    recall_at_pool: float
    mrr_at_10: float
    ndcg_at_10: float
    success_at_5: float
    latency_ms: float
    result_count: int
    rerank_applied: bool
    rerank_fallback_reason: str | None
    rerank_provider: str | None
    rerank_abstained: bool


@dataclass(slots=True)
class QueryModeResult:
    """Result payload for one query-mode execution."""

    query_id: str
    domain: str
    mode: str
    expected_ids: list[str]
    returned_ids: list[str]
    metrics: EvalMetrics


@dataclass(slots=True)
class AggregateMetrics:
    """Aggregate metrics for one domain/mode slice."""

    query_count: int
    recall_at_10: float
    recall_at_pool: float
    mrr_at_10: float
    ndcg_at_10: float
    success_at_5: float
    latency_p50_ms: float
    latency_p95_ms: float
    rerank_applied_rate: float
    rerank_fallback_rate: float
    rerank_abstained_rate: float


@dataclass(slots=True)
class EvalReport:
    """Serialized report format written to JSON and Markdown."""

    backend: str
    profile: str
    pool_limit: int
    aggregates: dict[str, dict[str, AggregateMetrics]]
    results: list[QueryModeResult]


class SmokeEmbedder:
    """Minimal embedder that remembers the last query for fixture lookup."""

    def __init__(self, provider: str = "smoke") -> None:
        self.provider = provider
        self.last_query: str = ""

    def embed(self, query: str) -> list[float]:
        self.last_query = query
        return [0.1, 0.2, 0.3]


class SmokeExtractor:
    """Minimal entity extractor used by temporal seed fallbacks."""

    def extract(self, query: str) -> list[dict[str, str]]:
        tokens = [token for token in query.split() if len(token) > 3]
        return [{"name": token.title(), "type": "concept"} for token in tokens[:3]]


class SmokeBridge:
    """Fixture-backed temporal bridge used in smoke evaluation."""

    def __init__(self, rows_by_query: dict[str, list[dict[str, Any]]], *, available: bool) -> None:
        self._rows_by_query = rows_by_query
        self._available = available
        self.last_query: str = ""

    def is_available(self) -> bool:
        return self._available

    def retrieve(self, **_: Any) -> dict[str, Any]:
        return {"results": self._rows_by_query.get(self.last_query, [])}


class SmokeSessionResult:
    """Simple Neo4j-like result object with a ``data()`` method."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def data(self) -> list[dict[str, Any]]:
        return list(self._rows)


class SmokeSessionContext:
    """Context manager wrapper for fixture-backed sessions."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def __enter__(self) -> Any:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class SmokeConnection:
    """Expose ``session()`` like the real Neo4j connection manager."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def session(self) -> SmokeSessionContext:
        return SmokeSessionContext(self._session)


class SmokeResearchSession:
    """Session that returns baseline research rows for the current query."""

    def __init__(self, embedder: SmokeEmbedder, rows_by_query: dict[str, list[dict[str, Any]]]) -> None:
        self._embedder = embedder
        self._rows_by_query = rows_by_query

    def run(self, *_: Any, **__: Any) -> SmokeSessionResult:
        return SmokeSessionResult(self._rows_by_query.get(self._embedder.last_query, []))


class SmokeGraph:
    """Code graph double with semantic baseline rows and graph neighborhoods."""

    def __init__(
        self,
        *,
        repo_id: str,
        baseline_rows_by_query: dict[str, list[dict[str, Any]]],
        neighborhoods_by_query: dict[str, dict[str, Any]],
    ) -> None:
        self.repo_id = repo_id
        self._baseline_rows_by_query = baseline_rows_by_query
        self._neighborhoods_by_query = neighborhoods_by_query
        self.last_query: str = ""

    def semantic_search(self, query: str, limit: int, repo_id: str | None = None) -> list[dict[str, Any]]:
        self.last_query = query
        rows = self._baseline_rows_by_query.get(query, [])
        return [dict(row, repo_id=repo_id or self.repo_id) for row in rows[:limit]]


def load_eval_queries(path: Path) -> list[EvalQuery]:
    """Load one JSONL gold query file."""

    rows: list[EvalQuery] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        expected_ids = payload.get("expected_ids") or []
        if not payload.get("query_id") or not payload.get("domain") or not payload.get("query"):
            raise ValueError(f"Invalid eval fixture row in {path}: missing query_id/domain/query")
        if not isinstance(expected_ids, list) or not all(isinstance(item, str) for item in expected_ids):
            raise ValueError(f"Invalid expected_ids in {path}: {payload.get('query_id')}")
        rows.append(
            EvalQuery(
                query_id=str(payload["query_id"]),
                domain=str(payload["domain"]),
                query=str(payload["query"]),
                expected_ids=list(expected_ids),
                project_id=payload.get("project_id"),
                as_of=payload.get("as_of"),
                high_stakes=bool(payload.get("high_stakes", False)),
                graded_relevance=dict(payload.get("graded_relevance") or {}),
                notes=payload.get("notes"),
                authority=payload.get("authority"),
                effective_date=payload.get("effective_date"),
                jurisdiction=payload.get("jurisdiction"),
                expect_no_result=bool(payload.get("expect_no_result", False)),
            )
        )
    return rows


def load_eval_profile(profile: str) -> list[EvalQuery]:
    """Load all domain query files for one profile name."""

    normalized = profile.strip().lower()
    paths = [
        EVAL_FIXTURE_DIR / f"code-{normalized}.jsonl",
        EVAL_FIXTURE_DIR / f"research-{normalized}.jsonl",
        EVAL_FIXTURE_DIR / f"conversation-{normalized}.jsonl",
    ]
    queries: list[EvalQuery] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing eval fixture file: {path}")
        queries.extend(load_eval_queries(path))
    return queries


def load_smoke_corpus(path: Path = SMOKE_CORPUS_PATH) -> dict[str, Any]:
    """Load the deterministic smoke corpus used in CI."""

    return json.loads(path.read_text(encoding="utf-8"))


def _rank_of_first_relevant(returned_ids: list[str], relevant_ids: set[str], *, limit: int) -> int | None:
    for index, candidate_id in enumerate(returned_ids[:limit], start=1):
        if candidate_id in relevant_ids:
            return index
    return None


def _dcg(returned_ids: list[str], graded_relevance: dict[str, int], *, limit: int) -> float:
    dcg = 0.0
    for rank, candidate_id in enumerate(returned_ids[:limit], start=1):
        gain = float(graded_relevance.get(candidate_id, 0))
        if gain <= 0:
            continue
        dcg += gain / math.log2(rank + 1)
    return dcg


def compute_metrics(
    *,
    returned_ids: list[str],
    expected_ids: list[str],
    graded_relevance: dict[str, int],
    latency_ms: float,
    result_count: int,
    rerank_applied: bool,
    rerank_fallback_reason: str | None,
    rerank_provider: str | None,
    rerank_abstained: bool,
    pool_limit: int,
) -> EvalMetrics:
    """Compute query-level retrieval metrics from returned ids and gold labels."""

    relevant = set(expected_ids)
    hit_rank_10 = _rank_of_first_relevant(returned_ids, relevant, limit=10)
    hit_rank_pool = _rank_of_first_relevant(returned_ids, relevant, limit=pool_limit)

    normalized_relevance = dict(graded_relevance) or {candidate_id: 1 for candidate_id in expected_ids}
    ideal_ids = [
        candidate_id
        for candidate_id, _score in sorted(
            normalized_relevance.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]
    ideal_dcg = _dcg(ideal_ids, normalized_relevance, limit=10)
    actual_dcg = _dcg(returned_ids, normalized_relevance, limit=10)

    return EvalMetrics(
        recall_at_10=1.0 if hit_rank_10 is not None else 0.0,
        recall_at_pool=1.0 if hit_rank_pool is not None else 0.0,
        mrr_at_10=(1.0 / hit_rank_10) if hit_rank_10 is not None else 0.0,
        ndcg_at_10=(actual_dcg / ideal_dcg) if ideal_dcg else 0.0,
        success_at_5=1.0 if hit_rank_10 is not None and hit_rank_10 <= 5 else 0.0,
        latency_ms=latency_ms,
        result_count=result_count,
        rerank_applied=rerank_applied,
        rerank_fallback_reason=rerank_fallback_reason,
        rerank_provider=rerank_provider,
        rerank_abstained=rerank_abstained,
    )


def _normalize_code_id(row: dict[str, Any]) -> str:
    return str(row.get("sig") or row.get("path") or "")


def _normalize_research_id(row: dict[str, Any]) -> str:
    source_kind = str(row.get("source_kind") or "research")
    source_id = str(row.get("source_id") or row.get("content_hash") or row.get("text") or "")
    return f"{source_kind}:{source_id}"


def _normalize_conversation_id(row: dict[str, Any]) -> str:
    return f"{row.get('session_id')}:{row.get('turn_index')}"


def _deterministic_rerank_documents(
    query: str,
    documents: Sequence[str],
    *,
    high_stakes: bool = False,
) -> RerankResponse:
    """Local reranker used in smoke mode so CI never depends on external APIs."""

    tokens = {token for token in query.lower().split() if len(token) > 2}
    scored: list[tuple[int, float]] = []
    for index, document in enumerate(documents):
        lowered = document.lower()
        score = sum(1.0 for token in tokens if token in lowered)
        score += max(0.0, min(len(document) / 1000.0, 0.2))
        scored.append((index, score))
    ordered = sorted(scored, key=lambda item: (-item[1], item[0]))
    if not ordered:
        return RerankResponse(applied=False, fallback_reason="no_documents", high_stakes=high_stakes)
    top_score = ordered[0][1]
    abstained = bool(high_stakes and top_score < 1.0)
    return RerankResponse(
        applied=True,
        provider="deterministic_smoke",
        model="local-overlap",
        scores=[RerankScore(index=index, relevance_score=score) for index, score in ordered],
        abstained=abstained,
        high_stakes=high_stakes,
        top_score=top_score,
    )


def _patch_smoke_rerankers(stack: ExitStack) -> None:
    """Replace hosted reranking with deterministic local scoring in smoke mode."""

    stack.enter_context(
        patch("agentic_memory.server.code_search.rerank_documents", _deterministic_rerank_documents)
    )
    stack.enter_context(
        patch("agentic_memory.server.research_search.rerank_documents", _deterministic_rerank_documents)
    )
    stack.enter_context(
        patch("agentic_memory.server.tools.rerank_documents", _deterministic_rerank_documents)
    )


def _serialize_report(report: EvalReport) -> dict[str, Any]:
    """Convert nested dataclasses into plain JSON-friendly structures."""

    return {
        "backend": report.backend,
        "profile": report.profile,
        "pool_limit": report.pool_limit,
        "aggregates": {
            domain: {mode: asdict(metrics) for mode, metrics in modes.items()}
            for domain, modes in report.aggregates.items()
        },
        "results": [
            {
                "query_id": row.query_id,
                "domain": row.domain,
                "mode": row.mode,
                "expected_ids": row.expected_ids,
                "returned_ids": row.returned_ids,
                "metrics": asdict(row.metrics),
            }
            for row in report.results
        ],
    }


def _aggregate_mode(rows: list[QueryModeResult]) -> AggregateMetrics:
    """Aggregate query-level metrics into one domain/mode summary."""

    latencies = [row.metrics.latency_ms for row in rows]
    rerank_rows = [row for row in rows if row.metrics.rerank_applied]
    fallback_rows = [row for row in rows if row.metrics.rerank_fallback_reason]
    abstained_rows = [row for row in rows if row.metrics.rerank_abstained]

    return AggregateMetrics(
        query_count=len(rows),
        recall_at_10=statistics.mean(row.metrics.recall_at_10 for row in rows),
        recall_at_pool=statistics.mean(row.metrics.recall_at_pool for row in rows),
        mrr_at_10=statistics.mean(row.metrics.mrr_at_10 for row in rows),
        ndcg_at_10=statistics.mean(row.metrics.ndcg_at_10 for row in rows),
        success_at_5=statistics.mean(row.metrics.success_at_5 for row in rows),
        latency_p50_ms=statistics.median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        rerank_applied_rate=len(rerank_rows) / len(rows),
        rerank_fallback_rate=len(fallback_rows) / len(rows),
        rerank_abstained_rate=len(abstained_rows) / len(rows),
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Return a simple inclusive percentile for small eval sample sizes."""

    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _report_markdown(report: EvalReport) -> str:
    """Render the final Markdown report written to disk."""

    lines = [
        "# Retrieval Eval Report",
        "",
        f"- Backend: `{report.backend}`",
        f"- Profile: `{report.profile}`",
        f"- Pool limit: `{report.pool_limit}`",
        "",
        "## Aggregates",
        "",
    ]
    for domain, modes in sorted(report.aggregates.items()):
        lines.append(f"### {domain.capitalize()}")
        lines.append("")
        lines.append(
            "| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for mode, metrics in sorted(modes.items()):
            lines.append(
                f"| {mode} | {metrics.query_count} | {metrics.recall_at_10:.2f} | "
                f"{metrics.recall_at_pool:.2f} | {metrics.mrr_at_10:.2f} | "
                f"{metrics.ndcg_at_10:.2f} | {metrics.success_at_5:.2f} | "
                f"{metrics.latency_p50_ms:.2f} | {metrics.latency_p95_ms:.2f} | "
                f"{metrics.rerank_applied_rate:.2%} | {metrics.rerank_fallback_rate:.2%} | "
                f"{metrics.rerank_abstained_rate:.2%} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _mode_rows(
    results: list[QueryModeResult],
    *,
    domain: str,
    mode: str,
) -> list[QueryModeResult]:
    return [row for row in results if row.domain == domain and row.mode == mode]


def _smoke_code_modes(graph: SmokeGraph, query: EvalQuery, *, pool_limit: int) -> list[QueryModeResult]:
    """Evaluate all code modes for one smoke query."""

    results: list[QueryModeResult] = []
    for mode_name, retrieval_policy, use_ppr in (
        ("baseline", code_search.SAFE_RETRIEVAL_POLICY, False),
        ("graph", code_search.GRAPH_RERANKED_POLICY, True),
        ("graph_rerank", code_search.GRAPH_RERANKED_POLICY, True),
    ):
        with ExitStack() as stack:
            if mode_name == "graph_rerank":
                _patch_smoke_rerankers(stack)
            else:
                stack.enter_context(
                    patch(
                        "agentic_memory.server.code_search.rerank_documents",
                        lambda query, documents, high_stakes=False: RerankResponse(
                            applied=False,
                            fallback_reason="disabled_for_eval_mode",
                            high_stakes=high_stakes,
                        ),
                    )
                )
            stack.enter_context(
                patch(
                    "agentic_memory.server.code_search._load_code_neighborhood",
                    lambda graph_obj, **kwargs: graph_obj._neighborhoods_by_query.get(graph_obj.last_query, {}),
                )
            )
            started = time.perf_counter()
            rows = code_search.search_code(
                graph,
                query=query.query,
                limit=pool_limit,
                use_ppr=use_ppr,
                retrieval_policy=retrieval_policy,
            )
            latency_ms = (time.perf_counter() - started) * 1000
        returned_ids = [_normalize_code_id(row) for row in rows]
        provenance = dict((rows[0].get("retrieval_provenance") or {})) if rows else {}
        results.append(
            QueryModeResult(
                query_id=query.query_id,
                domain=query.domain,
                mode=mode_name,
                expected_ids=query.expected_ids,
                returned_ids=returned_ids,
                metrics=compute_metrics(
                    returned_ids=returned_ids,
                    expected_ids=query.expected_ids,
                    graded_relevance=query.graded_relevance,
                    latency_ms=latency_ms,
                    result_count=len(rows),
                    rerank_applied=bool(provenance.get("reranker_applied", False)),
                    rerank_fallback_reason=provenance.get("reranker_fallback_reason"),
                    rerank_provider=provenance.get("reranker_provider"),
                    rerank_abstained=bool(provenance.get("reranker_abstained", False)),
                    pool_limit=pool_limit,
                ),
            )
        )
    return results


def _smoke_research_modes(
    pipeline: ResearchIngestionPipeline,
    query: EvalQuery,
    *,
    pool_limit: int,
) -> list[QueryModeResult]:
    """Evaluate all research modes for one smoke query."""

    results: list[QueryModeResult] = []
    for mode_name, temporal_available, rerank_enabled in (
        ("baseline", False, False),
        ("temporal", True, False),
        ("temporal_rerank", True, True),
    ):
        with ExitStack() as stack:
            if rerank_enabled:
                _patch_smoke_rerankers(stack)
            else:
                stack.enter_context(
                    patch(
                        "agentic_memory.server.research_search.rerank_documents",
                        lambda query, documents, high_stakes=False: RerankResponse(
                            applied=False,
                            fallback_reason="disabled_for_eval_mode",
                            high_stakes=high_stakes,
                        ),
                    )
                )
            pipeline._temporal_bridge._available = temporal_available  # type: ignore[attr-defined]
            pipeline._temporal_bridge.last_query = query.query  # type: ignore[attr-defined]
            started = time.perf_counter()
            rows = research_search.search_research(
                pipeline,
                query=query.query,
                limit=pool_limit,
                as_of=query.as_of,
                high_stakes=query.high_stakes,
            )
            latency_ms = (time.perf_counter() - started) * 1000
        returned_ids = [_normalize_research_id(row) for row in rows]
        provenance = dict((rows[0].get("retrieval_provenance") or {})) if rows else {}
        results.append(
            QueryModeResult(
                query_id=query.query_id,
                domain=query.domain,
                mode=mode_name,
                expected_ids=query.expected_ids,
                returned_ids=returned_ids,
                metrics=compute_metrics(
                    returned_ids=returned_ids,
                    expected_ids=query.expected_ids,
                    graded_relevance=query.graded_relevance,
                    latency_ms=latency_ms,
                    result_count=len(rows),
                    rerank_applied=bool(provenance.get("reranker_applied", False)),
                    rerank_fallback_reason=provenance.get("reranker_fallback_reason"),
                    rerank_provider=provenance.get("reranker_provider"),
                    rerank_abstained=bool(provenance.get("reranker_abstained", False)),
                    pool_limit=pool_limit,
                ),
            )
        )
    return results


def _smoke_conversation_modes(
    pipeline: ConversationIngestionPipeline,
    query: EvalQuery,
    *,
    vector_rows_by_query: dict[str, list[dict[str, Any]]],
    hydrated_rows_by_query: dict[str, list[dict[str, Any]]],
    pool_limit: int,
) -> list[QueryModeResult]:
    """Evaluate all conversation modes for one smoke query."""

    results: list[QueryModeResult] = []
    for mode_name, temporal_available, rerank_enabled in (
        ("baseline", False, False),
        ("temporal", True, False),
        ("temporal_rerank", True, True),
    ):
        with ExitStack() as stack:
            if rerank_enabled:
                _patch_smoke_rerankers(stack)
            else:
                stack.enter_context(
                    patch(
                        "agentic_memory.server.tools.rerank_documents",
                        lambda query, documents, high_stakes=False: RerankResponse(
                            applied=False,
                            fallback_reason="disabled_for_eval_mode",
                            high_stakes=high_stakes,
                        ),
                    )
                )
            stack.enter_context(
                patch(
                    "agentic_memory.server.tools._vector_conversation_search",
                    lambda conn, embedder, **kwargs: vector_rows_by_query.get(kwargs["query"], []),
                )
            )
            stack.enter_context(
                patch(
                    "agentic_memory.server.tools._hydrate_temporal_conversation_results",
                    lambda conn, ranked_rows, **kwargs: hydrated_rows_by_query.get(query.query, []),
                )
            )
            pipeline._temporal_bridge._available = temporal_available  # type: ignore[attr-defined]
            pipeline._temporal_bridge.last_query = query.query  # type: ignore[attr-defined]
            started = time.perf_counter()
            rows = tools.search_conversation_turns_sync(
                pipeline,
                query=query.query,
                project_id=query.project_id,
                role=None,
                limit=pool_limit,
                as_of=query.as_of,
                log_prefix="eval_smoke",
            )
            latency_ms = (time.perf_counter() - started) * 1000
        returned_ids = [_normalize_conversation_id(row) for row in rows]
        provenance = dict((rows[0].get("retrieval_provenance") or {})) if rows else {}
        results.append(
            QueryModeResult(
                query_id=query.query_id,
                domain=query.domain,
                mode=mode_name,
                expected_ids=query.expected_ids,
                returned_ids=returned_ids,
                metrics=compute_metrics(
                    returned_ids=returned_ids,
                    expected_ids=query.expected_ids,
                    graded_relevance=query.graded_relevance,
                    latency_ms=latency_ms,
                    result_count=len(rows),
                    rerank_applied=bool(provenance.get("reranker_applied", False)),
                    rerank_fallback_reason=provenance.get("reranker_fallback_reason"),
                    rerank_provider=provenance.get("reranker_provider"),
                    rerank_abstained=bool(provenance.get("reranker_abstained", False)),
                    pool_limit=pool_limit,
                ),
            )
        )
    return results


def run_smoke_eval(*, queries: list[EvalQuery], pool_limit: int) -> EvalReport:
    """Run deterministic smoke evaluation against checked-in fixture corpora."""

    corpus = load_smoke_corpus()
    code_fixture = corpus["code"]
    research_fixture = corpus["research"]
    conversation_fixture = corpus["conversation"]

    normalized_neighborhoods: dict[str, dict[str, Any]] = {}
    for query_text, payload in code_fixture["neighborhoods_by_query"].items():
        normalized_neighborhoods[query_text] = {
            "seed_ids": [int(node_id) for node_id in payload.get("seed_ids", [])],
            "adjacency": {
                int(node_id): [(int(target_id), float(weight)) for target_id, weight in edges]
                for node_id, edges in (payload.get("adjacency") or {}).items()
            },
            "node_meta": {
                int(node_id): dict(meta)
                for node_id, meta in (payload.get("node_meta") or {}).items()
            },
        }

    code_graph = SmokeGraph(
        repo_id=str(code_fixture["repo_id"]),
        baseline_rows_by_query={query: list(rows) for query, rows in code_fixture["baseline_rows_by_query"].items()},
        neighborhoods_by_query=normalized_neighborhoods,
    )

    research_embedder = SmokeEmbedder()
    research_bridge = SmokeBridge(
        {query: list(rows) for query, rows in research_fixture["temporal_rows_by_query"].items()},
        available=True,
    )
    research_pipeline = ResearchIngestionPipeline(
        SmokeConnection(
            SmokeResearchSession(
                research_embedder,
                {query: list(rows) for query, rows in research_fixture["baseline_rows_by_query"].items()},
            )
        ),
        research_embedder,
        SmokeExtractor(),
        temporal_bridge=research_bridge,
    )

    conversation_embedder = SmokeEmbedder()
    conversation_bridge = SmokeBridge(
        {query: list(rows) for query, rows in conversation_fixture["temporal_rows_by_query"].items()},
        available=True,
    )
    conversation_pipeline = ConversationIngestionPipeline(
        SmokeConnection(object()),
        conversation_embedder,
        SmokeExtractor(),
        temporal_bridge=conversation_bridge,
    )

    results: list[QueryModeResult] = []
    for query in queries:
        if query.domain == "code":
            results.extend(_smoke_code_modes(code_graph, query, pool_limit=pool_limit))
        elif query.domain == "research":
            research_embedder.last_query = query.query
            research_bridge.last_query = query.query
            results.extend(_smoke_research_modes(research_pipeline, query, pool_limit=pool_limit))
        elif query.domain == "conversation":
            conversation_embedder.last_query = query.query
            conversation_bridge.last_query = query.query
            results.extend(
                _smoke_conversation_modes(
                    conversation_pipeline,
                    query,
                    vector_rows_by_query={
                        query_text: list(rows)
                        for query_text, rows in conversation_fixture["baseline_rows_by_query"].items()
                    },
                    hydrated_rows_by_query={
                        query_text: list(rows)
                        for query_text, rows in conversation_fixture["hydrated_rows_by_query"].items()
                    },
                    pool_limit=pool_limit,
                )
            )
        else:
            raise ValueError(f"Unsupported domain: {query.domain}")

    return build_report(
        backend="smoke",
        profile="smoke",
        pool_limit=pool_limit,
        results=results,
    )


def _disable_rerank(module_path: str, stack: ExitStack) -> None:
    """Disable learned reranking for one eval mode."""

    stack.enter_context(
        patch(
            module_path,
            lambda query, documents, high_stakes=False: RerankResponse(
                applied=False,
                fallback_reason="disabled_for_eval_mode",
                high_stakes=high_stakes,
            ),
        )
    )


def _run_live_code_mode(
    graph: Any,
    query: EvalQuery,
    *,
    mode_name: str,
    retrieval_policy: str,
    use_ppr: bool,
    pool_limit: int,
) -> QueryModeResult:
    with ExitStack() as stack:
        if mode_name != "graph_rerank":
            _disable_rerank("agentic_memory.server.code_search.rerank_documents", stack)
        started = time.perf_counter()
        rows = code_search.search_code(
            graph,
            query=query.query,
            limit=pool_limit,
            use_ppr=use_ppr,
            retrieval_policy=retrieval_policy,
        )
        latency_ms = (time.perf_counter() - started) * 1000
    returned_ids = [_normalize_code_id(row) for row in rows]
    provenance = dict((rows[0].get("retrieval_provenance") or {})) if rows else {}
    return QueryModeResult(
        query_id=query.query_id,
        domain=query.domain,
        mode=mode_name,
        expected_ids=query.expected_ids,
        returned_ids=returned_ids,
        metrics=compute_metrics(
            returned_ids=returned_ids,
            expected_ids=query.expected_ids,
            graded_relevance=query.graded_relevance,
            latency_ms=latency_ms,
            result_count=len(rows),
            rerank_applied=bool(provenance.get("reranker_applied", False)),
            rerank_fallback_reason=provenance.get("reranker_fallback_reason"),
            rerank_provider=provenance.get("reranker_provider"),
            rerank_abstained=bool(provenance.get("reranker_abstained", False)),
            pool_limit=pool_limit,
        ),
    )


def _run_live_research_mode(
    pipeline: ResearchIngestionPipeline,
    query: EvalQuery,
    *,
    mode_name: str,
    temporal_enabled: bool,
    pool_limit: int,
) -> QueryModeResult:
    with ExitStack() as stack:
        if mode_name != "temporal_rerank":
            _disable_rerank("agentic_memory.server.research_search.rerank_documents", stack)
        bridge = pipeline.__dict__.get("_temporal_bridge")
        if bridge is not None and hasattr(bridge, "is_available"):
            stack.enter_context(patch.object(bridge, "is_available", return_value=temporal_enabled))
        started = time.perf_counter()
        rows = research_search.search_research(
            pipeline,
            query=query.query,
            limit=pool_limit,
            as_of=query.as_of,
            high_stakes=query.high_stakes,
        )
        latency_ms = (time.perf_counter() - started) * 1000
    returned_ids = [_normalize_research_id(row) for row in rows]
    provenance = dict((rows[0].get("retrieval_provenance") or {})) if rows else {}
    return QueryModeResult(
        query_id=query.query_id,
        domain=query.domain,
        mode=mode_name,
        expected_ids=query.expected_ids,
        returned_ids=returned_ids,
        metrics=compute_metrics(
            returned_ids=returned_ids,
            expected_ids=query.expected_ids,
            graded_relevance=query.graded_relevance,
            latency_ms=latency_ms,
            result_count=len(rows),
            rerank_applied=bool(provenance.get("reranker_applied", False)),
            rerank_fallback_reason=provenance.get("reranker_fallback_reason"),
            rerank_provider=provenance.get("reranker_provider"),
            rerank_abstained=bool(provenance.get("reranker_abstained", False)),
            pool_limit=pool_limit,
        ),
    )


def _run_live_conversation_mode(
    pipeline: ConversationIngestionPipeline,
    query: EvalQuery,
    *,
    mode_name: str,
    temporal_enabled: bool,
    pool_limit: int,
) -> QueryModeResult:
    with ExitStack() as stack:
        if mode_name != "temporal_rerank":
            _disable_rerank("agentic_memory.server.tools.rerank_documents", stack)
        bridge = pipeline.__dict__.get("_temporal_bridge")
        if bridge is not None and hasattr(bridge, "is_available"):
            stack.enter_context(patch.object(bridge, "is_available", return_value=temporal_enabled))
        started = time.perf_counter()
        rows = tools.search_conversation_turns_sync(
            pipeline,
            query=query.query,
            project_id=query.project_id,
            role=None,
            limit=pool_limit,
            as_of=query.as_of,
            log_prefix="eval_live",
        )
        latency_ms = (time.perf_counter() - started) * 1000
    returned_ids = [_normalize_conversation_id(row) for row in rows]
    provenance = dict((rows[0].get("retrieval_provenance") or {})) if rows else {}
    return QueryModeResult(
        query_id=query.query_id,
        domain=query.domain,
        mode=mode_name,
        expected_ids=query.expected_ids,
        returned_ids=returned_ids,
        metrics=compute_metrics(
            returned_ids=returned_ids,
            expected_ids=query.expected_ids,
            graded_relevance=query.graded_relevance,
            latency_ms=latency_ms,
            result_count=len(rows),
            rerank_applied=bool(provenance.get("reranker_applied", False)),
            rerank_fallback_reason=provenance.get("reranker_fallback_reason"),
            rerank_provider=provenance.get("reranker_provider"),
            rerank_abstained=bool(provenance.get("reranker_abstained", False)),
            pool_limit=pool_limit,
        ),
    )


def run_live_eval(
    *,
    queries: list[EvalQuery],
    pool_limit: int,
    repo_root: Path | None = None,
) -> EvalReport:
    """Run live evaluation against the currently configured repo and pipelines."""

    graph = None
    if any(query.domain == "code" for query in queries):
        args = type("EvalArgs", (), {"repo": str(repo_root) if repo_root else None, "env_file": None})()
        resolved_repo_root, config = _resolve_repo_and_config(args, require_initialized=True)
        graph = _build_code_graph_builder(repo_root=resolved_repo_root, config=config)

    research_pipeline = get_pipeline() if any(query.domain == "research" for query in queries) else None
    conversation_pipeline = (
        get_conversation_pipeline() if any(query.domain == "conversation" for query in queries) else None
    )

    results: list[QueryModeResult] = []
    for query in queries:
        if query.domain == "code":
            if graph is None:
                raise RuntimeError("Live code evaluation requested without a code graph builder.")
            results.extend(
                [
                    _run_live_code_mode(
                        graph,
                        query,
                        mode_name="baseline",
                        retrieval_policy=code_search.SAFE_RETRIEVAL_POLICY,
                        use_ppr=False,
                        pool_limit=pool_limit,
                    ),
                    _run_live_code_mode(
                        graph,
                        query,
                        mode_name="graph",
                        retrieval_policy=code_search.GRAPH_RERANKED_POLICY,
                        use_ppr=True,
                        pool_limit=pool_limit,
                    ),
                    _run_live_code_mode(
                        graph,
                        query,
                        mode_name="graph_rerank",
                        retrieval_policy=code_search.GRAPH_RERANKED_POLICY,
                        use_ppr=True,
                        pool_limit=pool_limit,
                    ),
                ]
            )
        elif query.domain == "research":
            if research_pipeline is None:
                raise RuntimeError("Live research evaluation requested without a research pipeline.")
            results.extend(
                [
                    _run_live_research_mode(
                        research_pipeline,
                        query,
                        mode_name="baseline",
                        temporal_enabled=False,
                        pool_limit=pool_limit,
                    ),
                    _run_live_research_mode(
                        research_pipeline,
                        query,
                        mode_name="temporal",
                        temporal_enabled=True,
                        pool_limit=pool_limit,
                    ),
                    _run_live_research_mode(
                        research_pipeline,
                        query,
                        mode_name="temporal_rerank",
                        temporal_enabled=True,
                        pool_limit=pool_limit,
                    ),
                ]
            )
        elif query.domain == "conversation":
            if conversation_pipeline is None:
                raise RuntimeError("Live conversation evaluation requested without a conversation pipeline.")
            results.extend(
                [
                    _run_live_conversation_mode(
                        conversation_pipeline,
                        query,
                        mode_name="baseline",
                        temporal_enabled=False,
                        pool_limit=pool_limit,
                    ),
                    _run_live_conversation_mode(
                        conversation_pipeline,
                        query,
                        mode_name="temporal",
                        temporal_enabled=True,
                        pool_limit=pool_limit,
                    ),
                    _run_live_conversation_mode(
                        conversation_pipeline,
                        query,
                        mode_name="temporal_rerank",
                        temporal_enabled=True,
                        pool_limit=pool_limit,
                    ),
                ]
            )
        else:
            raise ValueError(f"Unsupported domain: {query.domain}")

    return build_report(
        backend="live",
        profile="gold",
        pool_limit=pool_limit,
        results=results,
    )


def build_report(
    *,
    backend: str,
    profile: str,
    pool_limit: int,
    results: list[QueryModeResult],
) -> EvalReport:
    """Aggregate query-level results into the persisted report structure."""

    domains = sorted({row.domain for row in results})
    modes = sorted({row.mode for row in results})
    aggregates: dict[str, dict[str, AggregateMetrics]] = {}
    for domain in domains:
        aggregates[domain] = {}
        for mode in modes:
            mode_rows = _mode_rows(results, domain=domain, mode=mode)
            if not mode_rows:
                continue
            aggregates[domain][mode] = _aggregate_mode(mode_rows)
    return EvalReport(
        backend=backend,
        profile=profile,
        pool_limit=pool_limit,
        aggregates=aggregates,
        results=results,
    )


def write_report(report: EvalReport, *, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports to ``output_dir``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report.backend}-{report.profile}-report.json"
    markdown_path = output_dir / f"{report.backend}-{report.profile}-report.md"
    json_path.write_text(json.dumps(_serialize_report(report), indent=2), encoding="utf-8")
    markdown_path.write_text(_report_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def enforce_smoke_gate(report: EvalReport) -> None:
    """Fail when the recommended smoke mode for a domain misses top-5/top-10."""

    failures: list[str] = []
    for domain in sorted({row.domain for row in report.results}):
        recommended_mode = DEFAULT_MODE_BY_DOMAIN[domain]
        domain_rows = [
            row
            for row in report.results
            if row.domain == domain and row.mode == recommended_mode
        ]
        for row in domain_rows:
            if row.metrics.recall_at_10 < 1.0:
                failures.append(f"{domain}/{row.query_id} missed Recall@10 in {recommended_mode}")
            if row.metrics.success_at_5 < 1.0:
                failures.append(f"{domain}/{row.query_id} missed Success@5 in {recommended_mode}")
    if failures:
        raise RuntimeError("Smoke eval gate failed:\n- " + "\n- ".join(failures))
