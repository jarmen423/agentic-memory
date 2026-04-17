"""FastAPI application factory for **am-server** (Agentic Memory HTTP control plane).

This module is the composition root for the production-facing API: it builds a single
``FastAPI`` instance, wires cross-cutting concerns (CORS, request IDs, metrics, unified
errors), enforces bearer authentication on **hosted MCP surfaces** before traffic reaches
mounted FastMCP ASGI apps, and registers REST routers for health, research, OpenClaw,
product status, and related surfaces.

**Lifecycle:** ``lifespan`` eagerly warms optional pipeline singletons and publishes
runtime component status into the local product store; failures are logged and skipped so
tests and partial configs do not crash the process.

**Observability:** HTTP duration and status are recorded per route template (when
available). MCP-mounted requests additionally emit surface-scoped metrics and may have
``X-Agentic-Memory-MCP-Surface`` / ``X-Agentic-Memory-MCP-Auth-Surface`` headers attached
on success.

**Configuration:** Browser CORS allowlist defaults to known agent host origins; override
with comma-separated ``AM_SERVER_CORS_ALLOW_ORIGINS``.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from am_server.auth import (
    oauth_www_authenticate_header,
    public_oauth_enabled,
    resolve_bearer_token,
    validate_surface_token,
)
from am_server.dependencies import get_conversation_pipeline, get_pipeline, get_product_store
from am_server.mcp_profiles import MCP_MOUNT_PROFILES, profile_for_path
from am_server.metrics import (
    record_error_response,
    record_http_request,
    record_mcp_surface_request,
)
from am_server.middleware import REQUEST_ID_HEADER, request_id_middleware
from am_server.publication_config import public_base_url
from am_server.routes import (
    conversation,
    dashboard,
    ext,
    health,
    openclaw,
    oauth,
    product,
    publication,
    research,
    search,
)

logger = logging.getLogger(__name__)

# Response headers surfacing which MCP profile handled (or rejected) the request.
MCP_SURFACE_HEADER = "X-Agentic-Memory-MCP-Surface"
MCP_AUTH_SURFACE_HEADER = "X-Agentic-Memory-MCP-Auth-Surface"

# Default origins for browser-based clients (e.g. ChatGPT, Claude) when env override unset.
DEFAULT_CORS_ALLOW_ORIGINS: tuple[str, ...] = (
    "https://chatgpt.com",
    "https://chat.openai.com",
    "https://platform.openai.com",
    "https://claude.ai",
    "https://claude.com",
)


def cors_allow_origins() -> list[str]:
    """Resolve the CORS ``Access-Control-Allow-Origin`` allowlist for this process.

    Reads ``AM_SERVER_CORS_ALLOW_ORIGINS`` as a comma-separated list. Whitespace around
    entries is stripped. When unset or empty, falls back to ``DEFAULT_CORS_ALLOW_ORIGINS``.

    Returns:
        Non-empty list of origin strings permitted by ``CORSMiddleware``.
    """

    raw = os.environ.get("AM_SERVER_CORS_ALLOW_ORIGINS", "")
    configured = [item.strip() for item in raw.split(",") if item.strip()]
    return configured or list(DEFAULT_CORS_ALLOW_ORIGINS)


def _pipeline_runtime_details(pipeline: Any) -> dict[str, object]:
    """Summarize a warmed pipeline instance for product-store / status payloads.

    Introspects ``__dict__`` so tests using mocks do not accidentally materialize
    attributes that were never configured on the real type.

    Args:
        pipeline: A pipeline singleton (e.g. research or conversation pipeline).

    Returns:
        Plain dict suitable for JSON-serializable ``details`` in component status.
    """

    details: dict[str, object] = {
        "pipeline_class": pipeline.__class__.__name__,
    }

    pipeline_vars = getattr(pipeline, "__dict__", {})

    # Use __dict__ lookups first so mocks do not fabricate child objects for
    # attributes that were never actually configured.
    embedder = pipeline_vars.get("_embedder")
    if embedder is not None:
        details["embedder_class"] = embedder.__class__.__name__
        provider = getattr(embedder, "provider", None)
        model = getattr(embedder, "model", None)
        if provider:
            details["embedding_provider"] = str(provider)
        if model:
            details["embedding_model"] = str(model)

    connection_manager = pipeline_vars.get("_conn")
    if connection_manager is not None:
        pool_settings = getattr(connection_manager, "pool_settings", None)
        if isinstance(pool_settings, dict):
            details["neo4j_pool"] = dict(pool_settings)

    temporal_bridge = pipeline_vars.get("_temporal_bridge")
    if temporal_bridge is not None:
        details["temporal_bridge_class"] = temporal_bridge.__class__.__name__
        is_available = getattr(temporal_bridge, "is_available", None)
        if callable(is_available):
            try:
                details["temporal_bridge_available"] = bool(is_available())
            except Exception:  # noqa: BLE001
                details["temporal_bridge_available"] = False

    return details


def _publish_runtime_component_status() -> None:
    """Write server and pipeline health snapshots into the local product store.

    Called after startup warm-up attempts so the desktop / product UI can show whether
    MCP surfaces, Neo4j-backed pipelines, and embeddings are available.

    Side effects:
        Mutates product store component rows for ``server``, ``mcp``,
        ``openclaw_memory``, and ``openclaw_context_engine``.
    """

    store = get_product_store()
    public_surfaces = [profile for profile in MCP_MOUNT_PROFILES if profile.auth_surface == "mcp_public"]
    internal_surfaces = [profile for profile in MCP_MOUNT_PROFILES if profile.auth_surface == "mcp_internal"]

    store.set_component_status(
        "server",
        status="healthy",
        details={
            "app": "am-server",
            "version": "0.1.0",
        },
    )
    store.set_component_status(
        "mcp",
        status="available",
        details={
            "surface_count": len(MCP_MOUNT_PROFILES),
            "public_surface_count": len(public_surfaces),
            "internal_surface_count": len(internal_surfaces),
            "surfaces": [
                {
                    "name": profile.name,
                    "mount_path": profile.mount_path,
                    "auth_surface": profile.auth_surface,
                    "transport": profile.transport,
                    "tool_count": len(profile.tool_names),
                }
                for profile in MCP_MOUNT_PROFILES
            ],
        },
    )

    try:
        conversation_pipeline = get_conversation_pipeline()
    except Exception as exc:  # noqa: BLE001
        store.set_component_status(
            "openclaw_memory",
            status="degraded",
            details={"warmup_error": exc.__class__.__name__},
        )
    else:
        store.set_component_status(
            "openclaw_memory",
            status="healthy",
            details=_pipeline_runtime_details(conversation_pipeline),
        )

    try:
        research_pipeline = get_pipeline()
    except Exception as exc:  # noqa: BLE001
        store.set_component_status(
            "openclaw_context_engine",
            status="degraded",
            details={"warmup_error": exc.__class__.__name__},
        )
    else:
        store.set_component_status(
            "openclaw_context_engine",
            status="healthy",
            details=_pipeline_runtime_details(research_pipeline),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context: warm pipelines and publish component status at startup.

    Each warm-up step is independent and **fault-tolerant**: failures log a warning and
    the app still serves traffic (useful for tests and environments missing Neo4j keys).

    Args:
        app: The FastAPI application instance (unused today; reserved for future hooks).

    Yields:
        Control returns to the ASGI server after startup work completes.

    Note:
        Shutdown is a no-op beyond normal FastAPI teardown.
    """
    try:
        get_pipeline()
        logger.info("am-server: research pipeline warmed up")
    except Exception as exc:  # noqa: BLE001
        logger.warning("am-server: research pipeline warm-up skipped: %s", exc)
    try:
        get_conversation_pipeline()
        logger.info("am-server: conversation pipeline warmed up")
    except Exception as exc:  # noqa: BLE001
        logger.warning("am-server: conversation pipeline warm-up skipped: %s", exc)
    try:
        _publish_runtime_component_status()
        logger.info("am-server: runtime component status published")
    except Exception as exc:  # noqa: BLE001
        logger.warning("am-server: runtime component publish skipped: %s", exc)

    # Mounted FastMCP Starlette apps do not automatically get their own lifespan
    # entered by the parent FastAPI app. Enter each underlying streamable HTTP
    # session manager once so ChatGPT/Claude can initialize and list tools.
    streamable_servers = getattr(app.state, "mcp_streamable_servers", [])
    async with AsyncExitStack() as stack:
        seen_ids: set[int] = set()
        for server in streamable_servers:
            if id(server) in seen_ids:
                continue
            seen_ids.add(id(server))
            session_manager = getattr(server, "_session_manager", None)
            if session_manager is not None:
                await stack.enter_async_context(session_manager.run())
        yield


