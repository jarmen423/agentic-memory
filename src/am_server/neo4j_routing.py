"""OpenClaw Neo4j routing: operator private graph vs shared default graph.

Only workspaces listed in ``AM_OPERATOR_WORKSPACE_IDS`` use the Bolt target
from ``NEO4J_OPERATOR_URI`` (plus optional operator-specific credentials).
All other workspaces continue to use the process-default ``NEO4J_URI`` graph.

This is intentionally narrow (single operator, two physical graphs) — not
arbitrary per-tenant databases.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _split_ids(raw: str) -> frozenset[str]:
    parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
    return frozenset(parts)


@lru_cache(maxsize=1)
def operator_workspace_ids() -> frozenset[str]:
    """Workspace ids that should use the operator Neo4j (private database)."""

    return _split_ids(os.environ.get("AM_OPERATOR_WORKSPACE_IDS", ""))


def operator_neo4j_configured() -> bool:
    """Return True when a separate operator Bolt URI is set."""

    return bool(os.environ.get("NEO4J_OPERATOR_URI", "").strip())


def use_operator_neo4j(workspace_id: str) -> bool:
    """Return True if this workspace should use the operator Neo4j target."""

    if not operator_neo4j_configured():
        return False
    return workspace_id.strip() in operator_workspace_ids()


def operator_neo4j_credentials() -> tuple[str, str, str]:
    """Return (uri, user, password) for the operator graph.

    Raises:
        RuntimeError: When ``NEO4J_OPERATOR_URI`` is unset (caller should guard).
    """

    uri = os.environ.get("NEO4J_OPERATOR_URI", "").strip()
    if not uri:
        raise RuntimeError("NEO4J_OPERATOR_URI is not set")
    user = (
        os.environ.get("NEO4J_OPERATOR_USER", "").strip()
        or os.environ.get("NEO4J_USER", "").strip()
        or os.environ.get("NEO4J_USERNAME", "").strip()
        or "neo4j"
    )
    password = os.environ.get("NEO4J_OPERATOR_PASSWORD", "").strip() or os.environ.get(
        "NEO4J_PASSWORD", ""
    )
    return uri, user, password
