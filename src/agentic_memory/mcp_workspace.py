"""MCP workspace binding: remember which repo the current tool call belongs to.

Agentic Memory runs against **one** Neo4j instance per process and partitions
memory across repositories by the ``repo_id`` property on graph nodes (not by
switching Bolt URIs). The historical "one graph and pipeline per repo root"
caches have therefore collapsed to a single process-wide singleton — there is
no longer any resource that varies per repo path.

What this module still does:

* Resolves the filesystem repo the **current MCP tool call** came from by
  calling ``roots/list`` on the injected :class:`~mcp.server.fastmcp.server.Context`
  (:func:`resolve_repo_root_for_mcp_session`). The result is stored in a
  :class:`~contextvars.ContextVar` (:func:`get_bound_repo_root`) so downstream
  code — telemetry, the active-scopes machinery, future automatic write-scope
  inference — can see which workspace the user is currently in.
* Exposes :func:`bind_workspace_for_tool_call` /
  :func:`reset_repo_binding` helpers that wrap the ContextVar lifecycle around
  a single tool invocation.

What this module deliberately no longer does:

* Select a different ``KnowledgeGraphBuilder`` / pipeline per repo. The old
  ``graph_cache()``, ``conversation_pipeline_cache()``, and
  ``research_pipeline_cache()`` helpers now return a shared single-slot cache
  used by :mod:`agentic_memory.server.app` and :mod:`agentic_memory.server.tools`
  to memoize the *process-wide* instance. They are preserved only as a
  thin compatibility shim; new code should use
  :func:`get_or_create_process_singleton`.
* Read per-repo Neo4j URIs. See
  :func:`agentic_memory.config.resolve_shared_neo4j_config`.

This module intentionally does **not** import :mod:`agentic_memory.server.app`
at load time to avoid circular imports. Callers pass factory functions in at
runtime; the module provides caching and the ContextVar state.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Tracks the filesystem repo the current MCP tool call came from. Set from
# roots/list at the top of each invocation and reset in `finally`. Consumed
# today only by telemetry and future scope-state code; the graph and pipelines
# no longer branch on this value.
_bound_repo_root: ContextVar[Optional[Path]] = ContextVar("mcp_bound_repo_root", default=None)

# Single-slot process-wide caches. See `get_or_create_process_singleton`. The
# legacy path-keyed dicts are retained as views over these singletons so older
# callers (and tests) that reach into the dict keys keep working.
_SINGLETON_KEY = "__process__"
_graph_cache: dict[str, Any] = {}
_pipeline_cache: dict[str, Any] = {}
_research_pipeline_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def get_bound_repo_root() -> Optional[Path]:
    """Return the repo root the current MCP tool call came from, if resolved.

    This is the **informational** binding — which workspace the editor is
    currently in — not the selector for which graph gets used. All tool calls
    in a process share the same :class:`~agentic_memory.ingestion.graph.KnowledgeGraphBuilder`
    and pipelines regardless of this value.
    """
    return _bound_repo_root.get()


def get_or_create_process_singleton(
    factory: Callable[[Path], T],
    cache: dict[str, T],
    process_repo_root: Path,
) -> T:
    """Build or return the single process-wide instance for ``cache``.

    Multi-repo Agentic Memory used to key graph/pipeline caches by the resolved
    repo path so each workspace in a multi-root MCP session could hold its own
    Neo4j driver. With the shared-Neo4j refactor, there is only ever one
    instance per process; this helper formalizes that by keying every call to
    the reserved :data:`_SINGLETON_KEY`.

    Args:
        factory: Constructor that takes the process repo root and returns the
            instance (``KnowledgeGraphBuilder``, ``ConversationIngestionPipeline``,
            etc.). Called at most once across the process lifetime.
        cache: Process-local dict to memoize into. Typically one of
            :func:`graph_cache`, :func:`conversation_pipeline_cache`, or
            :func:`research_pipeline_cache`; any dict works.
        process_repo_root: Canonical repo root (usually
            :func:`agentic_memory.server.app.resolve_process_repo_root`) passed
            to ``factory`` so it can read its per-repo config (embedding keys,
            extraction LLM config, ``repo_id`` for ingestion tagging).

    Returns:
        The cached instance.
    """
    with _cache_lock:
        if _SINGLETON_KEY not in cache:
            cache[_SINGLETON_KEY] = factory(process_repo_root)
        return cache[_SINGLETON_KEY]


def get_or_create_cached(
    repo_root: Path,
    factory: Callable[[Path], T],
    cache: dict[str, T],
) -> T:
    """Compatibility shim: delegates to :func:`get_or_create_process_singleton`.

    Pre-refactor callers keyed the cache by ``repo_root.resolve()``. The
    signature is preserved so existing call sites do not need to change in
    lockstep with the refactor; internally every call collapses to the shared
    singleton so ``repo_root`` only matters for the **first** call (its value
    is passed to ``factory``).

    .. deprecated::
        New code should call :func:`get_or_create_process_singleton` directly
        to make the single-instance contract explicit.
    """
    return get_or_create_process_singleton(factory, cache, repo_root)


def clear_mcp_caches_for_tests() -> None:
    """Drop the process-wide graph / pipeline singletons (tests only)."""
    with _cache_lock:
        _graph_cache.clear()
        _pipeline_cache.clear()
        _research_pipeline_cache.clear()


def file_uri_to_path(uri: str) -> Path:
    """Turn a ``file://`` URI from MCP roots into a local :class:`~pathlib.Path`."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected file URI, got: {uri!r}")
    path = unquote(parsed.path or "")
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path).resolve()


