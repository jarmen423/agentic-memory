"""ASGI entrypoint: API routes plus optional static SPA for single-port deploy.

On the Hetzner experiment host, bind to loopback and point Cloudflare Tunnel at
``http://127.0.0.1:$PORT``. Postgres stays on ``127.0.0.1:5432`` with no public
exposure.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from healthcare_dashboard.api import router as api_router
from healthcare_dashboard.config import cors_origins, static_dist_dir
from healthcare_dashboard.db import close_pool, init_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_pool()
        logger.info("database_pool_ready")
    except Exception:
        logger.exception("database_pool_init_failed")
        raise
    yield
    close_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Healthcare experiments dashboard",
        lifespan=lifespan,
        default_response_class=JSONResponse,
    )

    origins = cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router)

    dist = static_dist_dir()
    if dist.is_dir() and (dist / "index.html").is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets)),
                name="assets",
            )

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon() -> FileResponse:
            icon = dist / "favicon.ico"
            if icon.is_file():
                return FileResponse(icon)
            raise HTTPException(status_code=404)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            """Serve built Vite assets or ``index.html`` for client-side routes."""
            if full_path.startswith("api"):
                raise HTTPException(status_code=404)
            candidate = dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root_placeholder() -> dict[str, str]:
            return {
                "message": "API only — build the UI into static/ (see web/README.md).",
                "health": "/api/health",
            }

    return app


app = create_app()
