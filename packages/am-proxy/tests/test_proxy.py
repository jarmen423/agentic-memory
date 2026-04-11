"""Unit tests for ACPProxy ACP message routing and buffer TTL."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from am_proxy.config import ProxyConfig
from am_proxy.proxy import ACPProxy


def make_proxy(config: ProxyConfig) -> ACPProxy:
    """Create ACPProxy with a mocked IngestClient."""
    proxy = ACPProxy(binary="echo", args=[], config=config, project_id="test-proj")
    proxy._ingest_client = MagicMock()  # type: ignore[assignment]
    proxy._ingest_client.fire_and_forget = MagicMock()
    return proxy


def encode(msg: dict) -> bytes:
    """Encode dict as newline-terminated JSON bytes."""
    return (json.dumps(msg) + "\n").encode()


# --- Routing: threads/message ---


def test_threads_message_calls_fire_and_forget(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "threads/message",
            "params": {"session_id": "s1", "message": {"content": "hello world"}},
        }
    )
    proxy._handle_line(line, direction="in")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    call_turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert call_turn["role"] == "user"
    assert call_turn["content"] == "hello world"
    assert call_turn["source_key"] == "chat_proxy"
    assert call_turn["ingestion_mode"] == "passive"
    assert call_turn["project_id"] == "test-proj"
    assert call_turn["turn_index"] == 0


def test_threads_message_increments_turn_index(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "method": "threads/message",
            "params": {"session_id": "s1", "message": {"content": "msg"}},
        }
    )
    proxy._handle_line(line, direction="in")
    proxy._handle_line(line, direction="in")
    calls = proxy._ingest_client.fire_and_forget.call_args_list
    assert calls[0][0][0]["turn_index"] == 0
    assert calls[1][0][0]["turn_index"] == 1


# --- Routing: $/ping, $/progress skip ---


def test_dollar_ping_not_ingested(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode({"jsonrpc": "2.0", "method": "$/ping", "params": {}})
    proxy._handle_line(line, direction="in")
    proxy._ingest_client.fire_and_forget.assert_not_called()


def test_dollar_progress_not_ingested(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode({"jsonrpc": "2.0", "method": "$/progress", "params": {}})
    proxy._handle_line(line, direction="out")
    proxy._ingest_client.fire_and_forget.assert_not_called()


def test_unknown_method_not_ingested(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode({"jsonrpc": "2.0", "method": "custom/method", "params": {}})
    proxy._handle_line(line, direction="in")
    proxy._ingest_client.fire_and_forget.assert_not_called()


# --- Routing: threads/update filtering ---


def test_threads_update_done_true_ingested(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "method": "threads/update",
            "params": {"session_id": "s1", "message": {"content": "final"}, "done": True},
        }
    )
    proxy._handle_line(line, direction="out")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert turn["role"] == "assistant"
    assert turn["source_key"] == "chat_proxy"


def test_threads_update_done_false_not_ingested(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "method": "threads/update",
            "params": {"session_id": "s1", "message": {"content": "chunk"}, "done": False},
        }
    )
    proxy._handle_line(line, direction="out")
    proxy._ingest_client.fire_and_forget.assert_not_called()


def test_threads_update_no_done_field_ingested(test_config: ProxyConfig) -> None:
    """Missing done field defaults to True (ingest)."""
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "method": "threads/update",
            "params": {"session_id": "s1", "message": {"content": "final"}},
        }
    )
    proxy._handle_line(line, direction="out")
    proxy._ingest_client.fire_and_forget.assert_called_once()


# --- Tool call buffering ---


def test_tool_call_buffered_not_ingested(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "threads/tool_call",
            "params": {"session_id": "s1", "tool_name": "read_file", "args": {"path": "/foo"}},
        }
    )
    proxy._handle_line(line, direction="out")
    proxy._ingest_client.fire_and_forget.assert_not_called()
    assert "call-1" in proxy._buffer


def test_tool_result_triggers_two_posts(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    call_line = encode(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "threads/tool_call",
            "params": {"session_id": "s1", "tool_name": "read_file", "args": {"path": "/foo"}},
        }
    )
    result_line = encode(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "threads/tool_result",
            "params": {"session_id": "s1", "message": {"content": "file contents here"}},
        }
    )
    proxy._handle_line(call_line, direction="out")
    proxy._handle_line(result_line, direction="in")
    assert proxy._ingest_client.fire_and_forget.call_count == 2
    turns = [c[0][0] for c in proxy._ingest_client.fire_and_forget.call_args_list]
    assert turns[0]["role"] == "tool"
    assert turns[1]["role"] == "tool"
    assert turns[0]["tool_name"] == "read_file"
    assert turns[0]["tool_call_id"] == "call-1"
    # Buffer entry cleared after result
    assert "call-1" not in proxy._buffer


def test_orphaned_tool_result_ignored(test_config: ProxyConfig) -> None:
    """tool_result with no matching buffer entry does nothing."""
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "id": "no-such-call",
            "method": "threads/tool_result",
            "params": {"session_id": "s1", "message": {"content": "result"}},
        }
    )
    proxy._handle_line(line, direction="in")
    proxy._ingest_client.fire_and_forget.assert_not_called()


# --- Buffer TTL eviction ---


async def test_buffer_ttl_evicts_entry(test_config: ProxyConfig) -> None:
    """Buffer entry is evicted after TTL expires."""
    config = ProxyConfig(
        endpoint="http://test:9999",
        api_key="key",
        default_project_id="proj",
        timeout_seconds=1.0,
        buffer_ttl_seconds=0.05,  # 50ms for fast test
    )
    proxy = make_proxy(config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "id": "call-ttl",
            "method": "threads/tool_call",
            "params": {"session_id": "s1", "tool_name": "tool", "args": {}},
        }
    )
    proxy._handle_line(line, direction="out")
    assert "call-ttl" in proxy._buffer
    await asyncio.sleep(0.1)  # Wait for TTL to fire
    assert "call-ttl" not in proxy._buffer


async def test_buffer_ttl_cancelled_on_result(test_config: ProxyConfig) -> None:
    """TTL handle is cancelled when tool_result matches before TTL fires."""
    config = ProxyConfig(
        endpoint="http://test:9999",
        api_key="key",
        default_project_id="proj",
        timeout_seconds=1.0,
        buffer_ttl_seconds=0.1,
    )
    proxy = make_proxy(config)
    call_line = encode(
        {
            "jsonrpc": "2.0",
            "id": "call-cancel",
            "method": "threads/tool_call",
            "params": {"session_id": "s1", "tool_name": "t", "args": {}},
        }
    )
    result_line = encode(
        {
            "jsonrpc": "2.0",
            "id": "call-cancel",
            "method": "threads/tool_result",
            "params": {"session_id": "s1", "message": {"content": "ok"}},
        }
    )
    proxy._handle_line(call_line, direction="out")
    proxy._handle_line(result_line, direction="in")
    # Entry removed immediately by tool_result handler, not waiting for TTL
    assert "call-cancel" not in proxy._buffer
    await asyncio.sleep(0.15)  # TTL window passes — no side effects
    assert "call-cancel" not in proxy._buffer


# --- Non-JSON lines ---


def test_non_json_line_no_exception(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    proxy._handle_line(b"not valid json\n", direction="in")
    proxy._ingest_client.fire_and_forget.assert_not_called()


def test_empty_line_no_exception(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    proxy._handle_line(b"\n", direction="in")
    proxy._ingest_client.fire_and_forget.assert_not_called()


def test_jsonrpc_response_no_method_not_ingested(test_config: ProxyConfig) -> None:
    """JSON-RPC response objects (no method field) are passed through silently."""
    proxy = make_proxy(test_config)
    line = encode({"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "s1"}})
    proxy._handle_line(line, direction="out")
    proxy._ingest_client.fire_and_forget.assert_not_called()


# --- threads/create ---


def test_threads_create_initializes_session(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "threads/create",
            "params": {"session_id": "sess-new"},
        }
    )
    proxy._handle_line(line, direction="in")
    proxy._ingest_client.fire_and_forget.assert_not_called()
    assert proxy._session_turn_counts.get("sess-new") == 0


# --- Codex App Server (openai_codex) ---


def test_codex_turn_start_ingests_user(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "method": "turn/start",
            "params": {"threadId": "thr_1", "input": "hello codex"},
        }
    )
    proxy._handle_line(line, direction="in", source_agent="openai_codex")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert turn["role"] == "user"
    assert turn["content"] == "hello codex"
    assert turn["session_id"] == "thr_1"
    assert turn["source_key"] == "chat_proxy"


def test_codex_turn_start_ingests_typed_input_array(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "jsonrpc": "2.0",
            "method": "turn/start",
            "params": {
                "threadId": "thr_array",
                "input": [
                    {"type": "input_text", "text": "hello"},
                    {"type": "input_image", "image_url": "ignored"},
                    {"type": "input_text", "text": "world"},
                ],
            },
        }
    )
    proxy._handle_line(line, direction="in", source_agent="openai_codex")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert turn["role"] == "user"
    assert turn["content"] == "hello\nworld"


def test_codex_turn_start_ingests_nested_turn_input_array(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "method": "turn/start",
            "params": {
                "threadId": "thr_nested",
                "turn": {"input": [{"type": "input_text", "text": "nested"}]},
            },
        }
    )
    proxy._handle_line(line, direction="in", source_agent="openai_codex")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert turn["content"] == "nested"


def test_codex_turn_start_method_prefix_without_source_agent(test_config: ProxyConfig) -> None:
    """thread/turn/item methods route even when source_agent is unknown."""
    proxy = make_proxy(test_config)
    line = encode(
        {
            "method": "turn/start",
            "params": {"threadId": "t2", "input": "hi"},
        }
    )
    proxy._handle_line(line, direction="in", source_agent="")
    proxy._ingest_client.fire_and_forget.assert_called_once()


def test_codex_thread_started_resets_turn_counter(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    proxy._session_turn_counts["thr_x"] = 99
    line = encode(
        {
            "method": "thread/started",
            "params": {"thread": {"id": "thr_x"}},
        }
    )
    proxy._handle_line(line, direction="out", source_agent="openai_codex")
    assert proxy._session_turn_counts.get("thr_x") == 0
    proxy._ingest_client.fire_and_forget.assert_not_called()


def test_codex_item_completed_ingests_assistant(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "method": "item/completed",
            "params": {
                "threadId": "thr_1",
                "item": {"type": "agent_message", "text": "Done."},
            },
        }
    )
    proxy._handle_line(line, direction="out", source_agent="openai_codex")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert turn["role"] == "assistant"
    assert turn["content"] == "Done."


def test_codex_item_completed_ingests_typed_content_array(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "method": "item/completed",
            "params": {
                "threadId": "thr_1",
                "item": {
                    "type": "agent_message",
                    "content": [
                        {"type": "output_text", "text": "Line 1"},
                        {"type": "output_image", "image_url": "ignored"},
                        {"type": "output_text", "text": "Line 2"},
                    ],
                },
            },
        }
    )
    proxy._handle_line(line, direction="out", source_agent="openai_codex")
    proxy._ingest_client.fire_and_forget.assert_called_once()
    turn = proxy._ingest_client.fire_and_forget.call_args[0][0]
    assert turn["role"] == "assistant"
    assert turn["content"] == "Line 1\nLine 2"


def test_codex_item_completed_skips_tool_like_items(test_config: ProxyConfig) -> None:
    proxy = make_proxy(test_config)
    line = encode(
        {
            "method": "item/completed",
            "params": {
                "threadId": "thr_1",
                "item": {"type": "tool_call", "text": "ignored"},
            },
        }
    )
    proxy._handle_line(line, direction="out", source_agent="openai_codex")
    proxy._ingest_client.fire_and_forget.assert_not_called()
