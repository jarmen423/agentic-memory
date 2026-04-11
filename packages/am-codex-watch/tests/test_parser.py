"""Tests for Codex rollout JSONL parsing."""

from __future__ import annotations

import json

from am_codex_watch.parser import parse_rollout_line, parse_rollout_object, session_id_from_rollout_path


def test_session_id_from_filename() -> None:
    p = "/home/x/.codex/sessions/rollout-2025-05-07T17-24-21-5973b6c0-94b8-487b-a530-2aeb6098ae0e.jsonl"
    assert session_id_from_rollout_path(p) == "5973b6c0-94b8-487b-a530-2aeb6098ae0e"


def test_session_meta_emits_id() -> None:
    obj = {
        "timestamp": "2025-01-01T00:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": "thread-abc",
            "cwd": "/tmp",
            "timestamp": "2025-01-01T00:00:00Z",
            "originator": "cli",
            "cli_version": "1.0",
        },
    }
    kind, val = parse_rollout_object(obj)
    assert kind == "session_id"
    assert val == "thread-abc"


def test_response_item_message_user() -> None:
    obj = {
        "timestamp": "2025-01-01T00:00:01Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Hello"}],
        },
    }
    kind, val = parse_rollout_object(obj)
    assert kind == "message"
    assert val is not None
    data = json.loads(val)
    assert data["role"] == "user"
    assert data["content"] == "Hello"
    assert data["timestamp"] == "2025-01-01T00:00:01Z"


def test_skips_tool_like_response_items() -> None:
    obj = {
        "type": "response_item",
        "payload": {"type": "local_shell_call", "call_id": "x"},
    }
    assert parse_rollout_object(obj) == ("skip", None)


def test_parse_rollout_line_empty() -> None:
    assert parse_rollout_line("") == ("skip", None)
