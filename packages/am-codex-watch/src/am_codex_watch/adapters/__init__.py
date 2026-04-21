"""Session artifact adapters for passive CLI transcript ingest."""

from am_codex_watch.adapters.base import SessionArtifactAdapter
from am_codex_watch.adapters.codex_rollout import CodexRolloutAdapter, parse_rollout_line
from am_codex_watch.adapters.registry import (
    BUILTIN_ADAPTERS,
    adapter_for_path,
    get_adapter,
    resolve_enabled,
)

__all__ = [
    "SessionArtifactAdapter",
    "CodexRolloutAdapter",
    "parse_rollout_line",
    "BUILTIN_ADAPTERS",
    "get_adapter",
    "resolve_enabled",
    "adapter_for_path",
]
