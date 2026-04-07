"""Configuration helpers for the desktop shell."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _default_host() -> str:
    return os.environ.get("DESKTOP_SHELL_HOST", "127.0.0.1")


def _default_port() -> int:
    return int(os.environ.get("DESKTOP_SHELL_PORT", "3030"))


def _default_backend_url() -> str:
    return os.environ.get("DESKTOP_SHELL_BACKEND_URL", os.environ.get("AM_SERVER_URL", "http://127.0.0.1:8765"))


def _default_backend_api_key() -> str:
    return os.environ.get("DESKTOP_SHELL_API_KEY", os.environ.get("AM_SERVER_API_KEY", ""))


@dataclass(frozen=True)
class ShellSettings:
    """Runtime settings for the local shell."""

    host: str = field(default_factory=_default_host)
    port: int = field(default_factory=_default_port)
    backend_url: str = field(default_factory=_default_backend_url)
    backend_api_key: str = field(default_factory=_default_backend_api_key)
