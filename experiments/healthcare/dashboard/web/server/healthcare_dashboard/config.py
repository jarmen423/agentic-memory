"""Runtime configuration for the healthcare dashboard API.

Environment variables keep secrets out of code and match how the app is run on
the Hetzner experiment host (Postgres on loopback) versus local dev (often via
SSH tunnel to a high local port).
"""

from __future__ import annotations

import os
from pathlib import Path


def database_url() -> str:
    """Postgres DSN. On the VM use 127.0.0.1:5432; locally, tunnel to a free port."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments",
    )


def listen_host() -> str:
    """Bind address. Default loopback so Cloudflare Tunnel can reach the service safely."""
    return os.environ.get("HOST", "127.0.0.1")


def listen_port() -> int:
    return int(os.environ.get("PORT", "8787"))


def cors_origins() -> list[str]:
    """Optional dev CORS; production is same-origin when UI is served by this app."""
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


def static_dist_dir() -> Path:
    """Directory containing the built Vite UI (index.html + assets/)."""
    return Path(__file__).resolve().parent.parent / "static"
