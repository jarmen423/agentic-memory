"""Persistent byte offsets and per-session turn counters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

# Unlikely to appear in session_id; namespaces turns per source_key.
_SEP = "\x1f"


def _turn_key(source_key: str, session_id: str) -> str:
    return f"{source_key}{_SEP}{session_id}"


class WatchState:
    """Tracks per-file read offsets and next turn_index per (source_key, session_id)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file_offsets: dict[str, int] = {}
        self._session_turns: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        fo = raw.get("file_offsets")
        st = raw.get("session_turns")
        if isinstance(fo, dict):
            self._file_offsets = {str(k): int(v) for k, v in fo.items() if isinstance(v, int)}
        if isinstance(st, dict):
            self._session_turns = {str(k): int(v) for k, v in st.items() if isinstance(v, int)}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "file_offsets": dict(sorted(self._file_offsets.items())),
            "session_turns": dict(sorted(self._session_turns.items())),
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get_offset(self, file_path: str) -> int:
        return int(self._file_offsets.get(file_path, 0))

    def has_offset(self, file_path: str) -> bool:
        return file_path in self._file_offsets

    def set_offset(self, file_path: str, offset: int) -> None:
        self._file_offsets[file_path] = offset

    def adopt_offset(self, canonical_key: str, alias_keys: list[str]) -> int:
        """Populate canonical_key from the first known alias when needed."""
        if self.has_offset(canonical_key):
            return self.get_offset(canonical_key)
        for alias in alias_keys:
            if alias == canonical_key or not self.has_offset(alias):
                continue
            offset = self.get_offset(alias)
            self.set_offset(canonical_key, offset)
            return offset
        return 0

    def adopt_matching_offset(self, canonical_key: str, matcher: Callable[[str], bool]) -> int:
        """Populate canonical_key from the first legacy key accepted by matcher."""
        if self.has_offset(canonical_key):
            return self.get_offset(canonical_key)
        for key, offset in self._file_offsets.items():
            if key == canonical_key:
                continue
            if matcher(key):
                self.set_offset(canonical_key, int(offset))
                return int(offset)
        return 0

    def peek_turn_index(self, source_key: str, session_id: str) -> int:
        key = _turn_key(source_key, session_id)
        return int(self._session_turns.get(key, 0))

    def commit_turn_index(self, source_key: str, session_id: str, turn_index: int) -> None:
        key = _turn_key(source_key, session_id)
        committed = int(self._session_turns.get(key, 0))
        self._session_turns[key] = max(committed, turn_index + 1)

    def next_turn_index(self, source_key: str, session_id: str) -> int:
        cur = self.peek_turn_index(source_key, session_id)
        self.commit_turn_index(source_key, session_id, cur)
        return cur
