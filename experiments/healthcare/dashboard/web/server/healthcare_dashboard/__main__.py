"""Run with: ``python -m healthcare_dashboard`` from the ``server`` directory."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    from healthcare_dashboard.config import listen_host, listen_port
    from healthcare_dashboard.main import app

    uvicorn.run(
        app,
        host=listen_host(),
        port=listen_port(),
        log_level="info",
    )


if __name__ == "__main__":
    main()
