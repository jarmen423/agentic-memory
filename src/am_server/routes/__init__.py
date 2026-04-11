"""Route subpackage — one APIRouter module per logical domain of the am_server API.

Each module in this subpackage defines a FastAPI ``APIRouter`` that is registered
onto the main application in ``am_server.app.create_app``. Grouping routes by
domain keeps individual files focused and makes it easy to add, version, or toggle
feature areas independently.

Route modules:
    - ``health``    — unauthenticated liveness probe (GET /health).
    - ``search``    — vector + graph hybrid memory search.
    - ``research``  — multi-step research pipeline endpoints.
    - ``conversation`` — conversation memory storage and retrieval.
    - ``product``   — product/project memory endpoints.
    - ``ext``       — browser-extension–facing endpoints.
    - ``openclaw``  — Claude Code plugin (openclaw) memory read/write endpoints.
    - ``dashboard`` — OpenClaw dashboard read endpoints.

Dependencies:
    - fastapi — ``APIRouter``, ``Depends``, HTTP exception helpers.
    - am_server.dependencies — shared pipeline dependency-injection helpers.
    - am_server.auth — API-key authentication dependency.
    - am_server.models — shared Pydantic request/response models.
"""
