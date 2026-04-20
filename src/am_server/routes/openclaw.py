"""HTTP API for the OpenClaw (Claude Code plugin) integration.

Exposes session registration, project activation lifecycle, conversation turn
ingest, unified memory search/read, and optional context-block assembly for the
plugin. The design splits concerns so **memory** (ingest/search/read) can run
even when the client is in capture-only mode, while **project state** (active
``project_id`` per workspace/agent/session) is resolved server-side from the
product store when the request omits it.

**Router-level contract**

- Every route on this ``APIRouter`` depends on ``require_auth`` (API key or
  equivalent as configured in ``am_server.auth``).

**Major dependencies**

- ``am_server.dependencies.get_product_store`` — OpenClaw identity, project
  bindings, automation records, audit events.
- ``am_server.dependencies.pipelines_for_openclaw_workspace`` /
  ``graph_for_openclaw_workspace`` — Pick shared Neo4j vs operator private
  Neo4j (see ``am_server.neo4j_routing``) for ingest, search, and read.
- ``agentic_memory.server.unified_search.search_all_memory_sync`` — Single entry
  for cross-domain search.
- ``am_server.metrics`` — Counters/histograms for OpenClaw operations.

**Caching**

- In-process TTL caches reduce load for project status and search; keys are
  scoped by workspace/device/agent/session (and search parameters) so tenants
  do not leak results across identities.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
import inspect
import json
from collections.abc import Iterable
from threading import Lock
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from am_server.auth import ensure_workspace_access, require_auth
from am_server.dependencies import (
    get_product_store,
    graph_for_openclaw_workspace,
    pipelines_for_openclaw_workspace,
)
from am_server.metrics import (
    record_openclaw_context_resolve,
    record_openclaw_ingest_error,
    record_openclaw_search,
    record_openclaw_session_registration,
    record_openclaw_turn_ingest,
)
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
    OpenClawToolConversationContextRequest,
    OpenClawToolConversationSearchRequest,
    OpenClawToolFileDependenciesRequest,
    OpenClawToolSearchCodebaseRequest,
    OpenClawToolTraceExecutionPathRequest,
    OpenClawTurnIngestRequest,
)
from agentic_memory.server.temporal_contract import TemporalRetrievalRequiredError
from agentic_memory.server.unified_search import search_all_memory_sync
from agentic_memory.temporal.seeds import parse_conversation_source_id

router = APIRouter(dependencies=[Depends(require_auth)])
PROJECT_STATUS_CACHE_TTL_SECONDS = 60.0
SEARCH_CACHE_TTL_SECONDS = 30.0
_CACHE_LOCK = Lock()
_PROJECT_STATUS_CACHE: dict[tuple[str, str, str, str], tuple[float, dict[str, Any] | None]] = {}
_SEARCH_CACHE: dict[tuple[str, str, str, str, str | None, str, int, str | None, tuple[str, ...]], tuple[float, dict[str, Any]]] = {}
_CACHE_MISS = object()


def _record_workspace_usage(*, workspace_id: str, metric: str, metadata: dict[str, Any] | None = None) -> None:
    """Increment one hosted-beta usage counter for the current workspace."""

    store = get_product_store()
    if not hasattr(store, "record_usage_counter"):
        return
    store.record_usage_counter(
        workspace_id=workspace_id,
        metric=metric,
        amount=1,
        metadata=metadata or {},
    )


def _serialize(value: object) -> object:
    """Serialize route payloads into plain JSON-safe Python objects.

    The OpenClaw routes sit on top of a few different internal result types:

    - Pydantic models expose ``model_dump()``
    - dataclass payloads such as ``UnifiedSearchResponse`` expose ``to_dict()``
      or can be converted with ``dataclasses.asdict``
    - some route helpers return nested lists / dicts directly

    Earlier versions of this adapter only knew about ``model_dump()``. That was
    enough for Pydantic models, but it broke once the unified search path
    started returning dataclass-based responses. The result was an
    ``AttributeError`` later in the route when the code assumed the serialized
    payload had ``dict`` methods like ``.get(...)``.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "to_dict"):
        return _serialize(value.to_dict())
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _coerce_serialized_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    """Return one serialized mapping or raise a stable adapter error.

    OpenClaw routes often need to preserve the raw structured payload for
    debugging while also reshaping part of it for the plugin. This helper keeps
    that boundary explicit: after serialization, the adapter expects a mapping.
    If an internal helper returns some other shape, we fail with a targeted
    error instead of a later ``AttributeError``.
    """

    serialized = _serialize(value)
    if isinstance(serialized, dict):
        return serialized
    raise TypeError(
        f"Expected `{field_name}` to serialize into an object mapping, "
        f"but got `{type(serialized).__name__}`."
    )


