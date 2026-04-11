"""Codex App Server JSON-RPC → passive ingest helpers (OpenAI Codex CLI).

Protocol reference: https://developers.openai.com/codex/app-server/
"""

from __future__ import annotations

from typing import Any


def should_route_codex(method: str, source_agent: str) -> bool:
    """Return True if this line should use Codex App Server routing."""
    if method.startswith("threads/"):
        return False
    if source_agent == "openai_codex":
        return True
    return method.startswith("thread/") or method.startswith("turn/") or method.startswith("item/")


def extract_thread_id(params: dict[str, Any], fallback: str) -> str:
    """Resolve thread id from Codex ``params``."""
    tid = params.get("threadId") or params.get("thread_id")
    if tid is not None:
        return str(tid)
    thread = params.get("thread")
    if isinstance(thread, dict) and thread.get("id") is not None:
        return str(thread["id"])
    item = params.get("item")
    if isinstance(item, dict):
        it = item.get("threadId") or item.get("thread_id")
        if it is not None:
            return str(it)
    return fallback


def _text_from_typed_item(item: Any) -> str:
    """Best-effort text extraction from a typed content item tree."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, list):
        parts = [_text_from_typed_item(part) for part in item]
        return "\n".join(part for part in parts if part).strip()
    if not isinstance(item, dict):
        return ""

    item_type = str(item.get("type", "")).lower()
    if item_type in {"input_text", "output_text", "text"}:
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

    for key in ("text", "content", "input", "prompt", "message", "body", "parts", "items"):
        if key not in item:
            continue
        text = _text_from_typed_item(item.get(key))
        if text:
            return text
    return ""


def extract_user_turn_text(params: dict[str, Any]) -> str:
    """Best-effort user text from ``turn/start`` or ``turn/steer`` params."""
    for key in ("input", "prompt", "text", "content"):
        val = params.get(key)
        text = _text_from_typed_item(val)
        if text:
            return text
    msg = params.get("message")
    if isinstance(msg, dict):
        for key in ("content", "text", "input"):
            text = _text_from_typed_item(msg.get(key))
            if text:
                return text
    turn = params.get("turn")
    if isinstance(turn, dict):
        return extract_user_turn_text(turn)
    items = params.get("items")
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            role = (it.get("role") or it.get("type") or "").lower()
            if role in ("user", "input", "input_text", "text", ""):
                text = _text_from_typed_item(it)
                if text:
                    return text
    return ""


def extract_item_completed_text(params: dict[str, Any]) -> str:
    """Assistant-visible text from ``item/completed`` (or similar) notifications."""
    item = params.get("item")
    if isinstance(item, dict):
        for key in ("text", "content", "message"):
            text = _text_from_typed_item(item.get(key))
            if text:
                return text
        nested = item.get("message")
        if isinstance(nested, dict):
            for key in ("content", "text"):
                text = _text_from_typed_item(nested.get(key))
                if text:
                    return text
        # Structured agent payloads
        text = _text_from_typed_item(item.get("body"))
        if text:
            return text
    result = params.get("result")
    if isinstance(result, dict):
        return extract_item_completed_text(result)
    text = _text_from_typed_item(result)
    if text:
        return text
    return ""


def tool_like_item(item: dict[str, Any]) -> bool:
    """Heuristic: whether an item represents a tool call (skip for text ingest)."""
    itype = str(item.get("type") or item.get("kind") or "").lower()
    if "tool" in itype or "command" in itype:
        return True
    return item.get("toolCall") is not None or item.get("tool_call_id") is not None
