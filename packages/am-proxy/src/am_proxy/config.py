"""Configuration loading for am-proxy.

Config file location: ~/.config/am-proxy/config.toml
Missing file is not an error — all fields have defaults.
CLI flags override config file values when passed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

# Default config file path
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "am-proxy" / "config.toml"


@dataclasses.dataclass
class ProxyConfig:
    """Runtime configuration for am-proxy.

    All fields have defaults so the proxy works with zero configuration.
    """

    endpoint: str = "http://localhost:8000"
    api_key: str = ""
    default_project_id: str = "default"
    timeout_seconds: float = 5.0
    buffer_ttl_seconds: float = 300.0
    debug: bool = False


def load_config(config_path: Path | None = None) -> ProxyConfig:
    """Load ProxyConfig from TOML file, returning defaults if file absent.

    Args:
        config_path: Path to TOML config file. Defaults to ~/.config/am-proxy/config.toml.

    Returns:
        ProxyConfig populated from file, or all-defaults if file missing.
    """
    path = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    if not path.exists():
        return ProxyConfig()

    try:
        with open(path, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)
    except Exception:
        # Malformed TOML — fall back to defaults silently
        return ProxyConfig()

    section: dict[str, Any] = data.get("am_proxy", {})
    return ProxyConfig(
        endpoint=section.get("endpoint", "http://localhost:8000"),
        api_key=section.get("api_key", ""),
        default_project_id=section.get("default_project_id", "default"),
        timeout_seconds=float(section.get("timeout_seconds", 5.0)),
        buffer_ttl_seconds=float(section.get("buffer_ttl_seconds", 300.0)),
        debug=bool(section.get("debug", False)),
    )
