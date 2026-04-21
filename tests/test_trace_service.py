"""Tests for JIT trace execution behavior."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from agentic_memory.trace.service import TraceExecutionService, TraceFunctionResult

pytestmark = [pytest.mark.unit]


def _mock_llm_client(payload: dict):
    """Build an OpenAI-compatible mock client for JSON-mode chat responses."""
    client = Mock()
    message = Mock()
    message.content = __import__("json").dumps(payload)
    choice = Mock(message=message)
    response = Mock(choices=[choice])
    client.chat.completions.create.return_value = response
    return client


def test_trace_execution_path_returns_ambiguous_candidates_without_llm():
    """Ambiguous symbol resolution should return candidates instead of guessing."""
    graph = Mock()
    graph.repo_id = "repo-1"
    graph.resolve_function_symbol.return_value = {
        "status": "ambiguous",
        "match_type": "name",
        "candidates": [
            {"signature": "a.py:run", "path": "a.py", "qualified_name": "run"},
            {"signature": "b.py:run", "path": "b.py", "qualified_name": "run"},
        ],
    }

    service = TraceExecutionService(
        graph=graph,
        client=_mock_llm_client({"edges": [], "unresolved": []}),
        api_key="test-key",
    )

    result = service.trace_execution_path(start_symbol="run", repo_id="repo-1")

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert result["total_edges"] == 0


def test_trace_function_uses_cache_when_available():
    """Valid cached traces should bypass the LLM and return normalized edges."""
    graph = Mock()
    graph.repo_id = "repo-1"
    graph.get_cached_jit_trace.return_value = {
        "trace_id": "trace-1",
        "model": "cached-model",
        "edges": [
            {
                "relationship_type": "JIT_CALLS_DIRECT",
                "caller_signature": "pkg/a.py:foo",
                "callee_signature": "pkg/b.py:bar",
                "callee_qualified_name": "bar",
                "callee_name": "bar",
                "callee_path": "pkg/b.py",
                "confidence": 0.91,
                "rationale": "explicit call",
                "evidence": "bar()",
            }
        ],
        "unresolved": [{"target_name": "zap", "reason": "missing"}],
    }
    graph.get_function_trace_context.return_value = {
        "root": {
            "signature": "pkg/a.py:foo",
            "qualified_name": "foo",
            "name": "foo",
            "path": "pkg/a.py",
        }
    }

    client = _mock_llm_client({"edges": [], "unresolved": []})
    service = TraceExecutionService(graph=graph, client=client, api_key="test-key")

    result = service.trace_function(signature="pkg/a.py:foo", repo_id="repo-1")

    assert result.cache_hit is True
    assert result.edges[0]["edge_type"] == "direct_call"
    assert result.edges[0]["callee_signature"] == "pkg/b.py:bar"
    client.chat.completions.create.assert_not_called()


def test_trace_function_runs_llm_and_stores_normalized_cache():
    """Fresh traces should validate LLM targets before persisting derived edges."""
    graph = Mock()
    graph.repo_id = "repo-1"
    graph.get_cached_jit_trace.return_value = None
    graph.get_function_trace_context.return_value = {
        "root": {
            "signature": "pkg/a.py:foo",
            "qualified_name": "foo",
            "name": "foo",
            "path": "pkg/a.py",
            "code": "def foo():\n    bar()\n    emit_event()\n",
            "imports": ["pkg/b.py"],
            "imported_by": [],
            "file_ohash": "hash-1",
        },
        "siblings": [],
        "classes": [],
        "candidate_functions": [
            {
                "signature": "pkg/b.py:bar",
                "qualified_name": "bar",
                "name": "bar",
                "path": "pkg/b.py",
            },
            {
                "signature": "pkg/c.py:on_event",
                "qualified_name": "on_event",
                "name": "on_event",
                "path": "pkg/c.py",
            },
        ],
    }

    client = _mock_llm_client(
        {
            "edges": [
                {
                    "callee_signature": "pkg/b.py:bar",
                    "edge_type": "direct_call",
                    "confidence": 0.95,
                    "rationale": "foo calls bar directly",
                    "evidence": "bar()",
                },
                {
                    "callee_signature": "pkg/ghost.py:missing",
                    "edge_type": "direct_call",
                    "confidence": 0.99,
                    "rationale": "invalid target",
                    "evidence": "ghost()",
                },
                {
                    "callee_signature": "pkg/c.py:on_event",
                    "edge_type": "message_flow",
                    "confidence": 0.7,
                    "rationale": "event dispatch",
                    "evidence": "emit_event()",
                },
            ],
            "unresolved": [
                {"target_name": "emit_event handler", "reason": "dynamic", "evidence": "emit_event()"}
            ],
        }
    )
    service = TraceExecutionService(graph=graph, client=client, api_key="test-key")

    result = service.trace_function(signature="pkg/a.py:foo", repo_id="repo-1")

    assert result.cache_hit is False
    assert [edge["callee_signature"] for edge in result.edges] == [
        "pkg/b.py:bar",
        "pkg/c.py:on_event",
    ]
    assert result.edges[0]["relationship_type"] == "JIT_CALLS_DIRECT"
    assert result.edges[1]["relationship_type"] == "JIT_MESSAGE_FLOW"
    assert result.unresolved[0]["target_name"] == "emit_event handler"
    graph.store_jit_trace_result.assert_called_once()
    stored_edges = graph.store_jit_trace_result.call_args.kwargs["edges"]
    assert len(stored_edges) == 2


def test_trace_execution_path_recurses_only_on_direct_calls():
    """Recursive tracing should expand only direct calls in v1."""
    graph = Mock()
    graph.repo_id = "repo-1"
    graph.resolve_function_symbol.return_value = {
        "status": "resolved",
        "match_type": "signature",
        "candidate": {
            "signature": "pkg/a.py:foo",
            "qualified_name": "foo",
            "name": "foo",
            "path": "pkg/a.py",
        },
    }

    service = TraceExecutionService(
        graph=graph,
        client=_mock_llm_client({"edges": [], "unresolved": []}),
        api_key="test-key",
    )

    trace_sequence = [
        TraceFunctionResult(
            root_signature="pkg/a.py:foo",
            root_qualified_name="foo",
            root_path="pkg/a.py",
            cache_hit=False,
            edges=[
                {
                    "callee_signature": "pkg/b.py:bar",
                    "edge_type": "direct_call",
                    "relationship_type": "JIT_CALLS_DIRECT",
                    "confidence": 0.9,
                    "evidence": "",
                    "rationale": "",
                },
                {
                    "callee_signature": "pkg/c.py:on_event",
                    "edge_type": "message_flow",
                    "relationship_type": "JIT_MESSAGE_FLOW",
                    "confidence": 0.6,
                    "evidence": "",
                    "rationale": "",
                },
            ],
            unresolved=[],
            model="test",
        ),
        TraceFunctionResult(
            root_signature="pkg/b.py:bar",
            root_qualified_name="bar",
            root_path="pkg/b.py",
            cache_hit=True,
            edges=[],
            unresolved=[],
            model="test",
        ),
    ]
    service.trace_function = Mock(side_effect=trace_sequence)

    result = service.trace_execution_path(start_symbol="pkg/a.py:foo", repo_id="repo-1", max_depth=3)

    assert result["status"] == "resolved"
    assert [row["root_signature"] for row in result["traces"]] == [
        "pkg/a.py:foo",
        "pkg/b.py:bar",
    ]
    service.trace_function.assert_any_call(
        signature="pkg/b.py:bar",
        repo_id="repo-1",
        force_refresh=False,
    )