def _coerce_serialized_hit_rows(value: object, *, field_name: str) -> list[dict[str, Any]]:
    """Return a list of search-hit mappings after defensive serialization."""

    serialized = _serialize(value)
    if serialized is None:
        return []
    if not isinstance(serialized, list):
        raise TypeError(
            f"Expected `{field_name}` to serialize into a list, "
            f"but got `{type(serialized).__name__}`."
        )

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(serialized):
        if not isinstance(item, dict):
            raise TypeError(
                f"Expected `{field_name}[{index}]` to serialize into an object mapping, "
                f"but got `{type(item).__name__}`."
            )
        rows.append(item)
    return rows


async def _resolve_openclaw_tool_text_result(result: object) -> str:
    """Normalize OpenClaw tool bridge results into plain text.

    The public Agentic Memory tool implementations are MCP-decorated. Importing
    them directly into FastAPI routes means the callable may return a coroutine
    because the telemetry/rate-limit wrapper is async even when the underlying
    tool logic is synchronous. The OpenClaw adapter should therefore:

    1. await any awaitable result
    2. preserve plain strings unchanged
    3. JSON-stringify structured fallbacks so FastAPI never tries to serialize
       a coroutine or opaque object itself
    """

    resolved = await result if inspect.isawaitable(result) else result
    if isinstance(resolved, str):
        return resolved

    serialized = _serialize(resolved)
    if isinstance(serialized, str):
        return serialized
    return json.dumps(serialized, indent=2, sort_keys=True, default=str)


def _monotonic_now() -> float:
    """Return the monotonic clock used for TTL caches."""

    return time.monotonic()


def _project_status_cache_key(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    session_id: str,
) -> tuple[str, str, str, str]:
    """Return the cache key for one resolved OpenClaw project-status lookup."""

    return (
        workspace_id,
        device_id,
        agent_id,
        session_id,
    )


def _search_cache_key(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    session_id: str,
    project_id: str | None,
    query: str,
    limit: int,
    as_of: str | None,
    modules: list[str] | None,
) -> tuple[str, str, str, str, str | None, str, int, str | None, tuple[str, ...]]:
    """Return the cache key for one OpenClaw search request.

    The cache key stays fully identity-scoped so one agent or workspace never
    receives another agent's cached search results.
    """

    normalized_modules = tuple(sorted({module.strip() for module in (modules or []) if module.strip()}))
    return (
        workspace_id,
        device_id,
        agent_id,
        session_id,
        project_id,
        query,
        limit,
        as_of,
        normalized_modules,
    )


def _read_cached_project_status(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    session_id: str,
) -> object:
    """Return the cached active-project binding for one OpenClaw session.

    Returns the binding value, `None` when a cached lookup found no project,
    or `_CACHE_MISS` when the cache has no fresh entry.
    """

    key = _project_status_cache_key(
        workspace_id=workspace_id,
        device_id=device_id,
        agent_id=agent_id,
        session_id=session_id,
    )
    now = _monotonic_now()
    with _CACHE_LOCK:
        cached = _PROJECT_STATUS_CACHE.get(key)
        if cached is None:
            return _CACHE_MISS
        expires_at, binding = cached
        if expires_at <= now:
            _PROJECT_STATUS_CACHE.pop(key, None)
            return _CACHE_MISS
        return copy.deepcopy(binding)


