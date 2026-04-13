"""FastAPI HTTP server package exposing agentic-memory as a REST API.

Summary:
    ``am_server`` is the network boundary for the agentic-memory stack. It
    accepts HTTP from plugins, gateways, extensions, and tools, then delegates
    to ``agentic_memory`` / ``codememory`` and returns structured JSON (or
    streams where applicable).

Package layout:
    * **Entry point** — :mod:`am_server.server` starts Uvicorn.
    * **App factory** — :func:`am_server.app.create_app` builds FastAPI, mounts
      routers, and registers middleware (including request correlation).
    * **Routes** — :mod:`am_server.routes` (per-domain modules: search, research,
      conversation, product, ext, openclaw, health).
    * **Cross-cutting** — :mod:`am_server.auth`, :mod:`am_server.dependencies`
      (``Depends`` singletons), :mod:`am_server.models` (Pydantic contracts),
      :mod:`am_server.middleware` (request id propagation).

External dependencies:
    * ``fastapi`` / ``uvicorn`` — ASGI stack.
    * ``agentic_memory`` — graph and vector memory pipeline.
    * ``codememory`` — code-oriented memory indexing.
"""
