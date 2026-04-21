"""Configuration for am-codex-watch."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from am_codex_watch.adapters.registry import resolve_enabled

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "am-codex-watch" / "config.toml"
DEFAULT_STATE_PATH = Path.home() / ".config" / "am-codex-watch" / "state.json"

DEFAULT_ENABLED_ADAPTERS: tuple[str, ...] = ("codex_rollout",)


def merged_watch_roots(
    *,
    home: Path,
    enabled_adapter_ids: list[str],
    roots_override: list[Path] | None,
    extra_roots: list[Path],
) -> list[Path]:
    """Union of adapter default roots plus extra_roots, or explicit override."""
    if roots_override:
        return list(roots_override)
    seen: set[str] = set()
    out: list[Path] = []
    for ad in resolve_enabled(enabled_adapter_ids):
        for r in ad.watch_roots(home):
            key = str(r.resolve())
            if key not in seen:
                seen.add(key)
                out.append(r)
    for r in extra_roots:
        key = str(r.expanduser().resolve())
        if key not in seen:
            seen.add(key)
            out.append(r.expanduser())
    return out


@dataclasses.dataclass
class WatchConfig:
    """Runtime settings for the session artifact watcher."""

    endpoint: str = "http://127.0.0.1:8765"
    api_key: str = ""
    default_project_id: str | None = "default"
    timeout_seconds: float = 10.0
    state_path: Path = dataclasses.field(default_factory=lambda: Path(DEFAULT_STATE_PATH))
    """Explicit root directories; when non-empty, replaces auto roots from adapters."""
    roots: list[Path] = dataclasses.field(default_factory=list)
    extra_roots: list[Path] = dataclasses.field(default_factory=list)
    enabled_adapters: list[str] = dataclasses.field(
        default_factory=lambda: list(DEFAULT_ENABLED_ADAPTERS),
    )
    debug: bool = False

    def resolved_roots(self, home: Path | None = None) -> list[Path]:
        """Directories to watch (recursive)."""
        h = home if home is not None else Path.home()
        return merged_watch_roots(
            home=h,
            enabled_adapter_ids=self.enabled_adapters,
            roots_override=self.roots if self.roots else None,
            extra_roots=self.extra_roots,
        )


def load_config(config_path: Path | None = None) -> WatchConfig:
    """Load WatchConfig from TOML; defaults if missing or malformed."""
    path = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    if not path.exists():
        return WatchConfig()

    try:
        with open(path, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)
    except Exception:
        return WatchConfig()

    section: dict[str, Any] = data.get("am_codex_watch", {})

    roots_raw = section.get("roots")
    roots: list[Path] = []
    if isinstance(roots_raw, list) and roots_raw:
        roots = [Path(str(x)).expanduser() for x in roots_raw]

    extra_raw = section.get("extra_roots")
    extra_roots: list[Path] = []
    if isinstance(extra_raw, list) and extra_raw:
        extra_roots = [Path(str(x)).expanduser() for x in extra_raw]

    adapters_raw = section.get("adapters")
    enabled: list[str]
    if isinstance(adapters_raw, list) and len(adapters_raw) > 0:
        enabled = [str(x) for x in adapters_raw]
    else:
        enabled = list(DEFAULT_ENABLED_ADAPTERS)

    state_raw = section.get("state_path")
    state_path = Path(str(state_raw)).expanduser() if state_raw else DEFAULT_STATE_PATH

    return WatchConfig(
        endpoint=str(section.get("endpoint", "http://127.0.0.1:8765")),
        api_key=str(section.get("api_key", "")),
        default_project_id=section.get("default_project_id", "default"),
        timeout_seconds=float(section.get("timeout_seconds", 10.0)),
        state_path=state_path,
        roots=roots,
        extra_roots=extra_roots,
        enabled_adapters=enabled,
        debug=bool(section.get("debug", False)),
    )
