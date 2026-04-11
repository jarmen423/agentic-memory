"""OpenAI Codex rollout JSONL (RolloutLine / RolloutItem)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Thread UUID in a rollout filename: .../rollout-*-<uuid>.jsonl
_ROLLOUT_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=\.jsonl$)"
)


def session_id_from_rollout_path(path: str) -> str | None:
    """Best-effort session/thread id from rollout filename."""
    m = _ROLLOUT_UUID.search(path)
    return m.group(0).lower() if m else None


def _content_items_to_text(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", "")).lower()
        if kind == "input_text":
            t = item.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t)
        elif kind == "output_text":
            t = item.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t)
    return "\n".join(parts).strip()


def parse_rollout_object(obj: dict[str, Any]) -> tuple[str | None, str | None]:
    """Parse one decoded JSON object from a rollout line."""
    kind = str(obj.get("type", "")).lower()
    if kind == "session_meta":
        payload = obj.get("payload")
        if isinstance(payload, dict):
            sid = payload.get("id")
            if isinstance(sid, str) and sid.strip():
                return "session_id", sid.strip()
        return "skip", None

    if kind != "response_item":
        return "skip", None

    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return "skip", None

    inner_type = str(payload.get("type", "")).lower()
    if inner_type != "message":
        return "skip", None

    role = str(payload.get("role", "")).lower().strip()
    if role not in ("user", "assistant"):
        return "skip", None

    raw_content = payload.get("content")
    if not isinstance(raw_content, list):
        return "skip", None

    text = _content_items_to_text(raw_content)
    if not text:
        return "skip", None

    ts = obj.get("timestamp")
    timestamp = ts if isinstance(ts, str) else None
    envelope = json.dumps(
        {"role": role, "content": text, "timestamp": timestamp},
        ensure_ascii=False,
    )
    return "message", envelope


def parse_rollout_line(line: str) -> tuple[str | None, str | None]:
    """Parse a single JSONL text line."""
    line = line.strip()
    if not line:
        return "skip", None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return "skip", None
    if not isinstance(obj, dict):
        return "skip", None
    return parse_rollout_object(obj)


class CodexRolloutAdapter:
    """Codex ``~/.codex/sessions/**/*.jsonl`` rollout files."""

    adapter_id = "codex_rollout"
    source_key = "chat_codex_rollout"
    source_agent = "codex"

    def watch_roots(self, home: Path) -> list[Path]:
        return [
            home / ".codex" / "sessions",
            home / ".codex" / "archived_sessions",
        ]

    def matches_file(self, path: Path) -> bool:
        return path.suffix.lower() == ".jsonl" and path.name.lower().startswith("rollout-")

    def session_hint_from_path(self, file_path: str) -> str | None:
        return session_id_from_rollout_path(file_path)

    def artifact_state_key(self, file_path: str, session_hint: str | None) -> str:
        if session_hint:
            return f"{self.adapter_id}:{session_hint}"
        return str(Path(file_path).resolve())

    def parse_line(
        self,
        line: str,
        *,
        file_path: str,
        session_hint: str | None,
        current_session_id: str | None,
    ) -> tuple[str | None, str | None]:
        del file_path, session_hint, current_session_id
        return parse_rollout_line(line)
