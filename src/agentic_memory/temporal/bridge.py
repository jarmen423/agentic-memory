"""Python bridge for the SpacetimeDB temporal retrieval helper."""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

_BRIDGE_SINGLETON: "TemporalBridge | None" = None
_BRIDGE_SINGLETON_LOCK = threading.Lock()


class TemporalBridgeError(RuntimeError):
    """Base error raised for helper process failures."""


class TemporalBridgeUnavailableError(TemporalBridgeError):
    """Raised when the bridge is disabled or not configured."""


@dataclass(frozen=True)
class _BridgeConfig:
    command: tuple[str, ...]
    cwd: str
    env: dict[str, str]
    disabled_reason: str | None = None


class TemporalBridge:
    """JSON-lines RPC client for the long-lived Node temporal helper."""

    def __init__(self, config: _BridgeConfig | None = None) -> None:
        self._config = config or self._build_config()
        self._process: subprocess.Popen[str] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "TemporalBridge":
        """Construct a bridge from the current environment."""
        return cls()

    def is_available(self) -> bool:
        """Return True when the bridge is configured and can be started."""
        return self._config.disabled_reason is None

    @property
    def disabled_reason(self) -> str | None:
        """Human-readable reason the bridge is unavailable, if any."""
        return self._config.disabled_reason

    def retrieve(
        self,
        *,
        project_id: str,
        seed_entities: list[dict[str, Any]],
        as_of_us: int | None = None,
        max_edges: int = 10,
        max_hops: int = 2,
        alpha: float = 0.85,
        half_life_hours: float = 24.0,
        min_relevance: float = 0.05,
    ) -> dict[str, Any]:
        """Run temporal retrieval against the warm helper process."""
        payload: dict[str, Any] = {
            "op": "retrieve",
            "projectId": project_id,
            "seedEntities": seed_entities,
            "maxEdges": max_edges,
            "maxHops": max_hops,
            "alpha": alpha,
            "halfLifeHours": half_life_hours,
            "minRelevance": min_relevance,
        }
        if as_of_us is not None:
            payload["asOfUs"] = as_of_us
        return self._request(payload)

    def ingest_claim(
        self,
        *,
        project_id: str,
        subject_name: str,
        predicate: str,
        object_name: str,
        evidence: dict[str, Any],
        subject_kind: str = "unknown",
        object_kind: str = "unknown",
        valid_from_us: int | None = None,
        valid_to_us: int | None = None,
        confidence: float = 1.0,
        now_us: int | None = None,
    ) -> dict[str, Any]:
        """Write a subject-predicate-object claim to SpacetimeDB."""
        payload: dict[str, Any] = {
            "op": "ingest_claim",
            "projectId": project_id,
            "subjectKind": subject_kind,
            "subjectName": subject_name,
            "predicate": predicate,
            "objectKind": object_kind,
            "objectName": object_name,
            "confidence": confidence,
            "evidence": evidence,
        }
        if valid_from_us is not None:
            payload["validFromUs"] = valid_from_us
        if valid_to_us is not None:
            payload["validToUs"] = valid_to_us
        if now_us is not None:
            payload["nowUs"] = now_us
        return self._request(payload)

    def ingest_relation(
        self,
        *,
        project_id: str,
        subject_kind: str,
        subject_name: str,
        predicate: str,
        object_kind: str,
        object_name: str,
        evidence: dict[str, Any],
        valid_from_us: int | None = None,
        valid_to_us: int | None = None,
        confidence: float = 1.0,
        now_us: int | None = None,
    ) -> dict[str, Any]:
        """Write a subject-object relation using deterministic node ids."""
        payload: dict[str, Any] = {
            "op": "ingest_relation",
            "projectId": project_id,
            "subjectKind": subject_kind,
            "subjectName": subject_name,
            "predicate": predicate,
            "objectKind": object_kind,
            "objectName": object_name,
            "confidence": confidence,
            "evidence": evidence,
        }
        if valid_from_us is not None:
            payload["validFromUs"] = valid_from_us
        if valid_to_us is not None:
            payload["validToUs"] = valid_to_us
        if now_us is not None:
            payload["nowUs"] = now_us
        return self._request(payload)

    def close(self) -> None:
        """Terminate the child helper process if it is running."""
        with self._lock:
            if self._process is None:
                return
            process = self._process
            self._process = None

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_available():
            raise TemporalBridgeUnavailableError(
                self.disabled_reason or "Temporal bridge is not configured."
            )

        with self._lock:
            process = self._ensure_process()
            stdin = process.stdin
            stdout = process.stdout
            if stdin is None or stdout is None:
                self._reset_process()
                raise TemporalBridgeError("Temporal bridge process missing stdio pipes.")

            stdin.write(json.dumps(payload) + "\n")
            stdin.flush()

            # The Node/Spacetime client occasionally emits human-readable
            # connection notices on stdout before the first JSON RPC response.
            # The bridge protocol itself is still JSON-lines, so we ignore any
            # non-JSON preamble lines rather than crashing the whole import on
            # the very first temporal write attempt.
            response: dict[str, Any] | None = None
            while response is None:
                line = stdout.readline()
                if not line:
                    self._reset_process()
                    raise TemporalBridgeError("Temporal bridge exited without a response.")
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    message = line.strip()
                    if message:
                        logger.info("Temporal bridge stdout: %s", message)
                    continue

        if not response.get("ok", False):
            error = response.get("error") or {}
            message = error.get("message", "Temporal bridge request failed.")
            raise TemporalBridgeError(str(message))

        return {key: value for key, value in response.items() if key != "ok"}

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process

        if self._config.disabled_reason is not None:
            raise TemporalBridgeUnavailableError(self._config.disabled_reason)

        # Force UTF-8 on the subprocess pipes. The Node helper emits UTF-8
        # (valid bytes like 0x8f can appear in JSON response payloads or in
        # stack traces). Without an explicit encoding Python falls back to
        # ``locale.getpreferredencoding(False)``, which is cp1252 on Windows
        # and raises UnicodeDecodeError on anything outside the Windows-1252
        # range. ``errors="replace"`` protects us from malformed mid-stream
        # bytes surfacing as hard crashes.
        process = subprocess.Popen(
            self._config.command,
            cwd=self._config.cwd,
            env=self._config.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._process = process
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr,),
            name="temporal-bridge-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        return process

    def _reset_process(self) -> None:
        if self._process is None:
            return
        process = self._process
        self._process = None
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)

    def _drain_stderr(self, stream: TextIO | None) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                message = line.rstrip()
                if message:
                    logger.warning("Temporal bridge stderr: %s", message)
        except Exception:  # noqa: BLE001
            logger.debug("Temporal bridge stderr reader exited unexpectedly.", exc_info=True)

    def _build_config(self) -> _BridgeConfig:
        repo_root = Path(__file__).resolve().parents[3]
        script_path = repo_root / "packages" / "am-temporal-kg" / "scripts" / "query_temporal.ts"
        if not script_path.exists():
            return _BridgeConfig(
                command=(),
                cwd=str(repo_root),
                env=dict(os.environ),
                disabled_reason=f"Temporal helper script not found: {script_path}",
            )

        if not os.getenv("STDB_BINDINGS_MODULE"):
            return _BridgeConfig(
                command=(),
                cwd=str(repo_root),
                env=dict(os.environ),
                disabled_reason="STDB_BINDINGS_MODULE is not set.",
            )

        npx_path = shutil.which("npx")
        if not npx_path:
            return _BridgeConfig(
                command=(),
                cwd=str(repo_root),
                env=dict(os.environ),
                disabled_reason="npx is not available on PATH.",
            )

        env = dict(os.environ)
        return _BridgeConfig(
            command=(npx_path, "tsx", str(script_path)),
            cwd=str(repo_root),
            env=env,
        )


def get_temporal_bridge() -> TemporalBridge:
    """Return a cached TemporalBridge singleton."""
    global _BRIDGE_SINGLETON
    with _BRIDGE_SINGLETON_LOCK:
        if _BRIDGE_SINGLETON is None:
            _BRIDGE_SINGLETON = TemporalBridge.from_env()
        return _BRIDGE_SINGLETON


def _close_cached_bridge() -> None:
    global _BRIDGE_SINGLETON
    with _BRIDGE_SINGLETON_LOCK:
        bridge = _BRIDGE_SINGLETON
        _BRIDGE_SINGLETON = None
    if bridge is not None:
        bridge.close()


atexit.register(_close_cached_bridge)
