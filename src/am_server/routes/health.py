"""Health checks, Prometheus metrics, and MCP surface inventory for ``am_server``.

This router exposes operational endpoints used by load balancers, monitoring,
and on-call engineers. It is separate from product APIs so probes stay cheap
and permissions can differ per route.

**Security model**

- ``GET /health`` is intentionally unauthenticated for orchestrator liveness.
- ``GET /metrics`` and ``GET /health/mcp-surfaces`` require authentication so
  route-level traffic and MCP configuration are not public.

**Dependencies**

- ``am_server.auth.require_auth`` — Protects sensitive endpoints.
- ``am_server.auth.strict_mcp_auth_enabled`` — Reflected in MCP health payload.
- ``am_server.mcp_profiles.MCP_MOUNT_PROFILES`` — Expected vs actual tool sets
  per mounted MCP profile.
- ``am_server.metrics.render_prometheus_metrics`` — Text exposition format.
- Lazy imports inside ``mcp_surfaces_health`` for app CORS config and both MCP
  app instances (public vs internal tool lists).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from am_server.auth import require_auth, strict_mcp_auth_enabled
from am_server.mcp_profiles import MCP_MOUNT_PROFILES
from am_server.metrics import render_prometheus_metrics

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness probe for orchestrators and load balancers.

    Returns:
        A minimal JSON body ``{"status": "ok"}`` when the process is serving
        requests. No authentication is required.

    Note:
        This endpoint does not validate downstream dependencies (Neo4j, etc.);
        it only confirms the HTTP stack is up.
    """
    return {"status": "ok"}


@router.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_auth)])
def metrics() -> PlainTextResponse:
    """Expose Prometheus-format counters and histograms for the server.

    Authentication is required because metric labels expose route structure and
    live error/traffic signals that should remain operator-only.

    Returns:
        ``text/plain`` body produced by ``render_prometheus_metrics()``.

    Dependencies:
        ``Depends(require_auth)`` on the route (see module docstring).
    """
    return PlainTextResponse(render_prometheus_metrics())


@router.get("/health/mcp-surfaces", dependencies=[Depends(require_auth)])
async def mcp_surfaces_health() -> dict:
    """Compare configured MCP mount profiles against live tool lists.

    For each entry in ``MCP_MOUNT_PROFILES``, lists expected tool names, actual
    tools returned by the corresponding MCP app, whether names match, and (for
    the public surface) whether every tool has non-empty annotations.

    Returns:
        JSON including:

        - ``status``: ``"ok"`` when the handler completes.
        - ``strict_mcp_auth``: Current strict MCP auth flag from settings.
        - ``cors_allow_origins``: Allowed origins from the main app factory.
        - ``surface_count`` / ``surfaces``: Per-profile diagnostics described above.

    Dependencies:
        ``Depends(require_auth)``. Dynamically imports ``cors_allow_origins``,
        ``full_mcp``, and ``public_mcp`` to avoid circular import issues at
        module load time and to query live tool registries.
    """
    from am_server.app import cors_allow_origins
    from agentic_memory.server.app import mcp as full_mcp
    from agentic_memory.server.public_mcp import public_mcp

    public_tools = await public_mcp.list_tools()
    full_tools = await full_mcp.list_tools()
    tool_sets = {
        "mcp_public": public_tools,
        "mcp_internal": full_tools,
    }

    surfaces = []
    for profile in MCP_MOUNT_PROFILES:
        tools = tool_sets[profile.auth_surface]
        actual_tool_names = [tool.name for tool in tools]
        annotations = {
            tool.name: (tool.annotations.model_dump(exclude_none=True) if tool.annotations else None)
            for tool in tools
        }
        surfaces.append(
            {
                "name": profile.name,
                "mount_path": profile.mount_path,
                "auth_surface": profile.auth_surface,
                "transport": profile.transport,
                "expected_tool_names": list(profile.tool_names),
                "actual_tool_names": actual_tool_names,
                "tool_names_match": tuple(actual_tool_names) == profile.tool_names,
                # Public MCP: directory reviews expect annotation metadata on every tool.
                "annotation_coverage_complete": (
                    all(annotations[name] is not None for name in actual_tool_names)
                    if profile.auth_surface == "mcp_public"
                    else None
                ),
                "annotations": annotations if profile.auth_surface == "mcp_public" else None,
            }
        )

    return {
        "status": "ok",
        "strict_mcp_auth": strict_mcp_auth_enabled(),
        "cors_allow_origins": cors_allow_origins(),
        "surface_count": len(surfaces),
        "surfaces": surfaces,
    }
