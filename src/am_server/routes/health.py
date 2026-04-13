"""Health checks, onboarding readiness, Prometheus metrics, and MCP inventory.

This router exposes operational endpoints used by load balancers, monitoring,
and on-call engineers. It is separate from product APIs so probes stay cheap
and permissions can differ per route.

**Security model**

- ``GET /health`` is intentionally unauthenticated for orchestrator liveness.
- ``GET /health/onboarding`` is intentionally unauthenticated so the local shell
  and future plugin doctor flow can inspect supported setup requirements before
  a working API key has been wired into the client.
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

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from am_server.auth import (
    expected_api_keys_for_surface,
    require_auth,
    strict_mcp_auth_enabled,
)
from am_server.dependencies import get_product_store
from am_server.mcp_profiles import MCP_MOUNT_PROFILES
from am_server.metrics import render_prometheus_metrics
from am_server.models import (
    OpenClawOnboardingContractModel,
    OpenClawOnboardingReadinessModel,
    OpenClawOnboardingServiceModel,
)

router = APIRouter()


def _component_record(name: str) -> dict[str, Any]:
    """Return one runtime component record from the local product store.

    Args:
        name: Component key under ``runtime.components``.

    Returns:
        Component payload dict, or an empty dict when the component has never
        been written to the store.
    """

    state = get_product_store().status_payload()
    runtime = state.get("runtime", {})
    components = runtime.get("components", {}) if isinstance(runtime, dict) else {}
    record = components.get(name, {})
    return record if isinstance(record, dict) else {}


def _normalize_service_status(raw_status: str | None) -> str:
    """Collapse product/runtime states into a smaller onboarding vocabulary."""

    normalized = str(raw_status or "unknown").strip().lower()
    if normalized in {"healthy", "available", "connected", "ok"}:
        return "healthy"
    if normalized in {"degraded", "error", "failed", "unavailable"}:
        return "degraded"
    if normalized in {"missing_config", "auth_not_configured"}:
        return "missing_config"
    if normalized in {"unknown", ""}:
        return "unknown"
    return normalized


def _service_from_component(
    *,
    service_id: str,
    label: str,
    component: str,
    required: bool,
    summary: str,
    depends_on: list[str] | None = None,
) -> OpenClawOnboardingServiceModel:
    """Build one onboarding service model from a product-store component row."""

    record = _component_record(component)
    return OpenClawOnboardingServiceModel(
        service_id=service_id,
        label=label,
        required=required,
        status=_normalize_service_status(record.get("status")),
        summary=summary,
        component=component,
        depends_on=depends_on or [],
        details={
            "updated_at": record.get("updated_at"),
            "details": record.get("details", {}) if isinstance(record.get("details"), dict) else {},
        },
    )


def _build_onboarding_contract() -> OpenClawOnboardingContractModel:
    """Assemble the whole-stack onboarding contract exposed to shell/plugin flows.

    The contract intentionally reflects the current supported path for OpenClaw:

    - install the published plugin package,
    - configure it against a reachable backend,
    - require only the services needed for ``capture_only`` to be considered
      honestly ready,
    - treat context assembly, desktop shell, temporal extras, and Grafana as
      optional enhancements rather than silent prerequisites.
    """

    api_key_count = len(expected_api_keys_for_surface("api"))
    public_mcp_key_count = len(expected_api_keys_for_surface("mcp_public"))
    internal_mcp_key_count = len(expected_api_keys_for_surface("mcp_internal"))
    strict_mcp = strict_mcp_auth_enabled()

    required_services = [
        OpenClawOnboardingServiceModel(
            service_id="backend_http",
            label="Agentic Memory backend HTTP API",
            required=True,
            status="healthy",
            summary="The am-server process is responding and can publish onboarding health.",
            details={
                "health_path": "/health",
                "onboarding_path": "/health/onboarding",
            },
        ),
        OpenClawOnboardingServiceModel(
            service_id="api_auth",
            label="Backend API authentication",
            required=True,
            status="healthy" if api_key_count else "missing_config",
            summary=(
                "Authenticated OpenClaw routes require at least one backend API key."
                if api_key_count
                else "No backend API key is configured, so plugin setup cannot be considered ready."
            ),
            details={
                "api_key_count": api_key_count,
                "configured": bool(api_key_count),
                "env_vars": ["AM_SERVER_API_KEYS", "AM_SERVER_API_KEY"],
            },
        ),
        _service_from_component(
            service_id="openclaw_memory",
            label="OpenClaw memory capture pipeline",
            component="openclaw_memory",
            required=True,
            summary=(
                "Turn ingest and memory search depend on this pipeline being healthy; "
                "it is the minimum functional bar for the supported capture-only path."
            ),
            depends_on=["backend_http", "api_auth"],
        ),
    ]

    optional_services = [
        _service_from_component(
            service_id="openclaw_context_engine",
            label="OpenClaw context engine",
            component="openclaw_context_engine",
            required=False,
            summary=(
                "Needed only for the richer augment-context mode; capture-only can still work "
                "without this component."
            ),
            depends_on=["backend_http", "api_auth", "openclaw_memory"],
        ),
        _service_from_component(
            service_id="mcp_surfaces",
            label="Hosted MCP surfaces",
            component="mcp",
            required=False,
            summary=(
                "Hosted MCP mounts are valuable for broader agent integrations, but they are "
                "not required for the supported OpenClaw plugin onboarding path."
            ),
            depends_on=["backend_http"],
        ),
        _service_from_component(
            service_id="desktop_shell",
            label="Local desktop shell",
            component="desktop_shell",
            required=False,
            summary=(
                "The desktop shell is an operator-facing control plane. It should help inspect "
                "onboarding status, but it is not a hard dependency for the plugin itself."
            ),
            depends_on=["backend_http"],
        ),
        OpenClawOnboardingServiceModel(
            service_id="temporal_stack",
            label="Temporal / SpacetimeDB local stack",
            required=False,
            status="unknown",
            summary=(
                "Temporal services are optional for the default OpenClaw onboarding path and "
                "should never be silently assumed from saved aliases or default ports."
            ),
            details={
                "validated_by_backend": False,
                "note": "Phase 16 bootstrap work will make temporal targeting explicit.",
            },
        ),
        OpenClawOnboardingServiceModel(
            service_id="grafana",
            label="Grafana dashboards",
            required=False,
            status="unknown",
            summary=(
                "Grafana is observability infrastructure, not a prerequisite for plugin setup "
                "or basic memory capture."
            ),
            details={
                "validated_by_backend": False,
            },
        ),
        OpenClawOnboardingServiceModel(
            service_id="mcp_dedicated_keys",
            label="Dedicated MCP API keys",
            required=False,
            status=(
                "healthy"
                if not strict_mcp or (public_mcp_key_count and internal_mcp_key_count)
                else "missing_config"
            ),
            summary=(
                "Dedicated public/internal MCP keys matter only when strict MCP auth is enabled."
                if strict_mcp
                else "Strict MCP auth is disabled, so dedicated MCP keys are optional."
            ),
            depends_on=["mcp_surfaces"],
            details={
                "strict_mcp_auth": strict_mcp,
                "public_mcp_key_count": public_mcp_key_count,
                "internal_mcp_key_count": internal_mcp_key_count,
            },
        ),
    ]

    required_healthy = sum(service.status == "healthy" for service in required_services)
    optional_healthy = sum(service.status == "healthy" for service in optional_services)
    blocking_services = [
        service.service_id for service in required_services if service.status != "healthy"
    ]
    degraded_optional_services = [
        service.service_id for service in optional_services if service.status not in {"healthy", "unknown"}
    ]

    setup_ready = all(
        service.status == "healthy"
        for service in required_services
        if service.service_id in {"backend_http", "api_auth"}
    )
    capture_only_ready = not blocking_services
    augment_context_ready = capture_only_ready and any(
        service.service_id == "openclaw_context_engine" and service.status == "healthy"
        for service in optional_services
    )

    readiness = OpenClawOnboardingReadinessModel(
        setup_ready=setup_ready,
        capture_only_ready=capture_only_ready,
        augment_context_ready=augment_context_ready,
        required_healthy=required_healthy,
        required_total=len(required_services),
        optional_healthy=optional_healthy,
        optional_total=len(optional_services),
        blocking_services=blocking_services,
        degraded_optional_services=degraded_optional_services,
    )

    return OpenClawOnboardingContractModel(
        status="ok",
        plugin_package_name="agentic-memory-openclaw",
        plugin_id="agentic-memory",
        install_command="openclaw plugin install agentic-memory-openclaw",
        setup_command="openclaw agentic-memory setup",
        doctor_command="openclaw agentic-memory doctor",
        required_services=required_services,
        optional_services=optional_services,
        readiness=readiness,
        notes=[
            "The backend can be reachable without being honestly ready for plugin setup; API auth and memory capture must both be healthy.",
            "Capture-only is the minimum supported onboarding mode. Augment-context additionally requires the context engine.",
            "Temporal services, Grafana, and the desktop shell are helpful but must not be treated as hidden prerequisites.",
        ],
    )


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


@router.get("/health/onboarding", response_model=OpenClawOnboardingContractModel)
def onboarding_health() -> OpenClawOnboardingContractModel:
    """Return the source-of-truth onboarding contract for the current backend.

    This endpoint is intentionally unauthenticated because the shell and future
    plugin-side doctor flow need to answer a pre-auth question:

    *Is this backend actually ready for the supported OpenClaw path, and if not,
    what is blocked?*

    Returns:
        A structured contract describing install/setup commands, required and
        optional services, and computed readiness rollups.
    """

    return _build_onboarding_contract()


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
