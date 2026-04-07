"""FastAPI app for the local desktop control-plane shell."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from desktop_shell.config import ShellSettings

STATIC_DIR = Path(__file__).with_name("static")


def get_settings() -> ShellSettings:
    """Return process settings for the shell."""
    return ShellSettings()


def get_backend_client(settings: ShellSettings = Depends(get_settings)):
    """Yield a backend client authenticated against the existing product API."""
    headers = {}
    if settings.backend_api_key:
        headers["Authorization"] = f"Bearer {settings.backend_api_key}"
    client = httpx.Client(base_url=settings.backend_url, headers=headers, timeout=10.0)
    try:
        yield client
    finally:
        client.close()


def _proxy_json_response(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> dict:
    """Proxy a JSON request to the backend."""
    response = client.request(method, path, json=json_body)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:  # pragma: no cover - exercised in integration smoke
        raise HTTPException(status_code=response.status_code, detail=response.text) from exc
    return response.json()


def create_app() -> FastAPI:
    """Create the desktop shell app."""
    app = FastAPI(title="Agentic Memory Desktop Shell", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/bootstrap")
    def bootstrap(settings: ShellSettings = Depends(get_settings)) -> dict:
        return {
            "shell": {
                "name": "Agentic Memory Desktop Shell",
                "version": "0.1.0",
                "dev_command": "python -m desktop_shell",
            },
            "backend": {
                "url": settings.backend_url,
                "auth_configured": bool(settings.backend_api_key),
            },
        }

    @app.get("/api/product/status")
    def product_status(client: httpx.Client = Depends(get_backend_client)) -> dict:
        return _proxy_json_response(client, "GET", "/product/status")

    @app.post("/api/product/repos")
    def upsert_repo(
        payload: dict = Body(...),
        client: httpx.Client = Depends(get_backend_client),
    ) -> dict:
        return _proxy_json_response(client, "POST", "/product/repos", json_body=payload)

    @app.post("/api/product/integrations")
    def upsert_integration(
        payload: dict = Body(...),
        client: httpx.Client = Depends(get_backend_client),
    ) -> dict:
        return _proxy_json_response(client, "POST", "/product/integrations", json_body=payload)

    @app.post("/api/product/components/{component}")
    def set_component_status(
        component: str,
        payload: dict = Body(...),
        client: httpx.Client = Depends(get_backend_client),
    ) -> dict:
        return _proxy_json_response(
            client,
            "POST",
            f"/product/components/{component}",
            json_body=payload,
        )

    @app.post("/api/product/onboarding")
    def update_onboarding(
        payload: dict = Body(...),
        client: httpx.Client = Depends(get_backend_client),
    ) -> dict:
        return _proxy_json_response(client, "POST", "/product/onboarding", json_body=payload)

    @app.post("/api/product/events")
    def record_event(
        payload: dict = Body(...),
        client: httpx.Client = Depends(get_backend_client),
    ) -> dict:
        return _proxy_json_response(client, "POST", "/product/events", json_body=payload)

    return app


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for running the shell."""
    parser = argparse.ArgumentParser(
        prog="python -m desktop_shell",
        description="Launch the local Agentic Memory desktop shell.",
    )
    parser.add_argument("--host", default=ShellSettings().host)
    parser.add_argument("--port", type=int, default=ShellSettings().port)
    parser.add_argument("--backend-url", default=ShellSettings().backend_url)
    parser.add_argument("--backend-api-key", default=ShellSettings().backend_api_key)
    return parser


def run(argv: list[str] | None = None) -> None:
    """Run the shell server."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Rebuild settings from CLI args so the shell can be started without env vars.
    import os

    os_env = {
        "DESKTOP_SHELL_HOST": args.host,
        "DESKTOP_SHELL_PORT": str(args.port),
        "DESKTOP_SHELL_BACKEND_URL": args.backend_url,
        "DESKTOP_SHELL_API_KEY": args.backend_api_key,
    }
    for key, value in os_env.items():
        if value:
            os.environ[key] = value

    import uvicorn

    uvicorn.run("desktop_shell.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    run()