def _pick_repo_root_from_paths(paths: list[Path]) -> Optional[Path]:
    """Prefer a path with Agentic Memory init, then git, else first."""
    if not paths:
        return None
    for marker in (
        lambda p: (p / ".agentic-memory" / "config.json").is_file(),
        lambda p: (p / ".agentic-memory").is_dir(),
        lambda p: (p / ".codememory").is_dir(),
        lambda p: (p / ".git").exists(),
    ):
        for p in paths:
            try:
                if marker(p):
                    return p
            except OSError:
                continue
    return paths[0]


async def resolve_repo_root_for_mcp_session(
    ctx: Any | None,
    *,
    workspace_root: str | None = None,
) -> Optional[Path]:
    """Resolve the filesystem repo root for this MCP tool call.

    Args:
        ctx: FastMCP :class:`~mcp.server.fastmcp.server.Context` when invoked
            from an MCP client that injects it; ``None`` in tests or CLI.
        workspace_root: Optional explicit absolute or user-relative path (when
            callers add it to tool schemas in the future).

    Returns:
        Resolved directory, or ``None`` to use the process default resolution
        (CLI / env / cwd walk).
    """
    if workspace_root is not None:
        raw = workspace_root.strip()
        if not raw:
            return None
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"workspace_root is not a directory: {p}")
        return p

    if ctx is None:
        return None

    try:
        result = await ctx.session.list_roots()
    except Exception as exc:
        logger.warning("MCP roots/list failed (%s); falling back to cwd discovery.", exc)
        return None

    roots = getattr(result, "roots", None) or []
    if not roots:
        logger.debug("MCP roots/list returned no roots; falling back to cwd discovery.")
        return None

    paths: list[Path] = []
    for root in roots:
        uri = str(getattr(root, "uri", "") or "")
        try:
            paths.append(file_uri_to_path(uri))
        except Exception as exc:
            logger.warning("Skipping MCP root %r: %s", uri, exc)

    if not paths:
        return None

    chosen = _pick_repo_root_from_paths(paths)
    logger.debug("MCP workspace binding: %s (from %s roots)", chosen, len(paths))
    return chosen


def apply_repo_binding(repo_root: Optional[Path]) -> Token[Optional[Path]]:
    """Set :func:`get_bound_repo_root` for the current context. Returns a reset token."""
    return _bound_repo_root.set(repo_root)


def reset_repo_binding(token: Token[Optional[Path]]) -> None:
    """Restore the previous binding (call from ``finally``)."""
    _bound_repo_root.reset(token)


async def bind_workspace_for_tool_call(
    ctx: Any | None,
    *,
    workspace_root: str | None = None,
) -> tuple[Optional[Path], Token[Optional[Path]]]:
    """Resolve the repo, apply binding, return ``(path, reset_token)`` for ``finally``."""
    resolved = await resolve_repo_root_for_mcp_session(ctx, workspace_root=workspace_root)
    reset_token = _bound_repo_root.set(resolved)
    return resolved, reset_token


