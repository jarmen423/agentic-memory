"""Entry point for running am-server with uvicorn."""

from __future__ import annotations

import os

import uvicorn

from am_server.app import create_app


def run() -> None:
    """Start the am-server using uvicorn."""
    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("AM_SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("AM_SERVER_PORT", "8765")),
    )


if __name__ == "__main__":
    run()
