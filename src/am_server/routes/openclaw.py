"""OpenClaw-facing endpoints for shared memory and context assembly."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends

from am_server.auth import require_auth
from am_server.dependencies import get_conversation_pipeline, get_pipeline, get_product_store
from am_server.models import (
    OpenClawContextResolveRequest,
    OpenClawMemorySearchRequest,
    OpenClawSessionRegisterRequest,
)
from agentic_memory.server.app import get_graph
from agentic_memory.server.unified_search import search_all_memory_sync

router = APIRouter(dependencies=[Depends(require_auth)])


def _serialize(value: object) -> object:
    """Serialize pydantic-like values without depending on a concrete model type."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _format_context_blocks(hits: Iterable[object]) -> list[dict[str, object]]:
    """Build context blocks from unified search hits."""
    blocks: list[dict[str, object]] = []
    for hit in hits:
        data = _serialize(hit)
        blocks.append(
            {
                "source": data.get("module") or data.get("domain") or "unknown",
                "title": data.get("title") or data.get("name") or data.get("path") or "hit",
                "score": data.get("score"),
                "content": data.get("content") or data.get("snippet") or data.get("text"),
                "provenance": data,
            }
        )
    return blocks


@router.post("/openclaw/session/register")
async def register_openclaw_session(body: OpenClawSessionRegisterRequest) -> dict:
    """Register an OpenClaw agent session in the local control plane."""
    store = get_product_store()
    integration = store.upsert_integration(
        surface="openclaw",
        target=f"{body.workspace_id}:{body.device_id}:{body.agent_id}",
        status="connected",
        config={
            "session_id": body.session_id,
            "workspace_id": body.workspace_id,
            "device_id": body.device_id,
            "agent_id": body.agent_id,
            "project_id": body.project_id,
            "context_engine": body.context_engine,
            "metadata": body.metadata,
        },
    )
    event = store.record_event(
        event_type="openclaw_session_registered",
        actor="openclaw",
        details={
            "workspace_id": body.workspace_id,
            "device_id": body.device_id,
            "agent_id": body.agent_id,
            "session_id": body.session_id,
            "project_id": body.project_id,
            "context_engine": body.context_engine,
            "metadata": body.metadata,
        },
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "integration": integration,
        "event": event,
    }


@router.post("/openclaw/memory/search")
async def search_openclaw_memory(body: OpenClawMemorySearchRequest) -> dict:
    """Search shared memory for an OpenClaw workspace/session."""
    graph = get_graph()
    research_pipeline = get_pipeline()
    conversation_pipeline = get_conversation_pipeline()
    response = search_all_memory_sync(
        query=body.query,
        limit=body.limit,
        project_id=body.project_id,
        as_of=body.as_of,
        modules=body.modules,
        graph=graph,
        research_pipeline=research_pipeline,
        conversation_pipeline=conversation_pipeline,
    )
    payload = _serialize(response)
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "results": payload.get("results", []),
        "response": payload,
    }


@router.post("/openclaw/context/resolve")
async def resolve_openclaw_context(body: OpenClawContextResolveRequest) -> dict:
    """Resolve context blocks for OpenClaw using current shared memory search."""
    search_response = await search_openclaw_memory(
        OpenClawMemorySearchRequest(
            workspace_id=body.workspace_id,
            device_id=body.device_id,
            agent_id=body.agent_id,
            session_id=body.session_id,
            project_id=body.project_id,
            metadata=body.metadata,
            query=body.query,
            limit=body.limit,
            as_of=body.as_of,
            modules=body.modules,
        )
    )
    blocks = _format_context_blocks(search_response.get("results", []))
    prompt_addition = None
    if body.include_system_prompt:
        prompt_addition = (
            "Use the retrieved OpenClaw workspace memory first; "
            "prefer recent session-specific hits when scores are similar."
        )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "context_engine": body.context_engine,
        "context_budget_tokens": body.context_budget_tokens,
        "system_prompt_addition": prompt_addition,
        "context_blocks": blocks,
        "search": search_response,
    }
