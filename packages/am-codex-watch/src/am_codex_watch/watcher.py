"""Watchdog integration for session artifact directories."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from am_codex_watch.adapters.registry import adapter_for_path, resolve_enabled
from am_codex_watch.config import WatchConfig
from am_codex_watch.state import WatchState
from am_codex_watch.tail import process_artifact_file

logger = logging.getLogger(__name__)


class _ArtifactHandler(FileSystemEventHandler):
    def __init__(
        self,
        *,
        config: WatchConfig,
        state: WatchState,
        debounce_s: float = 0.3,
    ) -> None:
        super().__init__()
        self._config = config
        self._state = state
        self._adapters = resolve_enabled(config.enabled_adapters)
        self._debounce_s = debounce_s
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def _schedule(self, path: Path) -> None:
        path = path.resolve()
        adapter = adapter_for_path(path, self._adapters)
        if adapter is None:
            return
        key = str(path)
        now = time.monotonic()
        with self._lock:
            self._pending[key] = now

    def dispatch_pending(self) -> None:
        """Process files whose debounce window expired (call from main loop)."""
        adapters = resolve_enabled(self._config.enabled_adapters)
        now = time.monotonic()
        due: list[Path] = []
        with self._lock:
            for key, t in list(self._pending.items()):
                if now - t >= self._debounce_s:
                    due.append(Path(key))
                    del self._pending[key]
        for p in due:
            adapter = adapter_for_path(p, adapters)
            if adapter is None:
                continue
            process_artifact_file(p, adapter, config=self._config, state=self._state)

    def on_modified(self, event: object) -> None:
        if getattr(event, "is_directory", False):
            return
        src = getattr(event, "src_path", None)
        if isinstance(src, str):
            self._schedule(Path(src))

    def on_created(self, event: object) -> None:
        self.on_modified(event)


def iter_artifact_files(config: WatchConfig) -> list[Path]:
    """List files under resolved roots that match any enabled adapter."""
    adapters = resolve_enabled(config.enabled_adapters)
    out: list[Path] = []
    for root in config.resolved_roots():
        if not root.is_dir():
            continue
        for p in root.rglob("*.jsonl"):
            if adapter_for_path(p, adapters) is not None:
                out.append(p)
    return sorted(out)


def iter_rollout_files(config: WatchConfig) -> list[Path]:
    """Backward-compatible alias for Codex-era name."""
    return iter_artifact_files(config)


def initial_scan(config: WatchConfig, state: WatchState) -> None:
    """Process all matching artifact files once (startup catch-up)."""
    adapters = resolve_enabled(config.enabled_adapters)
    for path in iter_artifact_files(config):
        adapter = adapter_for_path(path, adapters)
        if adapter is not None:
            process_artifact_file(path, adapter, config=config, state=state)


def run_forever(config: WatchConfig, state: WatchState) -> None:
    """Watch configured roots until interrupted."""
    initial_scan(config, state)

    handler = _ArtifactHandler(config=config, state=state)
    observer = Observer()
    scheduled = 0
    for root in config.resolved_roots():
        if root.is_dir():
            observer.schedule(handler, str(root), recursive=True)
            scheduled += 1
            if config.debug:
                logger.info("watching %s", root)

    if scheduled == 0:
        logger.warning(
            "no session roots to watch; create ~/.codex/sessions, set [am_codex_watch].roots, "
            "or add [am_codex_watch].extra_roots",
        )
        return

    observer.start()
    try:
        while True:
            time.sleep(0.1)
            handler.dispatch_pending()
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join(timeout=5.0)
