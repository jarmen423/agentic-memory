"""Shared helpers for repo/project identity discovery and repo-id resolution.

This module exists because Agentic Memory currently has two overlapping
identity concepts that show up in different retrieval surfaces:

- ``project_id`` for conversation / research scoping
- ``repo_id`` for code-graph scoping

Historically the code graph stored ``repo_id`` values as filesystem-shaped
paths (for example ``D:\\code\\agentic-memory`` or ``/home/josh/m26pipeline``).
For agent-facing workflows we want a friendlier outward contract that can
prefer canonical git-style identifiers such as ``jarmen423/agentic-memory``
when the graph contains enough Git metadata to derive them.

This helper layer intentionally does **not** rewrite stored graph data. It
provides:

- discovery helpers for currently known ``project_id`` and ``repo_id`` values
- outward-facing repo ids that prefer canonical git identifiers when available
- explicit repo-id resolution for user/tool supplied repo filters
- legacy alias handling for path-style ids still stored in the graph

That lets the public/MCP/OpenClaw surfaces become easier to reason about now,
while deferring any graph-wide data migration to a later dedicated wave.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import logging
import os
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)

_SSH_REMOTE_RE = re.compile(r"^[^@]+@[^:]+:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")


@dataclass(slots=True)
class RepoIdentityRecord:
    """One repo identity known to the graph plus outward-facing aliases.

    Attributes:
        stored_repo_id: The ``repo_id`` string currently stored on graph nodes.
        outward_repo_id: The user-facing id we should return in responses.
            Canonical git-style ids win when they can be derived; otherwise this
            falls back to ``stored_repo_id``.
        root_path: Optional repo root path recorded on ``GitRepo`` nodes.
        remote_url: Optional git remote URL used for canonicalization.
        aliases: Exact strings accepted as explicit repo-id inputs for this
            record during the compatibility-layer rollout.
    """

    stored_repo_id: str
    outward_repo_id: str
    root_path: str | None = None
    remote_url: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(slots=True)
class RepoResolution:
    """Result of resolving one explicit repo-id input for a search request."""

    requested_repo_id: str | None
    resolved_repo_id: str | None
    stored_repo_id: str | None
    repo_resolution_status: str
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe mapping for tool payloads and HTTP responses."""

        return {
            "requested_repo_id": self.requested_repo_id,
            "resolved_repo_id": self.resolved_repo_id,
            "stored_repo_id": self.stored_repo_id,
            "repo_resolution_status": self.repo_resolution_status,
            "suggestions": list(self.suggestions),
        }


def canonical_repo_id_from_remote_url(remote_url: str | None) -> str | None:
    """Return ``owner/repo`` when a git remote URL can be normalized safely."""

    if not remote_url:
        return None

    raw = remote_url.strip()
    if not raw:
        return None

    ssh_match = _SSH_REMOTE_RE.match(raw)
    if ssh_match:
        return f"{ssh_match.group('owner')}/{ssh_match.group('repo')}"

    normalized = raw[:-4] if raw.endswith(".git") else raw
    normalized = normalized.rstrip("/")
    parts = normalized.split("/")
    if len(parts) < 2:
        return None
    owner = parts[-2].strip()
    repo = parts[-1].strip()
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def _home_alias_for_path(path_text: str | None) -> str | None:
    """Return a ``~/...`` alias when ``path_text`` lives under the current home."""

    if not path_text:
        return None
    try:
        candidate = Path(path_text)
        home = Path.home()
        relative = candidate.relative_to(home)
    except Exception:
        return None
    return f"~/{relative.as_posix()}"


def _query_repo_rows(graph: Any) -> list[dict[str, Any]]:
    """Collect repo identity rows from ``GitRepo`` plus any extra bare repo ids."""

    rows: list[dict[str, Any]] = []
    seen_repo_ids: set[str] = set()
    try:
        with graph.driver.session() as session:
            git_rows = session.run(
                """
                MATCH (r:GitRepo)
                RETURN
                    r.repo_id AS repo_id,
                    r.root_path AS root_path,
                    r.remote_url AS remote_url
                ORDER BY repo_id
                """
            )
            for row in git_rows:
                repo_id = row.get("repo_id")
                if not repo_id:
                    continue
                rows.append(
                    {
                        "repo_id": repo_id,
                        "root_path": row.get("root_path"),
                        "remote_url": row.get("remote_url"),
                    }
                )
                seen_repo_ids.add(repo_id)

            fallback_rows = session.run(
                "MATCH (n) WHERE n.repo_id IS NOT NULL RETURN DISTINCT n.repo_id AS repo_id ORDER BY repo_id"
            )
            for row in fallback_rows:
                repo_id = row.get("repo_id")
                if not repo_id or repo_id in seen_repo_ids:
                    continue
                rows.append(
                    {
                        "repo_id": repo_id,
                        "root_path": None,
                        "remote_url": None,
                    }
                )
    except Exception as exc:
        logger.warning("Repo identity query failed: %s", exc)
        return []
    return rows


