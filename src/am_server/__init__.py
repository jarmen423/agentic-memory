"""FastAPI HTTP server package that exposes the agentic-memory system as a REST API.

am_server is the network boundary for the agentic-memory stack. It receives HTTP
requests from clients (Claude Code plugins, the am-proxy gateway, browser extensions,
and external tools), translates them into calls on the underlying Python packages
(agentic_memory, codememory), and streams or returns structured JSON responses.

Role:
    - Entry point: ``am_server.server`` launches the Uvicorn process.
    - App factory: ``am_server.app.create_app`` builds and configures the FastAPI
      application, registers route routers, and attaches middleware.
    - Route modules live in ``am_server.routes`` (one module per logical domain:
      search, research, conversation, product, ext, openclaw, health).
    - Auth, dependency injection, and shared request/response models are in
      ``am_server.auth``, ``am_server.dependencies``, and ``am_server.models``.

Dependencies:
    - fastapi / uvicorn — ASGI framework and server.
    - agentic_memory — core graph + vector memory pipeline.
    - codememory — code-specific memory indexing.
    - am_server.middleware — request-ID injection and other cross-cutting concerns.
"""
