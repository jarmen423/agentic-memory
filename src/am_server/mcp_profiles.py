"""MCP mount profiles: URL paths, auth surfaces, transports, and public tool contracts.

``am_server`` exposes several hosted MCP endpoints (streamable HTTP and SSE) aimed at
different packaging targets (OpenAI, Codex, Claude, generic public default, and
internal/full-tool self-hosted mounts). Each profile binds:

* A **mount path** (HTTP prefix) used for routing and metrics.
* An **auth surface** string consumed by :mod:`am_server.auth` (``mcp_public`` vs
  ``mcp_internal``) so keys can be isolated per audience.
* A **transport** (``streamable_http`` or ``sse``).
* The **tool allow-list** exposed on that mount.

:func:`profile_for_path` resolves the longest matching ``mount_path`` prefix so
nested paths map to the correct profile. :data:`PUBLIC_TOOL_ANNOTATIONS` supplies
MCP ``ToolAnnotations`` for marketplace-style disclosure (read-only vs write tools).

See :data:`MCP_MOUNT_PROFILES` for the canonical list of named surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class MCPMountProfile:
    """Immutable description of one hosted MCP HTTP mount.

    Attributes:
        name: Short stable identifier (e.g. ``"openai"``, ``"full"``) for logs and metrics.
        mount_path: URL prefix for this MCP app (e.g. ``"/mcp-openai"``).
        auth_surface: Passed to auth as ``surface``—typically ``mcp_public`` for
            plugin-facing URLs or ``mcp_internal`` for self-hosted full mounts.
        tool_names: Ordered allow-list of tool names registered on this mount.
        transport: MCP wire transport, ``streamable_http`` (default) or ``sse``.
        description: Human-readable summary for operators and docs.
    """

    name: str
    mount_path: str
    auth_surface: str
    tool_names: tuple[str, ...]
    transport: str = "streamable_http"
    description: str = ""


# Subset of tools exposed on public/plugin packaging surfaces (not the full internal set).
PUBLIC_MCP_TOOL_NAMES: tuple[str, ...] = (
    "search_codebase",
    "get_file_dependencies",
    "trace_execution_path",
    "search_all_memory",
    "search_web_memory",
    "memory_ingest_research",
    "search_conversations",
    "get_conversation_context",
    "add_message",
)


def _read_tool_annotations(title: str) -> ToolAnnotations:
    """Return the standard public annotation shape for read-only tools."""

    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def _memory_write_tool_annotations(title: str) -> ToolAnnotations:
    """Return the standard public annotation shape for memory-write tools.

    These tools only change Agentic Memory's private backend state and do not
    alter public internet state, so ``openWorldHint`` remains ``False``. We mark
    write tools as destructive for compatibility with clients and review flows
    that expect all state-changing tools to be classified explicitly.
    """

    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )


PUBLIC_TOOL_ANNOTATIONS: dict[str, ToolAnnotations] = {
    "search_codebase": _read_tool_annotations("Search Codebase"),
    "get_file_dependencies": _read_tool_annotations("Get File Dependencies"),
    "trace_execution_path": _read_tool_annotations("Trace Execution Path"),
    "search_all_memory": _read_tool_annotations("Search All Memory"),
    "search_web_memory": _read_tool_annotations("Search Web Memory"),
    "memory_ingest_research": _memory_write_tool_annotations("Save Research To Memory"),
    "search_conversations": _read_tool_annotations("Search Conversations"),
    "get_conversation_context": _read_tool_annotations("Get Conversation Context"),
    "add_message": _memory_write_tool_annotations("Add Message To Memory"),
}

# Public tool set plus internal-only tools (git history, impact, Brave, research runners, etc.).
FULL_MCP_TOOL_NAMES: tuple[str, ...] = PUBLIC_MCP_TOOL_NAMES + (
    "get_git_file_history",
    "get_commit_context",
    "identify_impact",
    "get_file_info",
    "brave_search",
    "schedule_research",
    "run_research_session",
    "list_research_schedules",
)


def public_tool_annotations(tool_name: str) -> ToolAnnotations:
    """Return MCP tool annotations for a name in :data:`PUBLIC_MCP_TOOL_NAMES`.

    Args:
        tool_name: Key in :data:`PUBLIC_TOOL_ANNOTATIONS`.

    Returns:
        The ``ToolAnnotations`` for that tool (read vs write hints).

    Raises:
        KeyError: If ``tool_name`` is not a public annotated tool.
    """

    return PUBLIC_TOOL_ANNOTATIONS[tool_name]


# Order is not used for matching; :func:`profile_for_path` picks longest prefix wins.
MCP_MOUNT_PROFILES: tuple[MCPMountProfile, ...] = (
    MCPMountProfile(
        name="full_sse",
        mount_path="/mcp-full/sse",
        auth_surface="mcp_internal",
        tool_names=FULL_MCP_TOOL_NAMES,
        transport="sse",
        description="Self-hosted/internal SSE MCP surface with the full tool set.",
    ),
    MCPMountProfile(
        name="full",
        mount_path="/mcp-full",
        auth_surface="mcp_internal",
        tool_names=FULL_MCP_TOOL_NAMES,
        description="Self-hosted/internal streamable HTTP MCP surface with the full tool set.",
    ),
    MCPMountProfile(
        name="openai",
        mount_path="/mcp-openai",
        auth_surface="mcp_public",
        tool_names=PUBLIC_MCP_TOOL_NAMES,
        description="Hosted public MCP surface for ChatGPT App packaging.",
    ),
    MCPMountProfile(
        name="codex",
        mount_path="/mcp-codex",
        auth_surface="mcp_public",
        tool_names=PUBLIC_MCP_TOOL_NAMES,
        description="Hosted public MCP surface for Codex plugin packaging.",
    ),
    MCPMountProfile(
        name="claude",
        mount_path="/mcp-claude",
        auth_surface="mcp_public",
        tool_names=PUBLIC_MCP_TOOL_NAMES,
        description="Hosted public MCP surface for Claude remote connectors.",
    ),
    MCPMountProfile(
        name="public_sse",
        mount_path="/mcp-sse",
        auth_surface="mcp_public",
        tool_names=PUBLIC_MCP_TOOL_NAMES,
        transport="sse",
        description="Hosted public SSE MCP surface kept for compatibility.",
    ),
    MCPMountProfile(
        name="public",
        mount_path="/mcp",
        auth_surface="mcp_public",
        tool_names=PUBLIC_MCP_TOOL_NAMES,
        description="Hosted public default MCP surface.",
    ),
)


def profile_for_path(path: str) -> MCPMountProfile | None:
    """Resolve the MCP profile whose ``mount_path`` matches this URL path.

    Compares normalized paths (trailing slashes stripped). If multiple profiles
    could match, the **longest** ``mount_path`` wins so e.g. ``/mcp-full/sse`` maps
    to the SSE full profile rather than a shorter prefix.

    Args:
        path: Request path (typically from the ASGI scope), may include trailing slash.

    Returns:
        The matching :class:`MCPMountProfile`, or ``None`` if no mount applies.
    """

    normalized = path.rstrip("/") or "/"
    for profile in sorted(MCP_MOUNT_PROFILES, key=lambda item: len(item.mount_path), reverse=True):
        mount_path = profile.mount_path.rstrip("/") or "/"
        if normalized == mount_path or normalized.startswith(f"{mount_path}/"):
            return profile
    return None
