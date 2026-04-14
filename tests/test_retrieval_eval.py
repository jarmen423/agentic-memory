"""Tests for the gold-query retrieval evaluation harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.eval import retrieval_eval


pytestmark = [pytest.mark.unit]


def test_compute_metrics_returns_expected_ranking_values():
    metrics = retrieval_eval.compute_metrics(
        returned_ids=["doc-b", "doc-a", "doc-c"],
        expected_ids=["doc-a"],
        graded_relevance={"doc-a": 2},
        latency_ms=12.0,
        result_count=3,
        rerank_applied=True,
        rerank_fallback_reason=None,
        rerank_provider="cohere",
        rerank_abstained=False,
        pool_limit=10,
    )

    assert metrics.recall_at_10 == 1.0
    assert metrics.recall_at_pool == 1.0
    assert metrics.mrr_at_10 == pytest.approx(0.5)
    assert metrics.success_at_5 == 1.0
    assert metrics.ndcg_at_10 == pytest.approx(1 / 1.5849625, rel=1e-4)


def test_load_eval_profile_smoke_returns_all_three_domains():
    rows = retrieval_eval.load_eval_profile("smoke")

    assert rows
    assert {row.domain for row in rows} == {"code", "research", "conversation"}


def test_run_smoke_eval_and_write_report(tmp_path: Path):
    rows = retrieval_eval.load_eval_profile("smoke")

    report = retrieval_eval.run_smoke_eval(queries=rows, pool_limit=10)
    retrieval_eval.enforce_smoke_gate(report)
    json_path, markdown_path = retrieval_eval.write_report(report, output_dir=tmp_path)

    assert json_path.exists()
    assert markdown_path.exists()
    assert "code" in report.aggregates
    assert "graph_rerank" in report.aggregates["code"]