def _route_path_for_metrics(request: Request) -> str:
    """Prefer OpenAPI route template over raw URL path for stable metric cardinality.

    Args:
        request: The incoming ASGI/FastAPI request.

    Returns:
        Route template (e.g. ``/items/{id}``) when ``request.scope["route"]`` exists,
        otherwise ``request.url.path``.
    """

    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return str(route_path or request.url.path)


def _mcp_profile_for_request(request: Request):
    """Map the request URL to a mounted MCP profile, if the path is under a mount.

    FastMCP apps are mounted as sub-applications; this helper lets outer middleware
    attribute auth failures and successful MCP traffic to the correct surface metadata.

    Args:
        request: The incoming request.

    Returns:
        The matching ``McpMountProfile`` from ``profile_for_path``, or ``None`` when the
        path is not an MCP mount.
    """

    return profile_for_path(request.url.path)


def _default_error_code(status_code: int) -> str:
    """Map common HTTP status codes to stable snake_case machine codes.

    Args:
        status_code: HTTP status integer.

    Returns:
        A short code string, or ``\"request_failed\"`` when unmapped.
    """

    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_server_error",
        503: "service_unavailable",
    }.get(status_code, "request_failed")


def _build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Construct the JSON error envelope and emit a matching metrics counter.

    Args:
        request: Current request (for ``request_id`` and metric path).
        status_code: HTTP status for the response.
        code: Machine-readable error code (snake_case).
        message: Human-readable summary.
        details: Optional structured payload; omitted when empty.
        extra_headers: Optional headers merged after ``REQUEST_ID_HEADER``.

    Returns:
        ``JSONResponse`` with unified ``{\"error\": {...}}`` body.
    """

    request_id = getattr(request.state, "request_id", None) or "unknown-request-id"
    payload = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "status": status_code,
        }
    }
    if details not in (None, [], {}, ""):
        payload["error"]["details"] = details

    record_error_response(code=code, path=_route_path_for_metrics(request), status_code=status_code)
    headers = {REQUEST_ID_HEADER: request_id}
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers=headers,
    )


def _normalize_http_exception(exc: HTTPException) -> tuple[str, str, object | None]:
    """Coerce ``HTTPException.detail`` into ``(code, message, details)`` for the envelope.

    Args:
        exc: Raised ``HTTPException`` from handlers or dependencies.

    Returns:
        Tuple of machine code, user-facing message, and optional details object.
    """

    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or _default_error_code(exc.status_code))
        message = str(detail.get("message") or detail.get("detail") or code.replace("_", " "))
        details = detail.get("details")
        return code, message, details

    if isinstance(detail, str):
        return _default_error_code(exc.status_code), detail, None

    return _default_error_code(exc.status_code), "Request failed.", detail


def create_app() -> FastAPI:
    """Build the fully configured ``FastAPI`` application for am-server.

    Installs CORS, exception handlers (HTTP, validation, catch-all), MCP bearer auth and
    metrics middleware, request-ID middleware, mounts FastMCP SSE/streamable-http apps per
    ``MCP_MOUNT_PROFILES``, and includes all API routers.

    Returns:
        Ready-to-serve ``FastAPI`` instance (e.g. ``uvicorn am_server.app:create_app``).
    """
    app = FastAPI(
        title="am-server",
        version="0.1.0",
        lifespan=lifespan,
    )
    # CORS: explicit allowlist; credentials off so wildcard-style browser flows stay simple.
    # Expose MCP surface headers so browser clients can read them after cross-origin calls.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, MCP_SURFACE_HEADER, MCP_AUTH_SURFACE_HEADER],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Normalize ``HTTPException`` into the shared JSON error envelope."""

        code, message, details = _normalize_http_exception(exc)
        return _build_error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details=details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Map Pydantic/request validation failures to HTTP 422 with ``exc.errors()``."""

        return _build_error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Last-resort handler: log stack trace, return generic 500 envelope (no stack)."""

        logger.exception("am_server_unhandled_exception")
        return _build_error_response(
            request,
            status_code=500,
            code="internal_server_error",
            message="Internal server error.",
            details={"exception_type": exc.__class__.__name__},
        )

    @app.middleware("http")
    async def mcp_auth_middleware(request: Request, call_next):
        """Gate **mounted MCP paths** with bearer token validation per profile auth surface.

        Non-MCP routes and CORS preflight ``OPTIONS`` bypass this middleware entirely.

        Args:
            request: Incoming request.
            call_next: Next ASGI handler in the chain.

        Returns:
            JSON error response on auth failure, or the downstream response when allowed.
        """

        profile = _mcp_profile_for_request(request)
        # Not under an MCP mount — no token requirement here.
        if profile is None:
            return await call_next(request)
        # Browser preflight must not require Authorization.
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        token = resolve_bearer_token(request)
        status_code, code, message = validate_surface_token(token, profile.auth_surface)
        if status_code != 200:
            headers = {
                MCP_SURFACE_HEADER: profile.name,
                MCP_AUTH_SURFACE_HEADER: profile.auth_surface,
            }
            # RFC 6750: 401 responses should advertise Bearer scheme for clients.
            if status_code == 401:
                headers["WWW-Authenticate"] = (
                    oauth_www_authenticate_header()
                    if profile.auth_surface == "mcp_public" and public_oauth_enabled()
                    else "Bearer"
                )
            details = {
                "surface": profile.name,
                "mount_path": profile.mount_path,
                "transport": profile.transport,
            }
            return _build_error_response(
                request,
                status_code=status_code,
                code=code,
                message=message,
                details=details,
                extra_headers=headers,
            )

        request.state.mcp_profile = profile.name
        request.state.mcp_auth_surface = profile.auth_surface
        return await call_next(request)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        """Time each request and record HTTP + optional MCP surface metrics.

        On success, attaches MCP surface headers if the downstream app did not set them.

        Args:
            request: Incoming request.
            call_next: Next handler.

        Returns:
            The downstream response after recording metrics.

        Raises:
            Exception: Re-raised after logging a 500 metric slice for the same request.
        """

        started = time.perf_counter()
        mcp_profile = _mcp_profile_for_request(request)
        try:
            response = await call_next(request)
        except Exception:
            # Count the failed request as 500 before propagating (observability contract).
            duration = time.perf_counter() - started
            record_http_request(
                method=request.method,
                path=_route_path_for_metrics(request),
                status_code=500,
                duration_seconds=duration,
            )
            if mcp_profile is not None:
                record_mcp_surface_request(
                    surface=mcp_profile.name,
                    mount_path=mcp_profile.mount_path,
                    auth_surface=mcp_profile.auth_surface,
                    transport=mcp_profile.transport,
                    status_code=500,
                )
            raise

        duration = time.perf_counter() - started
        record_http_request(
            method=request.method,
            path=_route_path_for_metrics(request),
            status_code=response.status_code,
            duration_seconds=duration,
        )
        if mcp_profile is not None:
            record_mcp_surface_request(
                surface=mcp_profile.name,
                mount_path=mcp_profile.mount_path,
                auth_surface=mcp_profile.auth_surface,
                transport=mcp_profile.transport,
                status_code=response.status_code,
            )
            # Surface identity for clients/debugging when the mount did not add headers.
            if MCP_SURFACE_HEADER not in response.headers:
                response.headers[MCP_SURFACE_HEADER] = mcp_profile.name
            if MCP_AUTH_SURFACE_HEADER not in response.headers:
                response.headers[MCP_AUTH_SURFACE_HEADER] = mcp_profile.auth_surface
        return response

    app.middleware("http")(request_id_middleware)

    # Mount FastMCP ASGI apps — import here to avoid circular imports at module level
    from agentic_memory.server.app import mcp as full_mcp  # noqa: PLC0415
    from agentic_memory.server.public_mcp import public_mcp  # noqa: PLC0415

    # FastMCP server singletons cache one StreamableHTTP session manager instance, but
    # ``create_app()`` can run multiple times in one Python process during tests. Reset the
    # lazily created manager so each FastAPI app gets a fresh lifecycle-owned transport.
    full_mcp._session_manager = None
    public_mcp._session_manager = None

    def _build_streamable_http_mount(server: Any):
        """Create one mounted streamable HTTP app whose external path is the mount root.

        FastMCP's default streamable HTTP app exposes its handler at ``/mcp`` inside the
        returned Starlette app. Because we mount that app at profile paths like
        ``/mcp-openai``, ChatGPT ends up probing ``/mcp-openai`` while the real handler
        lives at ``/mcp-openai/mcp``. Override the inner route path to ``/`` at app-build
        time so the published mount path itself is the canonical MCP endpoint.
        """

        original_path = server.settings.streamable_http_path
        try:
            server.settings.streamable_http_path = "/"
            return server.streamable_http_app()
        finally:
            server.settings.streamable_http_path = original_path

    def _allowed_transport_base_urls(profile) -> tuple[str, ...]:
        """Return externally valid base URLs that should pass MCP host checks."""

        urls: list[str] = []
        if profile.auth_surface == "mcp_public":
            public_url = public_base_url()
            if public_url:
                urls.append(public_url)
        hosted_url = str(os.environ.get("AGENTIC_MEMORY_HOSTED_BASE_URL", "")).strip()
        if hosted_url:
            urls.append(hosted_url.rstrip("/"))
        return tuple(dict.fromkeys(urls))

    def _configure_transport_security(server: Any, *, allowed_base_urls: tuple[str, ...]) -> None:
        """Extend FastMCP DNS-rebinding allowlists with the real deployed hosts."""

        current = getattr(server.settings, "transport_security", None)
        if current is None:
            return

        allowed_hosts = list(current.allowed_hosts)
        allowed_origins = list(current.allowed_origins)
        for base_url in allowed_base_urls:
            parsed = urlparse(base_url)
            if not parsed.scheme or not parsed.netloc:
                continue
            if parsed.netloc not in allowed_hosts:
                allowed_hosts.append(parsed.netloc)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in allowed_origins:
                allowed_origins.append(origin)

        server.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=current.enable_dns_rebinding_protection,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

    def _mount_aliases(mount_path: str) -> tuple[str, ...]:
        """Return every concrete path alias that should serve one MCP mount.

        Some MCP clients probe the configured server URL both with and without a
        trailing slash. FastMCP's streamable HTTP app currently redirects the
        slashless form and then misses the redirected ``/.../`` variant when we
        only mount the raw path once. Mounting both aliases keeps the public MCP
        URL stable for clients like ChatGPT developer mode.
        """

        normalized = mount_path.rstrip("/") or "/"
        if normalized == "/":
            return ("/",)
        return (normalized, f"{normalized}/")

    # Longest mount_path first so nested or overlapping prefixes match the intended profile.
    mcp_streamable_servers: list[Any] = []
    for profile in sorted(MCP_MOUNT_PROFILES, key=lambda item: len(item.mount_path), reverse=True):
        server = full_mcp if profile.auth_surface == "mcp_internal" else public_mcp
        _configure_transport_security(server, allowed_base_urls=_allowed_transport_base_urls(profile))
        asgi_app = (
            server.sse_app()
            if profile.transport == "sse"
            else _build_streamable_http_mount(server)
        )
        if profile.transport != "sse":
            mcp_streamable_servers.append(server)
        for mount_alias in _mount_aliases(profile.mount_path):
            app.mount(mount_alias, asgi_app)
    app.state.mcp_streamable_servers = mcp_streamable_servers

    # Register routers
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(conversation.router)
    app.include_router(search.router)
    app.include_router(ext.router)
    app.include_router(openclaw.router)
    app.include_router(dashboard.router)
    app.include_router(product.router)
    app.include_router(publication.router)
    app.include_router(oauth.router)

    return app