def _write_cached_project_status(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    session_id: str,
    binding: dict[str, Any] | None,
) -> None:
    """Store one resolved project-status lookup in the in-process TTL cache."""

    key = _project_status_cache_key(
        workspace_id=workspace_id,
        device_id=device_id,
        agent_id=agent_id,
        session_id=session_id,
    )
    with _CACHE_LOCK:
        _PROJECT_STATUS_CACHE[key] = (
            _monotonic_now() + PROJECT_STATUS_CACHE_TTL_SECONDS,
            copy.deepcopy(binding),
        )


def _read_cached_search_response(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    session_id: str,
    project_id: str | None,
    query: str,
    limit: int,
    as_of: str | None,
    modules: list[str] | None,
) -> dict[str, Any] | None:
    """Return a cached OpenClaw search response when one is still fresh."""

    key = _search_cache_key(
        workspace_id=workspace_id,
        device_id=device_id,
        agent_id=agent_id,
        session_id=session_id,
        project_id=project_id,
        query=query,
        limit=limit,
        as_of=as_of,
        modules=modules,
    )
    now = _monotonic_now()
    with _CACHE_LOCK:
        cached = _SEARCH_CACHE.get(key)
        if cached is None:
            return None
        expires_at, payload = cached
        if expires_at <= now:
            _SEARCH_CACHE.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _write_cached_search_response(
    *,
    workspace_id: str,
    device_id: str,
    agent_id: str,
    session_id: str,
    project_id: str | None,
    query: str,
    limit: int,
    as_of: str | None,
    modules: list[str] | None,
    payload: dict[str, Any],
) -> None:
    """Store one successful OpenClaw search response in the TTL cache."""

    key = _search_cache_key(
        workspace_id=workspace_id,
        device_id=device_id,
        agent_id=agent_id,
        session_id=session_id,
        project_id=project_id,
        query=query,
        limit=limit,
        as_of=as_of,
        modules=modules,
    )
    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = (
            _monotonic_now() + SEARCH_CACHE_TTL_SECONDS,
            copy.deepcopy(payload),
        )


def _invalidate_project_status_cache(
    *,
    workspace_id: str,
    agent_id: str,
    session_id: str | None = None,
    device_id: str | None = None,
) -> None:
    """Invalidate cached project-status lookups for one OpenClaw identity scope."""

    with _CACHE_LOCK:
        keys_to_delete = [
            key
            for key in _PROJECT_STATUS_CACHE
            if key[0] == workspace_id
            and key[2] == agent_id
            and (session_id is None or key[3] == session_id)
            and (device_id is None or key[1] == device_id)
        ]
        for key in keys_to_delete:
            _PROJECT_STATUS_CACHE.pop(key, None)


def _invalidate_search_cache(
    *,
    workspace_id: str,
    agent_id: str,
    session_id: str | None = None,
    device_id: str | None = None,
) -> None:
    """Invalidate cached OpenClaw search results for one identity scope."""

    with _CACHE_LOCK:
        keys_to_delete = [
            key
            for key in _SEARCH_CACHE
            if key[0] == workspace_id
            and key[2] == agent_id
            and (session_id is None or key[3] == session_id)
            and (device_id is None or key[1] == device_id)
        ]
        for key in keys_to_delete:
            _SEARCH_CACHE.pop(key, None)


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


