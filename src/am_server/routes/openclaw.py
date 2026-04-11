"""OpenClaw-facing endpoints for shared memory, project state, and context.

This router now models the product split explicitly:

- memory owns session registration, turn capture, search, and canonical reads
- project state decides whether a given session currently has an active
  ``project_id`` label
- context resolution is optional and sits downstream of memory capture

The OpenClaw plugin can therefore send turn-ingest events through a
memory-specific route even when it is running in "capture only" mode.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from am_server.auth import require_auth
from am_server.dependencies import get_conversation_pipeline, get_pipeline, get_product_store
from am_server.models import (
    ConversationIngestRequest,
    OpenClawProjectActivationRequest,
    OpenClawProjectAutomationRequest,
    OpenClawProjectDeactivationRequest,
    OpenClawProjectStatusRequest,
    OpenClawContextResolveRequest,
    OpenClawMemoryReadRequest,
    OpenClawMemorySearchRequest,
    OpenClawSessionRegisterRequest,
    OpenClawTurnIngestRequest,
)
from agentic_memory.server.app import get_graph
from agentic_memory.server.unified_search import search_all_memory_sync
from agentic_memory.temporal.seeds import parse_conversation_source_id

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


def _resolve_active_project_id(
    *,
    workspace_id: str,
    agent_id: str,
    session_id: str,
    explicit_project_id: str | None,
) -> str | None:
    """Resolve the effective project id for this OpenClaw request.

    Request-time explicit project ids win. When omitted, the local product
    store is treated as the source of truth for the session's current active
    project binding.
    """

    if explicit_project_id:
        return explicit_project_id

    store = get_product_store()
    binding = store.get_active_project_for_openclaw_identity(
        workspace_id=workspace_id,
        agent_id=agent_id,
        session_id=session_id,
    )
    return binding["project_id"] if binding else None


def _resolve_openclaw_session_id(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    explicit_session_id: str | None,
) -> str:
    """Resolve the effective OpenClaw session id for project lifecycle routes.

    The runtime always knows the current `session_id`, but plugin-owned CLI
    commands do not receive it from the current OpenClaw SDK surface. To keep
    project commands ergonomic, the backend falls back to the latest session
    registration for this workspace/agent/device identity.
    """

    store = get_product_store()
    session_id = store.resolve_openclaw_session_id(
        workspace_id=workspace_id,
        agent_id=agent_id,
        explicit_session_id=explicit_session_id,
        device_id=device_id,
    )
    if session_id:
        return session_id

    raise HTTPException(
        status_code=422,
        detail=(
            "No active OpenClaw session is registered for this workspace/agent. "
            "Start or resume an OpenClaw session first so Agentic Memory can "
            "infer the current session automatically."
        ),
    )


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


def _canonical_read_path(hit: dict[str, Any]) -> str:
    """Return the stable path token OpenClaw should use for follow-up reads.

    The plugin needs one identifier that survives across search and read calls.
    Unified search already guarantees `source_id`, so we promote that to the
    OpenClaw-facing `path` field.
    """

    return str(
        hit.get("path")
        or hit.get("source_id")
        or hit.get("sig")
        or hit.get("title")
        or "unknown"
    )


def _normalize_openclaw_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Translate unified search hits into the richer OpenClaw plugin shape."""

    metadata = hit.get("metadata") or {}
    turn_index = metadata.get("turn_index")
    line_number = int(turn_index) + 1 if isinstance(turn_index, int) else 1
    path = _canonical_read_path(hit)
    snippet = (
        hit.get("content")
        or hit.get("snippet")
        or hit.get("excerpt")
        or hit.get("text")
        or ""
    )

    return {
        **hit,
        "path": path,
        "start_line": line_number,
        "end_line": line_number,
        "snippet": snippet,
        "content": snippet,
        "citation": f"{path}#L{line_number}",
    }


def _fetch_conversation_turn_by_source_id(
    conversation_pipeline: Any,
    *,
    source_id: str,
) -> dict[str, Any] | None:
    """Read a conversation turn by the canonical `session_id:turn_index` source id."""

    session_id, turn_index = parse_conversation_source_id(source_id)
    with conversation_pipeline._conn.session() as session:  # type: ignore[attr-defined]
        result = session.run(
            (
                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id, turn_index: $turn_index}) "
                "RETURN "
                "    t.session_id AS session_id, "
                "    t.turn_index AS turn_index, "
                "    t.role AS role, "
                "    t.content AS content, "
                "    t.project_id AS project_id, "
                "    t.workspace_id AS workspace_id, "
                "    t.device_id AS device_id, "
                "    t.agent_id AS agent_id, "
                "    t.source_agent AS source_agent, "
                "    t.timestamp AS timestamp, "
                "    t.ingested_at AS ingested_at, "
                "    t.entities AS entities, "
                "    t.entity_types AS entity_types"
            ),
            session_id=session_id,
            turn_index=turn_index,
        ).single()
    return dict(result) if result else None


