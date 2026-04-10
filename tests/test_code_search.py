"""Unit tests for repo-scoped code retrieval and optional PPR reranking."""

from __future__ import annotations

from unittest.mock import Mock

from agentic_memory.server import code_search


def _row(*, sig: str, path: str, score: float) -> dict[str, object]:
    """Create one semantic-search row in the shape used by the code module."""
    return {
        "name": sig.split("::")[-1],
        "sig": sig,
        "score": score,
        "text": f"snippet for {sig}",
        "path": path,
        "labels": ["Function"],
    }


def test_search_code_uses_baseline_semantic_search_when_ppr_disabled():
    """Baseline code search should preserve the legacy semantic-search path."""
    graph = Mock()
    graph.repo_id = "repo-alpha"
    graph.semantic_search.return_value = [
        _row(sig="pkg/auth.py::login", path="pkg/auth.py", score=0.91),
        _row(sig="pkg/auth.py::logout", path="pkg/auth.py", score=0.73),
    ]

    rows = code_search.search_code(
        graph,
        query="login flow",
        limit=1,
        use_ppr=False,
    )

    assert len(rows) == 1
    assert rows[0]["sig"] == "pkg/auth.py::login"
    assert rows[0]["retrieval_provenance"]["policy"] == "auto"
    assert rows[0]["retrieval_provenance"]["graph_reranking_applied"] is False
    graph.semantic_search.assert_called_once_with("login flow", limit=1)


def test_search_code_uses_explicit_repo_scope_for_baseline_search():
    """Explicit repo_id should flow into the baseline graph query."""
    graph = Mock()
    graph.repo_id = "repo-default"
    graph.semantic_search.return_value = [
        _row(sig="pkg/cache.py::warm", path="pkg/cache.py", score=0.8),
    ]

    rows = code_search.search_code(
        graph,
        query="warm cache",
        limit=1,
        repo_id="repo-override",
        use_ppr=False,
    )

    assert rows[0]["sig"] == "pkg/cache.py::warm"
    assert rows[0]["retrieval_provenance"]["policy"] == "auto"
    graph.semantic_search.assert_called_once_with(
        "warm cache",
        limit=1,
        repo_id="repo-override",
    )


def test_search_code_ppr_reranks_with_structural_scores(monkeypatch):
    """Code PPR should combine baseline and structural scores into one ranking."""
    graph = Mock()
    graph.repo_id = "repo-alpha"
    graph.semantic_search.return_value = [
        _row(sig="pkg/service.py::seed", path="pkg/service.py", score=0.50),
        _row(sig="pkg/helpers.py::helper", path="pkg/helpers.py", score=0.49),
    ]

    monkeypatch.setattr(
        code_search,
        "_load_code_neighborhood",
        lambda *args, **kwargs: {
            "seed_ids": [1, 2],
            "adjacency": {
                1: [(2, 1.0)],
                2: [(1, 1.0)],
            },
            "node_meta": {
                1: {
                    "labels": ["Function"],
                    "props": {
                        "signature": "pkg/service.py::seed",
                        "name": "seed",
                        "path": "pkg/service.py",
                    },
                },
                2: {
                    "labels": ["Function"],
                    "props": {
                        "signature": "pkg/helpers.py::helper",
                        "name": "helper",
                        "path": "pkg/helpers.py",
                    },
                },
            },
        },
    )
    monkeypatch.setattr(
        code_search,
        "_run_personalized_page_rank",
        lambda **kwargs: {
            1: 0.05,
            2: 0.90,
        },
    )

    rows = code_search.search_code(
        graph,
        query="shared helper",
        limit=2,
        use_ppr=True,
    )

    assert [row["sig"] for row in rows] == [
        "pkg/helpers.py::helper",
        "pkg/service.py::seed",
    ]
    assert rows[0]["ppr_score"] == 0.90
    assert rows[0]["retrieval_provenance"]["graph_reranking_applied"] is True
    assert rows[0]["retrieval_provenance"]["graph_edge_types_used"] == [
        "IMPORTS",
        "HAS_METHOD",
        "DEFINES",
    ]
    graph.semantic_search.assert_called_once_with("shared helper", limit=6)


def test_search_code_without_repo_context_falls_back_to_baseline():
    """PPR requests should degrade to baseline search when no repo scope exists."""
    graph = Mock()
    graph.repo_id = None
    graph.semantic_search.return_value = [
        _row(sig="pkg/standalone.py::run", path="pkg/standalone.py", score=0.77),
    ]

    rows = code_search.search_code(
        graph,
        query="standalone entrypoint",
        limit=1,
        use_ppr=True,
    )

    assert rows[0]["sig"] == "pkg/standalone.py::run"
    assert rows[0]["retrieval_provenance"]["mode"] == "semantic_only"
    graph.semantic_search.assert_called_once_with("standalone entrypoint", limit=1)


def test_search_code_safe_policy_ignores_graph_reranking():
    """Agent-safe retrieval should stay on semantic search even when repo-scoped."""
    graph = Mock()
    graph.repo_id = "repo-alpha"
    graph.semantic_search.return_value = [
        _row(sig="pkg/auth.py::login", path="pkg/auth.py", score=0.91),
    ]

    rows = code_search.search_code(
        graph,
        query="login flow",
        limit=1,
        retrieval_policy="safe",
    )

    assert rows[0]["retrieval_provenance"]["policy"] == "safe"
    assert rows[0]["retrieval_provenance"]["graph_reranking_applied"] is False
    graph.semantic_search.assert_called_once_with("login flow", limit=1)


def test_run_personalized_page_rank_biases_toward_seed_nodes():
    """Restart probability should keep the starting node ahead of its neighbors."""
    scores = code_search._run_personalized_page_rank(
        seed_ids=[1],
        adjacency={
            1: [(2, 1.0)],
            2: [(1, 1.0)],
        },
        alpha=0.2,
        max_iterations=25,
        epsilon=1e-8,
    )

    assert scores[1] > scores[2] > 0.0