def _format_openclaw_tool_search_results(
    title: str,
    query: str,
    results: Iterable[dict[str, Any]],
) -> str:
    """Render normalized search hits into one compact text response.

    The OpenClaw tool bridge returns plain text so the agent can use the result
    without needing to reason about a secondary JSON envelope. We still keep the
    raw payload in the HTTP response for debugging and future structured usage.
    """

    normalized_results = list(results)
    if not normalized_results:
        return f"## {title}\n\nQuery: `{query}`\n\nNo results found."

    lines = [f"## {title}", "", f"Query: `{query}`", ""]
    for index, hit in enumerate(normalized_results, start=1):
        title_text = str(hit.get("title") or hit.get("name") or hit.get("path") or "result")
        path = str(hit.get("path") or "unknown")
        score = hit.get("score")
        snippet = str(hit.get("snippet") or hit.get("content") or hit.get("text") or "").strip()

        lines.append(f"{index}. {title_text}")
        lines.append(f"Path: `{path}`")
        if isinstance(score, (int, float)):
            lines.append(f"Score: {float(score):.3f}")
        if snippet:
            lines.append(f"Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_openclaw_conversation_context_text(
    *,
    query: str,
    project_id: str,
    turns: Iterable[dict[str, Any]],
) -> str:
    """Render structured conversation-context rows into a readable report."""

    matched_turns = list(turns)
    if not matched_turns:
        return (
            "## Conversation Context\n\n"
            f"Query: `{query}`\n"
            f"Project: `{project_id}`\n\n"
            "No conversation context found."
        )

    lines = [
        "## Conversation Context",
        "",
        f"Query: `{query}`",
        f"Project: `{project_id}`",
        "",
    ]
    for index, turn in enumerate(matched_turns, start=1):
        lines.append(
            f"{index}. session `{turn.get('session_id', 'unknown')}` turn #{turn.get('turn_index', '?')}"
        )
        lines.append(f"Role: `{turn.get('role', 'unknown')}`")
        content = str(turn.get("content") or "").strip()
        if content:
            lines.append(f"Content: {content}")
        context_window = turn.get("context_window") or []
        if context_window:
            lines.append("Context window:")
            for neighbor in context_window:
                lines.append(
                    f"- `{neighbor.get('role', 'unknown')}` turn #{neighbor.get('turn_index', '?')}: "
                    f"{neighbor.get('content', '')}"
                )
        lines.append("")
    return "\n".join(lines).strip()


@router.post("/openclaw/session/register")
async def register_openclaw_session(request: Request, body: OpenClawSessionRegisterRequest) -> dict:
    """Register or refresh an OpenClaw session in the local product store.

    Persists workspace/device/agent/session metadata and records an audit event.
    Invalidates in-process project-status and search caches for this identity so
    subsequent reads reflect the new registration.

    Args:
        body: OpenClaw identity, session id, optional project/context fields, and
            opaque metadata from the plugin.

    Returns:
        JSON with ``status`` ``"ok"``, echoed ``identity``, updated
        ``integration`` record, and ``event`` audit entry.

    Dependencies:
        ``get_product_store`` (implicit via ``get_product_store()``).
    """
    ensure_workspace_access(request, body.workspace_id)
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
    record_openclaw_session_registration(
        workspace_id=body.workspace_id,
        session_id=body.session_id,
    )
    _record_workspace_usage(
        workspace_id=body.workspace_id,
        metric="openclaw_session_register",
        metadata={"agent_id": body.agent_id},
    )
    _invalidate_project_status_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        device_id=body.device_id,
    )
    _invalidate_search_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        device_id=body.device_id,
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "integration": integration,
        "event": event,
    }


@router.post("/openclaw/project/activate")
async def activate_openclaw_project(request: Request, body: OpenClawProjectActivationRequest) -> dict:
    """Bind an active ``project_id`` to the resolved OpenClaw session.

    If ``body.session_id`` is omitted, the backend infers the current session
    from the latest registration for the workspace/agent/device tuple (see
    ``_resolve_openclaw_session_id``).

    Args:
        body: Workspace, device, agent, optional session, project id, title, and
            metadata.

    Returns:
        JSON with ``status`` ``"ok"``, ``identity`` including the resolved
        ``session_id``, ``binding`` from the store, and ``event``.

    Raises:
        HTTPException: 422 when no session can be inferred for the identity.
    """
    ensure_workspace_access(request, body.workspace_id)
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
    _invalidate_project_status_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
        device_id=body.device_id,
    )
    _invalidate_search_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
        device_id=body.device_id,
    )
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "session_id": session_id},
        "binding": binding,
        "event": event,
    }