def graph_cache() -> dict[str, Any]:
    """Return the dict backing the process-wide graph singleton.

    Callers should use :func:`get_or_create_process_singleton` with this dict.
    Exposed as a function (not a direct attribute) so tests and future
    refactors can swap the storage without touching every call site.
    """
    return _graph_cache


def conversation_pipeline_cache() -> dict[str, Any]:
    """Return the dict backing the process-wide conversation-pipeline singleton."""
    return _pipeline_cache


def research_pipeline_cache() -> dict[str, Any]:
    """Return the dict backing the process-wide web research pipeline singleton."""
    return _research_pipeline_cache


def effective_repo_root_for_mcp() -> Path:
    """Filesystem repo root used for resolving per-repo config on the hot path.

    In the shared-Neo4j model every tool call in a process reads the same
    :class:`~agentic_memory.config.Config` regardless of which MCP workspace
    triggered it. This helper therefore returns the **process repo root** (env
    / CWD discovery via :func:`agentic_memory.server.app.resolve_process_repo_root`),
    not the per-call MCP binding. The bound root is still available via
    :func:`get_bound_repo_root` for telemetry and scope-state code.

    Returns:
        The process repo root, resolved once per call.
    """
    # Import lazily — :mod:`agentic_memory.server.app` pulls this module for get_graph.
    from agentic_memory.server.app import resolve_process_repo_root

    return resolve_process_repo_root()


# ---------------------------------------------------------------------------
# Active scopes (focus / isolate / write target)
# ---------------------------------------------------------------------------
#
# Agentic Memory stores memory for every repo the user has ingested inside one
# shared Neo4j graph, partitioned by the ``repo_id`` property. "Active scopes"
# is the per-process user-visible state that says, for the current session,
# which of those ``repo_id``s Should:
#
# * receive **writes** (ingestion tags new memory with the write target),
# * be **read** by ``search_*`` tools and automatic injection
#   (the isolate list is a hard filter; empty/None means "read everything"),
# * be given a **soft ranking boost** during retrieval
#   (the focus list is informational for now — the boost itself is deferred to
#   follow-up ranking research; see ``.planning`` notes).
#
# The state is updated by ``/project`` slash commands (see
# :mod:`agentic_memory.server.tools` prompt registrations) and rendered by
# OpenClaw through the ``resource://agentic-memory/active-scopes`` MCP resource.
#
# Storage is intentionally in-memory only. Long-running hosted MCP servers keep
# state for the life of the process; a fresh Cursor session starts with empty
# scopes, which is the common UX. If session persistence is ever required,
# serialize :class:`ActiveScopes` to ``~/.agentic-memory/active-scopes.json``
# and rehydrate at module import.


