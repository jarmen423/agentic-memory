"""Lightweight in-process metrics for the OpenClaw foundation wave.

This module intentionally keeps observability simple:

- no external metrics backend is required to use it
- request metrics are collected in-process from FastAPI middleware
- `/metrics` exposes Prometheus-compatible text for scraping or debugging

The goal for this wave is operational visibility, not a full metrics platform.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock

_LOCK = Lock()
_REQUEST_COUNTS: Counter[tuple[str, str, str]] = Counter()
_REQUEST_DURATION_SUMS: Counter[tuple[str, str]] = Counter()
_REQUEST_DURATION_COUNTS: Counter[tuple[str, str]] = Counter()
_ERROR_COUNTS: Counter[tuple[str, str, str]] = Counter()


def _escape_label(value: str) -> str:
    """Escape Prometheus label values safely."""

    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def record_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record one HTTP request for Prometheus-style export."""

    request_key = (method.upper(), path, str(status_code))
    duration_key = (method.upper(), path)
    with _LOCK:
        _REQUEST_COUNTS[request_key] += 1
        _REQUEST_DURATION_SUMS[duration_key] += duration_seconds
        _REQUEST_DURATION_COUNTS[duration_key] += 1


def record_error_response(*, code: str, path: str, status_code: int) -> None:
    """Record one normalized API error response."""

    error_key = (code, path, str(status_code))
    with _LOCK:
        _ERROR_COUNTS[error_key] += 1


def render_prometheus_metrics() -> str:
    """Render the current in-process metrics in Prometheus text format."""

    lines = [
        "# HELP am_http_requests_total Total HTTP requests handled by am-server.",
        "# TYPE am_http_requests_total counter",
    ]
    with _LOCK:
        for (method, path, status_code), value in sorted(_REQUEST_COUNTS.items()):
            lines.append(
                'am_http_requests_total{method="%s",path="%s",status_code="%s"} %s'
                % (
                    _escape_label(method),
                    _escape_label(path),
                    _escape_label(status_code),
                    value,
                )
            )

        lines.extend(
            [
                "# HELP am_http_request_duration_seconds Request duration summary for am-server.",
                "# TYPE am_http_request_duration_seconds summary",
            ]
        )
        for (method, path), value in sorted(_REQUEST_DURATION_COUNTS.items()):
            labels = 'method="%s",path="%s"' % (
                _escape_label(method),
                _escape_label(path),
            )
            lines.append(f"am_http_request_duration_seconds_count{{{labels}}} {value}")
            lines.append(
                "am_http_request_duration_seconds_sum{%s} %s"
                % (
                    labels,
                    _REQUEST_DURATION_SUMS[(method, path)],
                )
            )

        lines.extend(
            [
                "# HELP am_api_error_responses_total Total normalized API error responses.",
                "# TYPE am_api_error_responses_total counter",
            ]
        )
        for (code, path, status_code), value in sorted(_ERROR_COUNTS.items()):
            lines.append(
                'am_api_error_responses_total{code="%s",path="%s",status_code="%s"} %s'
                % (
                    _escape_label(code),
                    _escape_label(path),
                    _escape_label(status_code),
                    value,
                )
            )

    return "\n".join(lines) + "\n"
