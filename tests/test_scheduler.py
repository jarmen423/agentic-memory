"""Unit tests for recurring research scheduling and MCP schedule tools."""

import asyncio
import json
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from codememory.core import scheduler as scheduler_module
from codememory.server import tools as tools_module

pytestmark = [pytest.mark.unit]


class FakeMCP:
    """Minimal FastMCP stand-in that records decorated tools."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, *args, **kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _data_result(rows):
    result = Mock()
    result.data.return_value = rows
    return result


def _single_result(payload):
    result = Mock()
    result.single.return_value = payload
    return result


def _iter_result(rows):
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    return result


def _mock_connection(session: Mock) -> Mock:
    conn = Mock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False
    conn.session.return_value = ctx
    return conn


def _build_scheduler(monkeypatch):
    mock_jobstore = Mock()
    mock_background_scheduler = Mock()
    mock_extraction_client = Mock()

    monkeypatch.setattr(
        scheduler_module,
        "SQLAlchemyJobStore",
        Mock(return_value=mock_jobstore),
    )
    monkeypatch.setattr(
        scheduler_module,
        "BackgroundScheduler",
        Mock(return_value=mock_background_scheduler),
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_extraction_openai_client",
        Mock(return_value=mock_extraction_client),
    )

    session = Mock()
    conn = _mock_connection(session)
    pipeline = Mock()
    pipeline._conn = conn

    scheduler = scheduler_module.ResearchScheduler(
        connection_manager=conn,
        extraction_llm_api_key="groq-key",
        extraction_llm_model="llama-3.3-70b-versatile",
        brave_api_key="brave-key",
        pipeline=pipeline,
    )
    return scheduler, session, pipeline, mock_background_scheduler, mock_extraction_client, conn


def test_create_schedule_persists_node_and_registers_job(monkeypatch):
    scheduler, session, _, background_scheduler, _, _ = _build_scheduler(monkeypatch)
    monkeypatch.setattr(
        scheduler_module.uuid,
        "uuid4",
        lambda: scheduler_module.uuid.UUID("00000000-0000-4000-8000-000000000000"),
    )

    schedule_id = scheduler.create_schedule(
        template="Research {topic}",
        variables=["topic"],
        cron_expr="0 9 * * 1",
        project_id="proj1",
        max_runs_per_day=3,
    )

    assert schedule_id == "00000000-0000-4000-8000-000000000000"
    assert "MERGE (s:Schedule" in session.run.call_args_list[0].args[0]
    background_scheduler.start.assert_called_once()
    add_job_kwargs = background_scheduler.add_job.call_args.kwargs
    assert add_job_kwargs["id"] == schedule_id
    assert add_job_kwargs["replace_existing"] is True
    assert add_job_kwargs["kwargs"] == {"schedule_id": schedule_id}


def test_fill_variables_uses_extraction_llm_json_payload(monkeypatch):
    scheduler, session, _, _, extraction_client, _ = _build_scheduler(monkeypatch)
    session.run.return_value = _data_result(
        [{"topic": "GraphRAG", "researched_at": "2026-03-20T00:00:00+00:00"}]
    )
    extraction_client.chat.completions.create.return_value = Mock(
        choices=[Mock(message=Mock(content='{"topic":"AI agents","angle":"memory systems"}'))]
    )

    rendered = scheduler._fill_variables(
        template="Research {topic} on {angle}",
        variables=["topic", "angle"],
        project_id="proj1",
    )

    assert rendered == "Research AI agents on memory systems"
    extraction_client.chat.completions.create.assert_called_once()


def test_run_research_session_ingests_brave_results(monkeypatch):
    scheduler, session, pipeline, _, _, _ = _build_scheduler(monkeypatch)
    scheduler._fill_variable_values = Mock(
        return_value={"topic": "AI agents", "angle": "memory systems"}
    )

    schedule = {
        "schedule_id": "sched-1",
        "template": "Research {topic} on {angle}",
        "variables": ["topic", "angle"],
        "project_id": "proj1",
        "run_count": 0,
        "max_runs_per_day": 5,
    }

    def run_side_effect(query, **kwargs):
        if "MATCH (s:Schedule" in query and "RETURN s{.*} AS schedule" in query:
            return _single_result({"schedule": schedule})
        return Mock()

    session.run.side_effect = run_side_effect

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "AI agents overview",
                    "url": "https://example.com/ai-agents",
                    "description": "Agentic systems in production",
                },
                {
                    "title": "Memory systems",
                    "url": "https://example.com/memory",
                    "description": "Working memory for autonomous agents",
                },
            ]
        }
    }
    mock_client = Mock()
    mock_client.get.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__.return_value = mock_client
    mock_client_ctx.__exit__.return_value = False
    monkeypatch.setattr(
        scheduler_module.httpx,
        "Client",
        Mock(return_value=mock_client_ctx),
    )

    result = scheduler.run_research_session(schedule_id="sched-1")

    assert result["status"] == "ok"
    assert result["results"] == 2
    assert result["query"] == "Research AI agents on memory systems"
    assert pipeline.ingest.call_count == 2
    first_call = pipeline.ingest.call_args_list[0].args[0]
    assert first_call["type"] == "finding"
    assert first_call["project_id"] == "proj1"


def test_run_research_session_skips_when_max_runs_reached(monkeypatch):
    scheduler, session, pipeline, _, _, _ = _build_scheduler(monkeypatch)
    schedule = {
        "schedule_id": "sched-1",
        "template": "Research {topic}",
        "variables": ["topic"],
        "project_id": "proj1",
        "run_count": 5,
        "max_runs_per_day": 5,
    }
    session.run.return_value = _single_result({"schedule": schedule})

    result = scheduler.run_research_session(schedule_id="sched-1")

    assert result == {"status": "skipped", "reason": "max_runs_per_day"}
    pipeline.ingest.assert_not_called()


def test_brave_circuit_breaker_opens_after_three_failures(monkeypatch):
    scheduler, session, pipeline, _, _, _ = _build_scheduler(monkeypatch)
    scheduler._fill_variable_values = Mock(return_value={"topic": "AI agents"})
    schedule = {
        "schedule_id": "sched-1",
        "template": "Research {topic}",
        "variables": ["topic"],
        "project_id": "proj1",
        "run_count": 0,
        "max_runs_per_day": 5,
    }
    session.run.return_value = _single_result({"schedule": schedule})

    mock_response = Mock(status_code=500)
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom",
        request=Mock(),
        response=mock_response,
    )
    mock_client = Mock()
    mock_client.get.return_value = mock_response
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__.return_value = mock_client
    mock_client_ctx.__exit__.return_value = False
    monkeypatch.setattr(
        scheduler_module.httpx,
        "Client",
        Mock(return_value=mock_client_ctx),
    )

    for _ in range(3):
        result = scheduler.run_research_session(schedule_id="sched-1")
        assert result["status"] == "error"

    skipped = scheduler.run_research_session(schedule_id="sched-1")
    assert skipped == {"status": "skipped", "reason": "brave_circuit_open"}
    assert scheduler._brave_failures == 3
    assert mock_client.get.call_count == 3
    pipeline.ingest.assert_not_called()


def test_list_schedules_returns_project_scoped_rows(monkeypatch):
    scheduler, session, _, _, _, _ = _build_scheduler(monkeypatch)
    session.run.return_value = _data_result(
        [
            {"schedule": {"schedule_id": "a", "project_id": "proj1"}},
            {"schedule": {"schedule_id": "b", "project_id": "proj1"}},
        ]
    )

    schedules = scheduler.list_schedules("proj1")

    assert schedules == [
        {"schedule_id": "a", "project_id": "proj1"},
        {"schedule_id": "b", "project_id": "proj1"},
    ]


def test_register_schedule_tools_exposes_schedule_run_and_list(monkeypatch):
    fake_mcp = FakeMCP()
    mock_scheduler = Mock()
    mock_scheduler.create_schedule.return_value = "sched-1"
    mock_scheduler.run_research_session.return_value = {
        "status": "ok",
        "results": 1,
        "query": "Research AI agents",
    }
    mock_scheduler.list_schedules.return_value = [{"schedule_id": "sched-1"}]
    monkeypatch.setattr(tools_module, "ResearchScheduler", Mock(return_value=mock_scheduler))

    tools_module.register_schedule_tools(
        fake_mcp,
        connection_manager=Mock(),
        groq_api_key="groq-key",
        brave_api_key="brave-key",
        pipeline=Mock(),
    )

    created = json.loads(
        asyncio.run(
            fake_mcp.tools["schedule_research"](
                template="Research {topic}",
                variables=["topic"],
                cron_expr="0 9 * * 1",
                project_id="proj1",
                max_runs_per_day=5,
            )
        )
    )
    assert created == {"status": "ok", "schedule_id": "sched-1"}

    run_payload = json.loads(
        asyncio.run(fake_mcp.tools["run_research_session"](schedule_id="sched-1"))
    )
    assert run_payload["status"] == "ok"

    listed = json.loads(
        asyncio.run(fake_mcp.tools["list_research_schedules"]("proj1"))
    )
    assert listed == {"status": "ok", "schedules": [{"schedule_id": "sched-1"}]}


def test_search_conversations_as_of_filters_future_turns(monkeypatch):
    fake_mcp = FakeMCP()
    tools_module.register_conversation_tools(fake_mcp)

    session = Mock()
    session.run.return_value = _iter_result(
        [
            {
                "session_id": "s1",
                "turn_index": 0,
                "role": "user",
                "content": "old",
                "source_agent": "claude",
                "timestamp": "2026-03-01T00:00:00+00:00",
                "ingested_at": "2026-03-01T00:00:00+00:00",
                "entities": [],
                "score": 0.9,
            },
            {
                "session_id": "s2",
                "turn_index": 1,
                "role": "assistant",
                "content": "new",
                "source_agent": "claude",
                "timestamp": "2026-03-10T00:00:00+00:00",
                "ingested_at": "2026-03-10T00:00:00+00:00",
                "entities": [],
                "score": 0.8,
            },
        ]
    )
    pipeline = Mock()
    pipeline._conn = _mock_connection(session)
    pipeline._embedder = Mock()
    pipeline._embedder.embed.return_value = [0.1] * 768
    monkeypatch.setattr(tools_module, "_get_mcp_conversation_pipeline", lambda: pipeline)

    results = asyncio.run(
        fake_mcp.tools["search_conversations"](
            query="memory",
            as_of="2026-03-05T00:00:00+00:00",
        )
    )

    assert len(results) == 1
    assert results[0]["content"] == "old"


def test_get_conversation_context_as_of_filters_matches_and_context(monkeypatch):
    fake_mcp = FakeMCP()
    tools_module.register_conversation_tools(fake_mcp)

    session = Mock()
    session.run.side_effect = [
        _iter_result(
            [
                {
                    "session_id": "s1",
                    "turn_index": 1,
                    "role": "assistant",
                    "content": "current",
                    "ingested_at": "2026-03-02T00:00:00+00:00",
                    "score": 0.95,
                },
                {
                    "session_id": "s2",
                    "turn_index": 1,
                    "role": "assistant",
                    "content": "future",
                    "ingested_at": "2026-03-20T00:00:00+00:00",
                    "score": 0.75,
                },
            ]
        ),
        _iter_result(
            [
                {
                    "turn_index": 0,
                    "role": "user",
                    "content": "prior",
                    "ingested_at": "2026-03-01T00:00:00+00:00",
                },
                {
                    "turn_index": 2,
                    "role": "user",
                    "content": "future context",
                    "ingested_at": "2026-03-25T00:00:00+00:00",
                },
            ]
        ),
    ]

    pipeline = Mock()
    pipeline._conn = _mock_connection(session)
    pipeline._embedder = Mock()
    pipeline._embedder.embed.return_value = [0.1] * 768
    monkeypatch.setattr(tools_module, "_get_mcp_conversation_pipeline", lambda: pipeline)

    payload = asyncio.run(
        fake_mcp.tools["get_conversation_context"](
            query="memory",
            project_id="proj1",
            as_of="2026-03-05T00:00:00+00:00",
        )
    )

    assert len(payload["turns"]) == 1
    assert payload["turns"][0]["content"] == "current"
    assert payload["turns"][0]["context_window"] == [
        {
            "turn_index": 0,
            "role": "user",
            "content": "prior",
            "ingested_at": "2026-03-01T00:00:00+00:00",
        }
    ]
