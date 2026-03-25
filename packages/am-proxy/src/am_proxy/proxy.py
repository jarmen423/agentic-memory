"""ACPProxy — bidirectional ACP stdio proxy with passive conversation ingestion.

Transparently passes all bytes between editor stdin/stdout and a spawned
agent subprocess, while tee-ing conversation turns to am-server as
fire-and-forget HTTP posts.

Silent failure contract: ingest errors MUST NEVER affect the agent session.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from uuid import uuid4

from am_proxy.config import ProxyConfig
from am_proxy.ingest import IngestClient


class ACPProxy:
    """Bidirectional ACP stdio proxy with passive conversation ingestion.

    Transparently passes all bytes between editor stdin/stdout and a spawned
    agent subprocess, while tee-ing conversation turns to am-server as
    fire-and-forget HTTP posts.

    Silent failure contract: ingest errors MUST NEVER affect the agent session.
    """

    def __init__(
        self,
        binary: str,
        args: list[str],
        config: ProxyConfig,
        project_id: str | None = None,
    ) -> None:
        """Initialize ACPProxy.

        Args:
            binary: Executable name or path for the agent subprocess.
            args: Additional arguments to pass to the agent subprocess.
            config: ProxyConfig with endpoint, api_key, and TTL settings.
            project_id: Optional project ID override; falls back to config.default_project_id.
        """
        self._binary = binary
        self._args = args
        self._config = config
        self._project_id = project_id or config.default_project_id
        # tool_call buffer: id -> (request_dict, cancel_handle)
        self._buffer: dict[str, tuple[dict[str, Any], asyncio.TimerHandle]] = {}
        # session turn counters: session_id -> next turn_index
        self._session_turn_counts: dict[str, int] = {}
        # Fallback session_id for agents that don't send threads/create
        self._fallback_session_id: str = str(uuid4())
        self._ingest_client = IngestClient(config)

    def _next_turn_index(self, session_id: str) -> int:
        """Return current turn index for session_id, then increment.

        Args:
            session_id: The session identifier.

        Returns:
            The current turn index (0-based). Initializes to 0 on first access.
        """
        idx = self._session_turn_counts.get(session_id, 0)
        self._session_turn_counts[session_id] = idx + 1
        return idx

    def _extract_session_id(self, params: dict[str, Any]) -> str:
        """Extract session_id from params, falling back to the proxy-level UUID.

        Args:
            params: JSON-RPC params dict from ACP message.

        Returns:
            session_id string — never raises.
        """
        return params.get("session_id") or self._fallback_session_id

    def _extract_content(self, params: dict[str, Any], fallback: str = "") -> str:
        """Defensive content extraction with multiple fallback paths.

        Args:
            params: JSON-RPC params dict from ACP message.
            fallback: String to return if no content can be extracted.

        Returns:
            Extracted content string — never raises.
        """
        msg = params.get("message", params)
        if isinstance(msg, dict):
            return str(msg.get("content") or msg.get("text") or str(msg))
        return str(msg) if msg else fallback

    def _buffer_tool_call(self, request_id: str, request: dict[str, Any]) -> None:
        """Buffer a threads/tool_call message and schedule TTL eviction.

        Args:
            request_id: JSON-RPC id to key the buffer entry on.
            request: Full JSON-RPC message dict.
        """
        # Cancel existing TTL if re-buffering same id
        if request_id in self._buffer:
            self._buffer[request_id][1].cancel()
        handle = asyncio.get_event_loop().call_later(
            self._config.buffer_ttl_seconds,
            self._evict_buffer,
            request_id,
        )
        self._buffer[request_id] = (request, handle)

    def _evict_buffer(self, request_id: str) -> None:
        """Remove buffer entry for request_id (called by TTL timer).

        Args:
            request_id: Buffer key to remove.
        """
        self._buffer.pop(request_id, None)

    def _handle_line(self, line: bytes, direction: str, source_agent: str = "") -> None:
        """Route an ACP message line to the appropriate ingest action.

        Pass-through of bytes to the stream has already happened at the call site.
        This method only handles ingest side-effects.

        Args:
            line: Raw bytes of one newline-delimited ACP message.
            direction: "in" (stdin->child) or "out" (child->stdout).
            source_agent: Agent identifier for ConversationIngestRequest.source_agent.
        """
        try:
            msg: dict[str, Any] = json.loads(line.decode("utf-8", errors="replace"))

            # Only route JSON-RPC request objects (must have a method field)
            if not isinstance(msg, dict) or "method" not in msg:
                return

            method: str = msg.get("method", "")
            params: dict[str, Any] = msg.get("params") or {}

            # Skip all $-prefixed methods ($/ping, $/progress, etc.)
            if method.startswith("$"):
                return

            if method == "threads/create":
                session_id = params.get("session_id") or self._fallback_session_id
                self._session_turn_counts[session_id] = 0

            elif method == "threads/message":
                session_id = self._extract_session_id(params)
                turn: dict[str, Any] = {
                    "role": "user",
                    "content": self._extract_content(params),
                    "session_id": session_id,
                    "project_id": self._project_id,
                    "turn_index": self._next_turn_index(session_id),
                    "source_agent": source_agent or None,
                    "ingestion_mode": "passive",
                    "source_key": "chat_proxy",
                }
                self._ingest_client.fire_and_forget(turn)

            elif method == "threads/update":
                # Ingest unless explicitly done=False (streaming chunk)
                done_flag = params.get("done", True)
                if not done_flag:
                    return
                session_id = self._extract_session_id(params)
                turn = {
                    "role": "assistant",
                    "content": self._extract_content(params),
                    "session_id": session_id,
                    "project_id": self._project_id,
                    "turn_index": self._next_turn_index(session_id),
                    "source_agent": source_agent or None,
                    "ingestion_mode": "passive",
                    "source_key": "chat_proxy",
                }
                self._ingest_client.fire_and_forget(turn)

            elif method == "threads/tool_call":
                # Buffer — do not ingest yet; wait for matching tool_result
                request_id = str(msg.get("id") or params.get("id") or uuid4())
                self._buffer_tool_call(request_id, msg)

            elif method == "threads/tool_result":
                request_id = str(msg.get("id") or params.get("id") or "")
                if request_id not in self._buffer:
                    return  # Orphaned result — no matching buffered call
                call_msg, handle = self._buffer.pop(request_id)
                handle.cancel()

                # Extract tool info from buffered call message
                call_params: dict[str, Any] = call_msg.get("params") or {}
                tool_name = str(
                    call_params.get("tool_name") or call_params.get("title") or "tool"
                )
                args = call_params.get("args") or call_params.get("arguments") or {}

                session_id = self._extract_session_id(params)

                # POST tool_call turn first
                call_turn: dict[str, Any] = {
                    "role": "tool",
                    "content": f"{tool_name}({json.dumps(args, default=str)})",
                    "tool_name": tool_name,
                    "tool_call_id": request_id,
                    "session_id": session_id,
                    "project_id": self._project_id,
                    "turn_index": self._next_turn_index(session_id),
                    "source_agent": source_agent or None,
                    "ingestion_mode": "passive",
                    "source_key": "chat_proxy",
                }

                # POST tool_result turn second
                result_content = self._extract_content(params, fallback=str(params))
                result_turn: dict[str, Any] = {
                    "role": "tool",
                    "content": result_content,
                    "tool_name": tool_name,
                    "tool_call_id": request_id,
                    "session_id": session_id,
                    "project_id": self._project_id,
                    "turn_index": self._next_turn_index(session_id),
                    "source_agent": source_agent or None,
                    "ingestion_mode": "passive",
                    "source_key": "chat_proxy",
                }

                self._ingest_client.fire_and_forget(call_turn)
                self._ingest_client.fire_and_forget(result_turn)

            # All other methods: pass-through only, no ingest

        except Exception:
            pass  # Silent failure — routing errors MUST NOT surface to caller

    async def run(self) -> int:
        """Spawn agent subprocess and proxy stdin/stdout bidirectionally.

        Returns:
            Exit code of the agent subprocess.
        """
        from am_proxy.agents import get_agent_config

        agent_cfg = get_agent_config(self._binary)
        source_agent = agent_cfg.source_agent

        proc = await asyncio.create_subprocess_exec(
            self._binary,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def stdin_to_child() -> None:
            loop = asyncio.get_running_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
                if not line:
                    break
                assert proc.stdin is not None
                proc.stdin.write(line)
                await proc.stdin.drain()
                self._handle_line(line, direction="in", source_agent=source_agent)
            if proc.stdin:
                proc.stdin.close()

        async def child_to_stdout() -> None:
            assert proc.stdout is not None
            async for line in proc.stdout:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                self._handle_line(line, direction="out", source_agent=source_agent)

        async def child_stderr_passthrough() -> None:
            assert proc.stderr is not None
            async for chunk in proc.stderr:
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()

        await asyncio.gather(
            stdin_to_child(),
            child_to_stdout(),
            child_stderr_passthrough(),
        )
        return await proc.wait()