@router.post("/openclaw/project/deactivate")
async def deactivate_openclaw_project(request: Request, body: OpenClawProjectDeactivationRequest) -> dict:
    """Remove the active project binding for the resolved OpenClaw session.

    Session resolution matches ``activate_openclaw_project``.

    Args:
        body: Workspace, device, agent, and optional session id.

    Returns:
        JSON with ``status`` ``"ok"``, ``identity`` with resolved ``session_id``,
        ``binding`` (removed record, if any), and ``event``.

    Raises:
        HTTPException: 422 when session id cannot be resolved.
    """
    ensure_workspace_access(request, body.workspace_id)
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
    _invalidate_project_status_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
        device_id=body.device_id,
    )
    _invalidate_search_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=session_id,
        device_id=body.device_id,
    )
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "session_id": session_id},
        "binding": removed,
        "event": event,
    }


@router.post("/openclaw/project/status")
async def status_openclaw_project(request: Request, body: OpenClawProjectStatusRequest) -> dict:
    """Return the active project binding for the resolved OpenClaw session.

    Uses a short TTL in-process cache keyed by workspace/device/agent/session
    to reduce repeated store reads.

    Args:
        body: Workspace, device, agent, and optional session id.

    Returns:
        JSON with ``status`` ``"ok"``, ``identity`` including resolved
        ``session_id``, and ``active_project`` (store binding or null).

    Raises:
        HTTPException: 422 when session id cannot be resolved.
    """
    ensure_workspace_access(request, body.workspace_id)
    session_id = _resolve_openclaw_session_id(
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        explicit_session_id=body.session_id,
    )
    cached_binding = _read_cached_project_status(
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        session_id=session_id,
    )
    if cached_binding is _CACHE_MISS:
        store = get_product_store()
        binding = store.get_active_project_for_openclaw_identity(
            workspace_id=body.workspace_id,
            agent_id=body.agent_id,
            session_id=session_id,
        )
        _write_cached_project_status(
            workspace_id=body.workspace_id,
            device_id=body.device_id,
            agent_id=body.agent_id,
            session_id=session_id,
            binding=binding,
        )
    else:
        binding = cached_binding
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "session_id": session_id},
        "active_project": binding,
    }


