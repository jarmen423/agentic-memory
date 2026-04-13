"""FastAPI route subpackage for ``am_server``.

This package holds one ``APIRouter`` module per logical API domain. Routers are
mounted from ``am_server.app.create_app`` so feature areas stay isolated and can
be versioned or toggled without tangling the main app.

**Role in the stack**

- Keeps HTTP surface area organized by product/feature boundaries.
- Shares cross-cutting pieces (auth ``Depends``, pipeline getters, Pydantic
  models) with the rest of ``am_server`` rather than re-implementing them here.

**Route modules (by concern)**

- ``health`` — Liveness and operator metrics; minimal public surface.
- ``search`` — Vector + graph hybrid memory search.
- ``research`` — Multi-step research pipeline endpoints.
- ``conversation`` — Conversation memory storage and retrieval.
- ``product`` — Product/project memory endpoints.
- ``ext`` — Browser-extension–facing endpoints.
- ``openclaw`` — Claude Code (OpenClaw) plugin memory read/write and project
  lifecycle.
- ``dashboard`` — OpenClaw dashboard read endpoints.
- ``publication`` — Public HTML pages for legal/support and directory reviews
  (no API-key auth on these routes).

**Typical dependencies (imported by individual routers, not this package)**

- ``fastapi`` — ``APIRouter``, ``Depends``, HTTP exceptions and responses.
- ``am_server.dependencies`` — Shared pipeline and store dependency injection.
- ``am_server.auth`` — API-key (and related) authentication dependencies.
- ``am_server.models`` — Shared Pydantic request/response bodies.
"""