@dataclasses.dataclass(frozen=True)
class ActiveScopes:
    """Immutable snapshot of the session's repo-scoping choices.

    Attributes:
        focus: ``repo_id`` values the user has marked as relevant right now.
            Today this is **informational** — rendered by the status line and
            reported through the MCP resource — but the values do not yet
            change retrieval. A follow-up task will wire them into a ranking
            boost once the right scoring approach has been researched.
        isolate: If ``None`` (the default), reads and automatic injection see
            every ``repo_id`` in the graph. If a list, it is a **hard filter**:
            only memory whose ``repo_id`` is in this list is returned or
            injected. Use for focused work sessions where cross-repo bleed is
            undesirable.
        write_target: ``repo_id`` new writes should be tagged with, or
            ``None`` to fall back to auto-detection
            (:func:`agentic_memory.server.tools` resolves the workspace via
            the bound MCP root, with ``CODEMEMORY_CLIENT=openclaw`` clients
            refusing the guess). Setting this explicitly is the recommended
            path for OpenClaw, which has no editor-style workspace root.
    """

    focus: tuple[str, ...] = ()
    isolate: Optional[tuple[str, ...]] = None
    write_target: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for the status-line MCP resource and logs.

        The isolate field is emitted as ``null`` rather than an empty list
        when no isolation is active so downstream consumers can distinguish
        "reads span everything" from "reads intentionally hit an empty set".
        """
        return {
            "focus": list(self.focus),
            "isolate": list(self.isolate) if self.isolate is not None else None,
            "write_target": self.write_target,
        }


_EMPTY_SCOPES = ActiveScopes()
_active_scopes: ActiveScopes = _EMPTY_SCOPES
_scopes_lock = threading.Lock()


def _normalize_repo_ids(values: Any) -> tuple[str, ...]:
    """Accept a string, list/tuple, or ``None``; return a deduplicated tuple.

    Slash command prompts receive their arguments as raw strings from the
    user, so be tolerant of ``"a,b"`` as well as ``["a", "b"]``. Empty entries
    and whitespace are dropped; order is preserved for the first occurrence of
    each id so the status line renders in the order the user specified.
    """
    if values is None:
        return ()
    if isinstance(values, str):
        parts = [p.strip() for p in values.replace(",", " ").split()]
    else:
        parts = [str(v).strip() for v in values]
    seen: dict[str, None] = {}
    for p in parts:
        if p and p not in seen:
            seen[p] = None
    return tuple(seen.keys())


def get_active_scopes() -> ActiveScopes:
    """Return the current :class:`ActiveScopes` snapshot (thread-safe)."""
    with _scopes_lock:
        return _active_scopes


def set_focus(repo_ids: Any) -> ActiveScopes:
    """Replace the focus list with ``repo_ids`` and return the new snapshot.

    Passing an empty iterable clears focus (same effect as :func:`clear_focus`).
    """
    return _mutate(focus=_normalize_repo_ids(repo_ids))


def add_focus(repo_id: str) -> ActiveScopes:
    """Append ``repo_id`` to focus if not already present."""
    with _scopes_lock:
        current = _active_scopes
        if repo_id in current.focus:
            return current
        new_focus = current.focus + (repo_id,)
        return _mutate_locked(focus=new_focus)


def remove_focus(repo_id: str) -> ActiveScopes:
    """Drop ``repo_id`` from the focus list (no-op if absent)."""
    with _scopes_lock:
        current = _active_scopes
        if repo_id not in current.focus:
            return current
        new_focus = tuple(r for r in current.focus if r != repo_id)
        return _mutate_locked(focus=new_focus)


def clear_focus() -> ActiveScopes:
    """Remove every repo from the focus list."""
    return _mutate(focus=())


def set_isolate(repo_ids: Any) -> ActiveScopes:
    """Activate isolation (hard read/injection filter) on ``repo_ids``.

    Passing an empty iterable clears isolation (reads span everything again),
    matching the UX of ``/project unisolate``. To deliberately isolate to an
    empty set (i.e. return nothing), callers should use an explicit sentinel
    when that use case lands; today we treat empty as "off" to avoid
    accidentally blinding the agent.
    """
    ids = _normalize_repo_ids(repo_ids)
    return _mutate(isolate=ids if ids else None)


def clear_isolate() -> ActiveScopes:
    """Disable isolation so reads and injection see every ``repo_id`` again."""
    return _mutate(isolate=None)


def set_write_target(repo_id: Optional[str]) -> ActiveScopes:
    """Pin ingestion writes to ``repo_id``; pass ``None`` to restore auto-detect."""
    normalized: Optional[str] = repo_id.strip() if isinstance(repo_id, str) else None
    return _mutate(write_target=normalized or None)


def clear_write_target() -> ActiveScopes:
    """Remove the explicit write target, returning to auto-detection."""
    return _mutate(write_target=None)


def clear_all_scopes() -> ActiveScopes:
    """Reset every scope (``/project clear``). Returns the empty snapshot."""
    with _scopes_lock:
        global _active_scopes
        _active_scopes = _EMPTY_SCOPES
        logger.info("Active scopes cleared.")
        return _active_scopes


def reset_active_scopes_for_tests() -> None:
    """Reset in-memory scope state. Call from test fixtures only."""
    with _scopes_lock:
        global _active_scopes
        _active_scopes = _EMPTY_SCOPES


def _mutate(**changes: Any) -> ActiveScopes:
    """Apply ``changes`` under the state lock and return the new snapshot."""
    with _scopes_lock:
        return _mutate_locked(**changes)


def _mutate_locked(**changes: Any) -> ActiveScopes:
    """Lock-held state replacement; do not call without holding ``_scopes_lock``."""
    global _active_scopes
    _active_scopes = dataclasses.replace(_active_scopes, **changes)
    logger.info("Active scopes updated: %s", _active_scopes.as_dict())
    return _active_scopes


# ---------------------------------------------------------------------------
# Write target resolution
# ---------------------------------------------------------------------------
#
# Editor-style MCP clients (Cursor, VS Code) always have a clear "current
# workspace" that the user is looking at; using it as the default ``repo_id``
# for new memory is safe. OpenClaw is different: the MCP server is launched
# from whatever directory the operator happened to be in (often the home
# directory or a config folder), and that has nothing to do with what project
# the user is actually working on. Guessing a write target from cwd there
# would silently tag memory to the wrong partition.
#
# The contract below makes the difference explicit:
#
# * Editor clients (``CODEMEMORY_CLIENT`` unset or not ``openclaw``): the
#   bound MCP root — if any — becomes the default write target. When no
#   MCP binding exists either (CLI, tests), fall back to the process repo
#   root. The caller gets a working string, no error.
# * OpenClaw (``CODEMEMORY_CLIENT=openclaw``): there is no safe fallback. If
#   neither an explicit argument nor an active write target is set, we raise
#   :class:`WriteTargetUnresolved`. The MCP tool layer converts that into a
#   friendly error that tells the user to run ``/project write <repo_id>``
#   (or ``/project list`` first to see what exists).


class WriteTargetUnresolved(RuntimeError):
    """Raised when no safe default repo_id exists for the current write.

    Tools that need a ``repo_id`` for ingestion catch this and turn it into a
    user-facing error pointing at the ``/project write`` slash command. It is
    deliberately **not** a subclass of :class:`ValueError` so handlers that
    retry on validation errors do not treat it as one; it indicates a missing
    session choice, not a malformed argument.
    """


def _is_openclaw_client() -> bool:
    """Detect the OpenClaw host from the ``CODEMEMORY_CLIENT`` env var.

    The variable is lowercased before comparison so values like ``OpenClaw``
    and ``OPENCLAW`` both match. Any other value — including empty, unset, or
    editor-specific strings like ``cursor`` — is treated as a non-OpenClaw
    client and gets the cwd / bound-root fallback.
    """
    return (os.getenv("CODEMEMORY_CLIENT") or "").strip().lower() == "openclaw"


def resolve_write_target_repo_id(*, explicit: Optional[str] = None) -> str:
    """Return the ``repo_id`` new memory should be tagged with.

    Resolution order:

    1. ``explicit`` argument (tool parameter, e.g. ``add_message(project_id=...)``).
       Trumps everything so agents can always override for a specific write.
    2. :attr:`ActiveScopes.write_target` (``/project write``). The session's
       chosen pin.
    3. For non-OpenClaw clients: the bound MCP root if any, otherwise the
       process repo root. Converted to the graph's ``repo_id`` convention
       (``str(path.resolve())`` — matches
       :class:`agentic_memory.ingestion.graph.KnowledgeGraphBuilder`).
    4. For OpenClaw: raise :exc:`WriteTargetUnresolved`.

    Args:
        explicit: Caller-supplied ``repo_id``. Whitespace is stripped; empty
            strings are treated as "not provided" so tools can forward raw
            user input without pre-trimming.

    Returns:
        The resolved ``repo_id`` string.

    Raises:
        WriteTargetUnresolved: When ``CODEMEMORY_CLIENT=openclaw`` and neither
            ``explicit`` nor an active write target is set. The exception's
            message points users at ``/project write <repo_id>``.
    """
    if isinstance(explicit, str):
        cleaned = explicit.strip()
        if cleaned:
            return cleaned

    active = get_active_scopes().write_target
    if active:
        return active

    if _is_openclaw_client():
        raise WriteTargetUnresolved(
            "No active project is set for this OpenClaw session. Call "
            "/project list to see available projects, then /project write "
            "<repo_id> to pin writes (or pass project_id explicitly)."
        )

    bound = get_bound_repo_root()
    if bound is not None:
        return str(bound.resolve())

    # Import lazily — :mod:`agentic_memory.server.app` imports this module.
    from agentic_memory.server.app import resolve_process_repo_root

    return str(resolve_process_repo_root().resolve())