@router.post("/openclaw/project/automation")
async def automate_openclaw_project(request: Request, body: OpenClawProjectAutomationRequest) -> dict:
    """Upsert automation settings for a project within a workspace.

    Args:
        body: Workspace id, project id, automation kind, enabled flag, and
            optional metadata.

    Returns:
        JSON with ``status`` ``"ok"``, persisted ``automation``, and ``event``.
    """
    ensure_workspace_access(request, body.workspace_id)
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
async def ingest_openclaw_turn(request: Request, body: OpenClawTurnIngestRequest) -> dict:
    """Accept one conversation turn and persist it via the conversation pipeline.

    Effective ``project_id`` is resolved server-side (explicit body value wins;
    otherwise the product store's active binding for the session). That lets
    the plugin stream turns without embedding a fixed project id in config.

    Args:
        body: Turn content, indices, workspace/agent/device/session ids, model
            metadata, and ingestion mode fields matching
            ``ConversationIngestRequest``.

    Returns:
        JSON with ``status`` ``"ok"``, request ``identity``, resolved
        ``effective_project_id``, and pipeline ``result`` (shape defined by the
        conversation pipeline).

    Raises:
        HTTPException: 422 when the pipeline rejects the payload (e.g. invalid
            combination of fields); error is logged to OpenClaw ingest metrics.

    Note:
        Responds with HTTP 202 Accepted (see route ``status_code``).
    """
    ensure_workspace_access(request, body.workspace_id)
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )

    _, pipeline = pipelines_for_openclaw_workspace(body.workspace_id)
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
        # Pipeline validation uses ValueError; map to 422 for consistent client handling.
        record_openclaw_ingest_error(
            workspace_id=body.workspace_id,
            error_code="validation_error",
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record_openclaw_turn_ingest(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        source_key=body.source_key,
    )
    _record_workspace_usage(
        workspace_id=body.workspace_id,
        metric="openclaw_turn_ingest",
        metadata={"agent_id": body.agent_id, "source_key": body.source_key},
    )
    _invalidate_search_cache(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        device_id=body.device_id,
    )

    return {
        "status": "ok",
        "identity": body.model_dump(),
        "effective_project_id": effective_project_id,
        "result": result,
    }


@router.post("/openclaw/memory/search")
async def search_openclaw_memory(request: Request, body: OpenClawMemorySearchRequest) -> dict:
    """Run unified memory search scoped to the effective project and identity.

    Results pass through ``search_all_memory_sync`` (code graph + research +
    conversation backends). Responses are cached briefly per identity and query
    parameters to reduce duplicate work.

    Args:
        body: Query string, limit, optional ``as_of``, optional module filter,
            workspace/device/agent/session, and optional explicit ``project_id``.

    Returns:
        JSON with ``status`` ``"ok"``, ``identity`` including resolved
        ``project_id``, ``cache_hit`` boolean, ``results`` (OpenClaw-normalized
        hits), and raw ``response`` from unified search (serialized).

    Dependencies:
        ``graph_for_openclaw_workspace`` and ``pipelines_for_openclaw_workspace``
        for the search call; product store for events.
    """
    ensure_workspace_access(request, body.workspace_id)
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )
    started = time.perf_counter()
    cache_hit = False
    cached_payload = _read_cached_search_response(
        workspace_id=body.workspace_id,
        device_id=body.device_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        project_id=effective_project_id,
        query=body.query,
        limit=body.limit,
        as_of=body.as_of,
        modules=body.modules,
    )
    if cached_payload is None:
        graph = graph_for_openclaw_workspace(body.workspace_id)
        research_pipeline, conversation_pipeline = pipelines_for_openclaw_workspace(
            body.workspace_id
        )
        try:
            response = search_all_memory_sync(
                query=body.query,
                limit=body.limit,
                project_id=effective_project_id,
                as_of=body.as_of,
                modules=body.modules,
                graph=graph,
                research_pipeline=research_pipeline,
                conversation_pipeline=conversation_pipeline,
                fail_on_temporal_errors=True,
            )
        except TemporalRetrievalRequiredError as exc:
            raise HTTPException(status_code=503, detail=exc.to_http_detail()) from exc
        payload = _coerce_serialized_mapping(response, field_name="search_response")
        _write_cached_search_response(
            workspace_id=body.workspace_id,
            device_id=body.device_id,
            agent_id=body.agent_id,
            session_id=body.session_id,
            project_id=effective_project_id,
            query=body.query,
            limit=body.limit,
            as_of=body.as_of,
            modules=body.modules,
            payload=payload,
        )
    else:
        payload = cached_payload
        cache_hit = True

    raw_hits = _coerce_serialized_hit_rows(payload.get("results"), field_name="search_response.results")

    duration = time.perf_counter() - started
    record_openclaw_search(
        workspace_id=body.workspace_id,
        modules=body.modules,
        duration_seconds=duration,
    )
    _record_workspace_usage(
        workspace_id=body.workspace_id,
        metric="openclaw_memory_search",
        metadata={"agent_id": body.agent_id},
    )
    get_product_store().record_event(
        event_type="openclaw_memory_search",
        actor="openclaw",
        details={
            "workspace_id": body.workspace_id,
            "device_id": body.device_id,
            "agent_id": body.agent_id,
            "session_id": body.session_id,
            "project_id": effective_project_id,
            "query": body.query,
            "limit": body.limit,
            "result_count": len(payload.get("results", [])),
            "modules": body.modules or [],
            "cache_hit": cache_hit,
        },
    )
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "project_id": effective_project_id},
        "cache_hit": cache_hit,
        "results": [_normalize_openclaw_hit(hit) for hit in raw_hits],
        "response": payload,
    }


