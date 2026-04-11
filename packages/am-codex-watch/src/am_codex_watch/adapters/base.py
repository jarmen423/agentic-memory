"""Protocol for session artifact adapters (CLI-specific transcript formats)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionArtifactAdapter(Protocol):
    """Maps on-disk artifacts to conversation turns for ``POST /ingest/conversation``.

    Each coding agent CLI with a stable transcript format should implement one adapter.
    """

    adapter_id: str
    source_key: str
    source_agent: str

    def watch_roots(self, home: Path) -> list[Path]:
        """Default directories to watch (recursive) for this tool."""

    def matches_file(self, path: Path) -> bool:
        """Return True if this file should be parsed by this adapter."""

    def session_hint_from_path(self, file_path: str) -> str | None:
        """Optional session/thread id from path alone (before reading lines)."""

    def artifact_state_key(self, file_path: str, session_hint: str | None) -> str:
        """Stable key for persisted offsets across file moves/renames."""

    def parse_line(
        self,
        line: str,
        *,
        file_path: str,
        session_hint: str | None,
        current_session_id: str | None,
    ) -> tuple[str | None, str | None]:
        """Parse one line of text.

        Returns:
            Same convention as legacy Codex parser:
            - ``("session_id", id)`` — update current session for this file
            - ``("message", json_envelope)`` — envelope has role, content, timestamp
            - ``("skip", None)`` — ignore
        """
