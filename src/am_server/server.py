"""Process entrypoint that boots Uvicorn with the FastAPI app factory.

``python -m am_server.server`` (or calling :func:`run`) constructs the ASGI app
via :func:`am_server.app.create_app` and listens for HTTP. This module does not
register routes itself; it only wires host/port from the environment and starts
the server process.
"""

from __future__ import annotations

import os

import uvicorn

from am_server.app import create_app


def run() -> None:
    """Start ``am-server`` with Uvicorn using environment-driven bind settings.

    Note:
        ``AM_SERVER_HOST`` defaults to ``0.0.0.0`` and ``AM_SERVER_PORT`` to
        ``8765`` when unset. The application object is built fresh each call;
        dependency singletons inside the app are created when the first request
        resolves each ``Depends`` (see :mod:`am_server.dependencies`).
    """
    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("AM_SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("AM_SERVER_PORT", "8765")),
    )


if __name__ == "__main__":
    run()