def list_repo_identity_records(graph: Any) -> list[RepoIdentityRecord]:
    """Return every known repo identity with outward ids and exact aliases."""

    records: list[RepoIdentityRecord] = []
    for row in _query_repo_rows(graph):
        stored_repo_id = str(row["repo_id"])
        root_path = str(row["root_path"]) if row.get("root_path") else None
        remote_url = str(row["remote_url"]) if row.get("remote_url") else None
        outward_repo_id = canonical_repo_id_from_remote_url(remote_url) or stored_repo_id

        aliases: list[str] = [stored_repo_id]
        if root_path and root_path not in aliases:
            aliases.append(root_path)
        if outward_repo_id not in aliases:
            aliases.append(outward_repo_id)
        home_alias = _home_alias_for_path(root_path)
        if home_alias and home_alias not in aliases:
            aliases.append(home_alias)

        records.append(
            RepoIdentityRecord(
                stored_repo_id=stored_repo_id,
                outward_repo_id=outward_repo_id,
                root_path=root_path,
                remote_url=remote_url,
                aliases=tuple(aliases),
            )
        )
    return records


def list_known_repo_ids(graph: Any) -> list[str]:
    """Return outward-facing repo ids known to the graph."""

    return sorted({record.outward_repo_id for record in list_repo_identity_records(graph)})


def list_known_project_ids(graph: Any) -> list[str]:
    """Return every distinct ``project_id`` property currently stored in the graph."""

    try:
        with graph.driver.session() as session:
            rows = session.run(
                """
                MATCH (n)
                WHERE n.project_id IS NOT NULL
                RETURN DISTINCT n.project_id AS project_id
                ORDER BY project_id
                """
            )
            return [str(row["project_id"]) for row in rows if row.get("project_id")]
    except Exception as exc:
        logger.warning("Project identity query failed: %s", exc)
        return []


def list_project_and_repo_ids_payload(graph: Any) -> dict[str, Any]:
    """Return the simple discovery payload requested by the product plan."""

    return {
        "status": "ok",
        "project_ids": list_known_project_ids(graph),
        "repo_ids": list_known_repo_ids(graph),
    }


def resolve_repo_id(graph: Any, requested_repo_id: str | None) -> RepoResolution:
    """Resolve one explicit repo-id input against known repos and aliases.

    This is intentionally strict: callers should only use it when the user/tool
    explicitly supplied a repo filter. Unscoped searches should remain
    permissive and bypass this helper.
    """

    known_records = list_repo_identity_records(graph)
    outward_ids = sorted({record.outward_repo_id for record in known_records})

    if requested_repo_id is None:
        return RepoResolution(
            requested_repo_id=None,
            resolved_repo_id=None,
            stored_repo_id=None,
            repo_resolution_status="unscoped",
            suggestions=outward_ids,
        )

    requested = requested_repo_id.strip()
    if not requested:
        return RepoResolution(
            requested_repo_id=requested_repo_id,
            resolved_repo_id=None,
            stored_repo_id=None,
            repo_resolution_status="unscoped",
            suggestions=outward_ids,
        )

    exact_outward = [record for record in known_records if record.outward_repo_id == requested]
    if len(exact_outward) == 1:
        record = exact_outward[0]
        return RepoResolution(
            requested_repo_id=requested,
            resolved_repo_id=record.outward_repo_id,
            stored_repo_id=record.stored_repo_id,
            repo_resolution_status="exact_match",
            suggestions=outward_ids,
        )

    exact_alias = [record for record in known_records if requested in record.aliases]
    if len(exact_alias) == 1:
        record = exact_alias[0]
        status = "exact_match" if requested == record.outward_repo_id else "alias_resolved"
        return RepoResolution(
            requested_repo_id=requested,
            resolved_repo_id=record.outward_repo_id,
            stored_repo_id=record.stored_repo_id,
            repo_resolution_status=status,
            suggestions=outward_ids,
        )

    suggestions = get_close_matches(requested, outward_ids, n=5, cutoff=0.2)
    return RepoResolution(
        requested_repo_id=requested,
        resolved_repo_id=None,
        stored_repo_id=None,
        repo_resolution_status="unknown_repo_id",
        suggestions=suggestions,
    )


def outward_repo_id_for_stored_repo_id(graph: Any, stored_repo_id: str | None) -> str | None:
    """Return the outward-facing repo id for one stored graph repo id."""

    if stored_repo_id is None:
        return None
    for record in list_repo_identity_records(graph):
        if record.stored_repo_id == stored_repo_id:
            return record.outward_repo_id
    return stored_repo_id


def format_unknown_repo_id_message(resolution: RepoResolution) -> str:
    """Return a stable human-readable error for unknown explicit repo ids."""

    suggestions = resolution.suggestions
    suggestion_text = ", ".join(f"`{repo_id}`" for repo_id in suggestions) if suggestions else "`none`"
    return (
        f"❌ Unknown repo_id `{resolution.requested_repo_id}`. "
        f"Known repo_ids: {suggestion_text}"
    )