@router.post("/openclaw/memory/read")
async def read_openclaw_memory(request: Request, body: OpenClawMemoryReadRequest) -> dict:
    """Fetch full text for a hit previously returned by search (v1: turns only).

    Only conversation-turn source ids (``session_id:turn_index`` form after
    stripping URL fragments) are supported. Code and research hits still depend
    on client-side snippets until dedicated read contracts exist.

    Args:
        body: ``rel_path`` from the plugin — may include a ``#L`` fragment; the
            fragment is ignored for Neo4j lookup.

    Returns:
        JSON with ``status`` ``"ok"``, ``identity``, normalized ``path``, ``text``
        assembled with neighbor turns for context, ``matched_turn``, and
        ``neighbors``.

    Raises:
        HTTPException: 404 when the path is not a valid conversation source id
            or no turn exists in the graph.
    """

    ensure_workspace_access(request, body.workspace_id)
    # Search hits may cite "#L{line}" — canonical id is the path before the fragment.
    canonical_path = body.rel_path.split("#", 1)[0].strip()
    _, conversation_pipeline = pipelines_for_openclaw_workspace(body.workspace_id)

    try:
        session_id, turn_index = parse_conversation_source_id(canonical_path)
    except ValueError as exc:
        # Unsupported path shape for v1 read contract (not a conversation source id).
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


@router.post("/openclaw/tools/search-codebase")
async def search_openclaw_tool_codebase(
    request: Request,
    body: OpenClawToolSearchCodebaseRequest,
) -> dict:
    """Bridge the public `search_codebase` tool into the OpenClaw plugin surface."""

    from agentic_memory.server.app import search_codebase

    ensure_workspace_access(request, body.workspace_id)
    text = await _resolve_openclaw_tool_text_result(
        search_codebase(
            query=body.query,
            limit=body.limit,
            domain=body.domain,
            repo_id=body.repo_id,
        )
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "text": text,
    }


@router.post("/openclaw/tools/get-file-dependencies")
async def get_openclaw_tool_file_dependencies(
    request: Request,
    body: OpenClawToolFileDependenciesRequest,
) -> dict:
    """Bridge the public `get_file_dependencies` tool into OpenClaw."""

    from agentic_memory.server.app import get_file_dependencies

    ensure_workspace_access(request, body.workspace_id)
    text = await _resolve_openclaw_tool_text_result(
        get_file_dependencies(
            file_path=body.file_path,
            repo_id=body.repo_id,
        )
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "text": text,
    }


@router.post("/openclaw/tools/trace-execution-path")
async def trace_openclaw_tool_execution_path(
    request: Request,
    body: OpenClawToolTraceExecutionPathRequest,
) -> dict:
    """Bridge the public `trace_execution_path` tool into OpenClaw."""

    from agentic_memory.server.app import trace_execution_path

    ensure_workspace_access(request, body.workspace_id)
    text = await _resolve_openclaw_tool_text_result(
        trace_execution_path(
            start_symbol=body.start_symbol,
            max_depth=body.max_depth,
            force_refresh=body.force_refresh,
            repo_id=body.repo_id,
        )
    )
    return {
        "status": "ok",
        "identity": body.model_dump(),
        "text": text,
    }


@router.post("/openclaw/tools/search-conversations")
async def search_openclaw_tool_conversations(
    request: Request,
    body: OpenClawToolConversationSearchRequest,
) -> dict:
    """Bridge `search_conversations` into OpenClaw with session/project routing."""

    from agentic_memory.server.tools import search_conversation_turns_sync

    ensure_workspace_access(request, body.workspace_id)
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )
    _, conversation_pipeline = pipelines_for_openclaw_workspace(body.workspace_id)
    try:
        results = search_conversation_turns_sync(
            conversation_pipeline,
            query=body.query,
            project_id=effective_project_id,
            role=body.role,
            limit=body.limit,
            as_of=body.as_of,
            log_prefix="openclaw.tools.search_conversations",
            temporal_required=True,
        )
    except TemporalRetrievalRequiredError as exc:
        raise HTTPException(status_code=503, detail=exc.to_http_detail()) from exc
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "project_id": effective_project_id},
        "text": _format_openclaw_tool_search_results(
            "Conversation Search",
            body.query,
            results,
        ),
        "payload": {
            "results": results,
        },
    }


