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

import os
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from am_server.auth import (
    deployment_mode,
    expected_api_keys_for_surface,
    oauth_authorization_endpoint,
    oauth_issuer_url,
    oauth_resource_url,
    oauth_token_endpoint,
    public_oauth_enabled,
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


def _configured_exact_key_count(*, multi_env: str, single_env: str) -> int:
    """Count explicitly configured secrets for one env-var pair.

    This helper avoids the surface fallback behavior in
    ``expected_api_keys_for_surface`` so onboarding can distinguish a dedicated
    reviewer-key setup from the general backend API key.
    """

    raw_multi = os.environ.get(multi_env, "")
    multi_keys = {item.strip() for item in raw_multi.split(",") if item.strip()}
    if multi_keys:
        return len(multi_keys)
    return 1 if str(os.environ.get(single_env, "")).strip() else 0


def _oauth_bootstrap_user_count() -> int:
    """Count operator-configured OAuth bootstrap users from env.

    OAuth users are seeded lazily when the auth routes are used, but the health
    contract should still be able to report whether the server has any obvious
    credential source for a reviewer/demo login.
    """

    raw = os.environ.get("AM_SERVER_OAUTH_BOOTSTRAP_USERS", "").strip()
    if not raw:
        return 0

    count = 0
    for entry in [item.strip() for item in raw.split(",") if item.strip()]:
        parts = [item.strip() for item in entry.split(":")]
        if len(parts) >= 3 and parts[0] and parts[1] and parts[2]:
            count += 1
    return count


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
    dedicated_public_mcp_key_count = _configured_exact_key_count(
        multi_env="AM_SERVER_PUBLIC_MCP_API_KEYS",
        single_env="AM_SERVER_PUBLIC_MCP_API_KEY",
    )
    strict_mcp = strict_mcp_auth_enabled()
    current_deployment_mode = deployment_mode()
    hosted_base_url = str(os.environ.get("AGENTIC_MEMORY_HOSTED_BASE_URL", "")).strip() or None
    auth_strategy = "workspace_api_key" if current_deployment_mode == "managed" else "shared_api_key"
    provider_key_mode = "managed" if current_deployment_mode == "managed" else "operator_managed"
    oauth_enabled = public_oauth_enabled()
    oauth_issuer = oauth_issuer_url()
    oauth_resource = oauth_resource_url()
    oauth_authorize = oauth_authorization_endpoint()
    oauth_token = oauth_token_endpoint()
    state_payload = get_product_store().status_payload()
    oauth_summary = state_payload.get("oauth", {}) if isinstance(state_payload, dict) else {}
    persisted_oauth_user_count = int(oauth_summary.get("oauth_user_count") or 0)
    bootstrap_oauth_user_count = _oauth_bootstrap_user_count()
    oauth_user_source_ready = (persisted_oauth_user_count + bootstrap_oauth_user_count) > 0
    oauth_publication_ready = bool(
        oauth_enabled
        and oauth_issuer
        and oauth_resource
        and oauth_authorize
        and oauth_token
        and oauth_user_source_ready
    )

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
                "auth_strategy": auth_strategy,
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
        OpenClawOnboardingServiceModel(
            service_id="public_mcp_oauth",
            label="Public MCP OAuth publication auth",
            required=False,
            status=(
                "healthy"
                if oauth_publication_ready
                else "missing_config"
                if oauth_enabled
                else "unknown"
            ),
            summary=(
                "OAuth 2.0 authorization code flow is configured for hosted public MCP publication."
                if oauth_publication_ready
                else "OAuth is enabled but not fully configured for public publication yet."
                if oauth_enabled
                else "OAuth is not enabled; the live reviewer dry run still depends on bearer-key auth."
            ),
            depends_on=["mcp_surfaces"],
            details={
                "enabled": oauth_enabled,
                "issuer_url": oauth_issuer,
                "resource_url": oauth_resource,
                "authorization_endpoint": oauth_authorize,
                "token_endpoint": oauth_token,
                "persisted_oauth_user_count": persisted_oauth_user_count,
                "bootstrap_oauth_user_count": bootstrap_oauth_user_count,
                "user_source_ready": oauth_user_source_ready,
                "publication_ready": oauth_publication_ready,
                "dedicated_public_mcp_key_count": dedicated_public_mcp_key_count,
                "current_reviewer_fallback": (
                    "dedicated_public_mcp_key"
                    if dedicated_public_mcp_key_count
                    else "shared_backend_api_key_fallback"
                    if public_mcp_key_count
                    else "none"
                ),
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
        deployment_mode=current_deployment_mode,
        supported_deployment_modes=["managed", "self_hosted"],
        auth_strategy=auth_strategy,
        provider_key_mode=provider_key_mode,
        hosted_base_url=hosted_base_url,
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
            (
                "Public MCP publication can now use OAuth when enabled, but reviewer-key fallback may still exist during rollout."
                if oauth_enabled
                else "Public MCP publication still reports bearer-key reviewer auth as the live dry-run path until OAuth is enabled."
            ),
            (
                "Managed mode means Agentic Memory owns backend API keys, provider keys, and database operations."
                if current_deployment_mode == "managed"
                else "Self-hosted mode means the operator owns backend deployment, provider keys, and database operations."
            ),
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
