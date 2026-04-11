"""FastAPI application factory for am-server."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from am_server.dependencies import get_conversation_pipeline, get_pipeline
from am_server.metrics import record_error_response, record_http_request
from am_server.middleware import REQUEST_ID_HEADER, request_id_middleware
from am_server.routes import conversation, dashboard, ext, health, openclaw, product, research, search

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifespan: warm up pipeline singletons at startup.

    Fault-tolerant: if warm-up fails (e.g., missing env vars during tests),
    log a warning but do not crash — tests may patch the dependency.
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
    yield


def _route_path_for_metrics(request: Request) -> str:
    """Return the route template when available, else the concrete request path."""

    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return str(route_path or request.url.path)


def _default_error_code(status_code: int) -> str:
    """Map HTTP status codes to stable fallback machine codes."""

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
) -> JSONResponse:
    """Build the shared API error envelope and record it in metrics."""

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
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={REQUEST_ID_HEADER: request_id},
    )


def _normalize_http_exception(exc: HTTPException) -> tuple[str, str, object | None]:
    """Normalize FastAPI HTTPException details into the shared error contract."""

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
    """Create and configure the FastAPI application.

    Mounts the FastMCP SSE app at /mcp and registers all routers.
    """
    app = FastAPI(
        title="am-server",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Return HTTP errors in the shared machine-readable envelope."""

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
        """Return FastAPI request validation errors in the shared envelope."""

        return _build_error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Return unexpected server failures in the shared envelope."""

        logger.exception("am_server_unhandled_exception")
        return _build_error_response(
            request,
            status_code=500,
            code="internal_server_error",
            message="Internal server error.",
            details={"exception_type": exc.__class__.__name__},
        )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        """Record coarse request metrics for `/metrics`.

        The foundation wave only needs enough observability to answer:

        - which routes are receiving traffic
        - which routes are erroring
        - how long requests are taking
        """

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - started
            record_http_request(
                method=request.method,
                path=_route_path_for_metrics(request),
                status_code=500,
                duration_seconds=duration,
            )
            raise

        duration = time.perf_counter() - started
        record_http_request(
            method=request.method,
            path=_route_path_for_metrics(request),
            status_code=response.status_code,
            duration_seconds=duration,
        )
        return response

    app.middleware("http")(request_id_middleware)

    # Mount FastMCP ASGI app — import here to avoid circular imports at module level
    from agentic_memory.server.app import mcp  # noqa: PLC0415

    app.mount("/mcp", mcp.sse_app())

    # Register routers
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(conversation.router)
    app.include_router(search.router)
    app.include_router(ext.router)
    app.include_router(openclaw.router)
    app.include_router(dashboard.router)
    app.include_router(product.router)

    return app