def _fetch_conversation_neighbors(
    conversation_pipeline: Any,
    *,
    session_id: str,
    turn_index: int,
) -> list[dict[str, Any]]:
    """Read immediate neighboring turns to provide useful canonical context."""

    with conversation_pipeline._conn.session() as session:  # type: ignore[attr-defined]
        result = session.run(
            (
                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id}) "
                "WHERE t.turn_index IN [$prev_index, $next_index] "
                "RETURN "
                "    t.turn_index AS turn_index, "
                "    t.role AS role, "
                "    t.content AS content "
                "ORDER BY t.turn_index"
            ),
            session_id=session_id,
            prev_index=turn_index - 1,
            next_index=turn_index + 1,
        )
        return [dict(row) for row in result]


def _format_conversation_read_document(
    turn: dict[str, Any],
    neighbors: list[dict[str, Any]],
) -> str:
    """Format a conversation turn and its immediate neighbors as canonical read text."""

    sections: list[str] = []
    for neighbor in neighbors:
        if int(neighbor.get("turn_index", -1)) < int(turn.get("turn_index", 0)):
            sections.append(
                f"[previous {neighbor.get('role', 'unknown')} turn #{neighbor.get('turn_index', '?')}]\n"
                f"{neighbor.get('content', '')}"
            )

    sections.append(
        f"[matched {turn.get('role', 'unknown')} turn #{turn.get('turn_index', '?')}]\n"
        f"{turn.get('content', '')}"
    )

    for neighbor in neighbors:
        if int(neighbor.get("turn_index", -1)) > int(turn.get("turn_index", 0)):
            sections.append(
                f"[next {neighbor.get('role', 'unknown')} turn #{neighbor.get('turn_index', '?')}]\n"
                f"{neighbor.get('content', '')}"
            )

    return "\n\n".join(section for section in sections if section.strip())


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
            "mode": body.mode,
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
            "mode": body.mode,
            "metadata": body.metadata,
        },
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "integration": integration,
        "event": event,
    }


@router.post("/openclaw/project/activate")
async def activate_openclaw_project(body: OpenClawProjectActivationRequest) -> dict:
    """Activate a reusable project label for one OpenClaw session."""

    session_id = _resolve_openclaw_session_id(
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        explicit_session_id=body.session_id,
    )
    store = get_product_store()
    binding = store.activate_project_for_openclaw_identity(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
        device_id=body.device_id,
        project_id=body.project_id,
        title=body.title,
        metadata=body.metadata,
    )
    event = store.record_event(
        event_type="openclaw_project_activated",
        actor="openclaw",
        details={
            "workspace_id": body.workspace_id,
            "device_id": body.device_id,
            "agent_id": body.agent_id,
            "session_id": session_id,
            "project_id": body.project_id,
        },
    )
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "session_id": session_id},
        "binding": binding,
        "event": event,
    }


@router.post("/openclaw/project/deactivate")
async def deactivate_openclaw_project(body: OpenClawProjectDeactivationRequest) -> dict:
    """Clear the active project for one OpenClaw session."""

    session_id = _resolve_openclaw_session_id(
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        explicit_session_id=body.session_id,
    )
    store = get_product_store()
    removed = store.deactivate_project_for_openclaw_identity(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
    )
    event = store.record_event(
        event_type="openclaw_project_deactivated",
        actor="openclaw",
        details={
            "workspace_id": body.workspace_id,
            "device_id": body.device_id,
            "agent_id": body.agent_id,
            "session_id": session_id,
            "project_id": removed["project_id"] if removed else None,
        },
    )
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "session_id": session_id},
        "binding": removed,
        "event": event,
    }


@router.post("/openclaw/project/status")
async def status_openclaw_project(body: OpenClawProjectStatusRequest) -> dict:
    """Return the current active project binding for one OpenClaw session."""

    session_id = _resolve_openclaw_session_id(
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        explicit_session_id=body.session_id,
    )
    store = get_product_store()
    binding = store.get_active_project_for_openclaw_identity(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
    )
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "session_id": session_id},
        "active_project": binding,
    }


