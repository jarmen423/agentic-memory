"""FastAPI application factory for am-server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from am_server.dependencies import get_pipeline
from am_server.routes import ext, health, research

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifespan: warm up pipeline singleton at startup.

    Fault-tolerant: if get_pipeline() fails (e.g., missing env vars during
    tests), log a warning but do not crash — tests may patch the dependency.
    """
    try:
        get_pipeline()
        logger.info("am-server: pipeline warmed up")
    except Exception as exc:  # noqa: BLE001
        logger.warning("am-server: pipeline warm-up skipped: %s", exc)
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Mounts the FastMCP SSE app at /mcp and registers all routers.
    """
    app = FastAPI(
        title="am-server",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount FastMCP ASGI app — import here to avoid circular imports at module level
    from codememory.server.app import mcp  # noqa: PLC0415

    app.mount("/mcp", mcp.sse_app())

    # Register routers
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(ext.router)

    return app