@router.post("/openclaw/tools/get-conversation-context")
async def get_openclaw_tool_conversation_context(
    request: Request,
    body: OpenClawToolConversationContextRequest,
) -> dict:
    """Bridge `get_conversation_context` into OpenClaw with active-project resolution."""

    from agentic_memory.server.tools import (
        _fetch_conversation_context_window,
        search_conversation_turns_sync,
    )

    ensure_workspace_access(request, body.workspace_id)
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )
    if not effective_project_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Conversation context requires an active project. "
                "Start a project for this session or pass an explicit project_id."
            ),
        )

    _, conversation_pipeline = pipelines_for_openclaw_workspace(body.workspace_id)
    conn = conversation_pipeline._conn  # type: ignore[attr-defined]
    try:
        matched_turns = search_conversation_turns_sync(
            conversation_pipeline,
            query=body.query,
            project_id=effective_project_id,
            role=None,
            limit=body.limit,
            as_of=body.as_of,
            log_prefix="openclaw.tools.get_conversation_context",
            temporal_required=True,
        )
    except TemporalRetrievalRequiredError as exc:
        raise HTTPException(status_code=503, detail=exc.to_http_detail()) from exc
    turns_with_context: list[dict[str, Any]] = []
    for turn in matched_turns:
        turn_data = dict(turn)
        turn_data["context_window"] = (
            _fetch_conversation_context_window(
                conn,
                session_id=turn["session_id"],
                turn_index=turn["turn_index"],
                as_of=body.as_of,
            )
            if body.include_session_context
            else []
        )
        turns_with_context.append(turn_data)

    payload = {
        "query": body.query,
        "project_id": effective_project_id,
        "turns": turns_with_context,
    }
    return {
        "status": "ok",
        "identity": {**body.model_dump(), "project_id": effective_project_id},
        "text": _format_openclaw_conversation_context_text(
            query=body.query,
            project_id=effective_project_id,
            turns=turns_with_context,
        ),
        "payload": payload,
    }


@router.post("/openclaw/context/resolve")
async def resolve_openclaw_context(request: Request, body: OpenClawContextResolveRequest) -> dict:
    """Build LLM-oriented context blocks from a memory search for this session.

    Internally reuses ``search_openclaw_memory`` with the same identity and
    search fields, then formats hits into ``context_blocks``. Optionally appends
    a short system-prompt hint when ``include_system_prompt`` is true.

    Args:
        body: Same search scoping as memory search, plus ``context_engine``,
            optional ``context_budget_tokens`` (advisory), and
            ``include_system_prompt``.

    Returns:
        JSON with ``status`` ``"ok"``, ``identity`` with resolved ``project_id``,
        ``context_engine``, ``context_budget_tokens``, optional
        ``system_prompt_addition``, ``context_blocks``, and embedded ``search``
        payload from the inner search call.

    Dependencies:
        Product store for audit event; OpenClaw context-resolve metric.
    """
    ensure_workspace_access(request, body.workspace_id)
    effective_project_id = _resolve_active_project_id(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        explicit_project_id=body.project_id,
    )
    started = time.perf_counter()
    search_response = await search_openclaw_memory(
        request,
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
    record_openclaw_context_resolve(duration_seconds=time.perf_counter() - started)
    _record_workspace_usage(
        workspace_id=body.workspace_id,
        metric="openclaw_context_resolve",
        metadata={"agent_id": body.agent_id, "context_engine": body.context_engine},
    )
    blocks = _format_context_blocks(search_response.get("results", []))
    prompt_addition = None
    if body.include_system_prompt:
        prompt_addition = (
            "Use the retrieved OpenClaw workspace memory first; "
            "prefer recent session-specific hits when scores are similar."
        )
    get_product_store().record_event(
        event_type="openclaw_context_resolve",
        actor="openclaw",
        details={
            "workspace_id": body.workspace_id,
            "device_id": body.device_id,
            "agent_id": body.agent_id,
            "session_id": body.session_id,
            "project_id": effective_project_id,
            "query": body.query,
            "limit": body.limit,
            "result_count": len(blocks),
            "context_engine": body.context_engine,
        },
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