@router.post("/openclaw/project/automation")
async def automate_openclaw_project(body: OpenClawProjectAutomationRequest) -> dict:
    """Create or update a workspace-scoped project automation record."""

    store = get_product_store()
    automation = store.upsert_project_automation(
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        automation_kind=body.automation_kind,
        enabled=body.enabled,
        metadata=body.metadata,
    )
    event = store.record_event(
        event_type="openclaw_project_automation_updated",
        actor="openclaw",
        details=automation,
    )
    return {"status": "ok", "automation": automation, "event": event}


@router.post("/openclaw/memory/ingest-turn", status_code=202)
async def ingest_openclaw_turn(body: OpenClawTurnIngestRequest) -> dict:
    """Ingest one OpenClaw conversation turn through the memory contract.

    This route keeps project resolution on the server side. The plugin can
    therefore capture memory continuously without baking a static project tag
    into install-time config.
    """

    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )

    pipeline = get_conversation_pipeline()
    conversation_payload = ConversationIngestRequest(
        role=body.role,
        content=body.content,
        session_id=body.session_id,
        project_id=effective_project_id,
        turn_index=body.turn_index,
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        source_agent=body.source_agent,
        model=body.model,
        tool_name=body.tool_name,
        tool_call_id=body.tool_call_id,
        tokens_input=body.tokens_input,
        tokens_output=body.tokens_output,
        timestamp=body.timestamp,
        ingestion_mode=body.ingestion_mode,
        source_key=body.source_key,
    )

    try:
        result = pipeline.ingest(conversation_payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": "ok",
        "identity": body.model_dump(),
        "effective_project_id": effective_project_id,
        "result": result,
    }


@router.post("/openclaw/memory/search")
async def search_openclaw_memory(body: OpenClawMemorySearchRequest) -> dict:
    """Search shared memory for an OpenClaw workspace/session."""
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )
    graph = get_graph()
    research_pipeline = get_pipeline()
    conversation_pipeline = get_conversation_pipeline()
    response = search_all_memory_sync(
        query=body.query,
        limit=body.limit,
        project_id=effective_project_id,
        as_of=body.as_of,
        modules=body.modules,
        graph=graph,
        research_pipeline=research_pipeline,
        conversation_pipeline=conversation_pipeline,
    )
    payload = _serialize(response)
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "project_id": effective_project_id},
        "results": [
            _normalize_openclaw_hit(hit) for hit in payload.get("results", [])
        ],
        "response": payload,
    }


@router.post("/openclaw/memory/read")
async def read_openclaw_memory(body: OpenClawMemoryReadRequest) -> dict:
    """Read canonical memory content for a previously returned OpenClaw search hit.

    v1 intentionally supports canonical reads for conversation turns first.
    Other hit types still rely on the plugin's cached snippet fallback until
    we add dedicated read contracts for code and research memory.
    """

    canonical_path = body.rel_path.split("#", 1)[0].strip()
    conversation_pipeline = get_conversation_pipeline()

    try:
        session_id, turn_index = parse_conversation_source_id(canonical_path)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Canonical OpenClaw reads currently support conversation-turn "
                f"source ids only. Unsupported path: {canonical_path}"
            ),
        ) from exc

    turn = _fetch_conversation_turn_by_source_id(
        conversation_pipeline,
        source_id=canonical_path,
    )
    if turn is None:
        raise HTTPException(
            status_code=404,
            detail=f"No OpenClaw memory turn found for {canonical_path}",
        )

    neighbors = _fetch_conversation_neighbors(
        conversation_pipeline,
        session_id=session_id,
        turn_index=turn_index,
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "path": canonical_path,
        "source_kind": "conversation_turn",
        "text": _format_conversation_read_document(turn, neighbors),
        "matched_turn": turn,
        "neighbors": neighbors,
    }


@router.post("/openclaw/context/resolve")
async def resolve_openclaw_context(body: OpenClawContextResolveRequest) -> dict:
    """Resolve context blocks for OpenClaw using current shared memory search."""
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )
    search_response = await search_openclaw_memory(
        OpenClawMemorySearchRequest(
            workspace_id=body.workspace_id,
            device_id=body.device_id,
            agent_id=body.agent_id,
            session_id=body.session_id,
            project_id=effective_project_id,
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
        "identity": {**body.model_dump(), "project_id": effective_project_id},
        "context_engine": body.context_engine,
        "context_budget_tokens": body.context_budget_tokens,
        "system_prompt_addition": prompt_addition,
        "context_blocks": blocks,
        "search": search_response,
    }
