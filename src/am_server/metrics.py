"""Lightweight in-process counters and summaries for ``am_server`` and OpenClaw.

All state lives in the process; a lock serializes updates. FastAPI middleware and
route handlers call the ``record_*`` helpers; :func:`render_prometheus_metrics` turns
the same data into Prometheus text exposition (suitable for ``/metrics`` scraping),
and :func:`snapshot_metrics` exposes an equivalent structured dict for dashboards
and tests.

**Prometheus metric names** (see :func:`render_prometheus_metrics` for exact labels):

* ``am_http_requests_total`` (counter) — ``method``, ``path``, ``status_code``.
* ``am_http_request_duration_seconds`` (summary) — ``method``, ``path``; emits
  ``_count`` and ``_sum`` (no quantiles in-process).
* ``am_api_error_responses_total`` (counter) — normalized ``code``, ``path``,
  ``status_code``.
* ``am_mcp_surface_requests_total`` (counter) — ``surface``, ``mount_path``,
  ``auth_surface``, ``transport``, ``status_code`` (splits public vs internal MCP).
* ``am_ingest_turns_total`` (counter) — OpenClaw ingest: ``workspace_id``,
  ``agent_id``, ``source_key``.
* ``am_ingest_errors_total`` (counter) — ingest failures: ``workspace_id``,
  ``error_code``.
* ``am_search_requests_total`` (counter) — memory search: ``workspace_id``, ``module``.
* ``am_search_latency_seconds`` (summary) — search latency by ``module``; ``_count`` /
  ``_sum``.
* ``am_context_resolve_latency_seconds`` (summary) — context resolution; labeled
  ``context_engine`` (currently ``default``).
* ``am_active_sessions`` (gauge) — distinct session IDs registered per ``workspace_id``
  in this process (no TTL; grows until restart).

**Operational notes:** Search recording duplicates latency into one summary per module
label when multiple modules are requested. Session counts reflect registrations seen
since process start, not lease-based liveness.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock

_LOCK = Lock()
_REQUEST_COUNTS: Counter[tuple[str, str, str]] = Counter()
_REQUEST_DURATION_SUMS: Counter[tuple[str, str]] = Counter()
_REQUEST_DURATION_COUNTS: Counter[tuple[str, str]] = Counter()
_ERROR_COUNTS: Counter[tuple[str, str, str]] = Counter()
_MCP_SURFACE_COUNTS: Counter[tuple[str, str, str, str, str]] = Counter()
_OPENCLAW_INGEST_COUNTS: Counter[tuple[str, str, str]] = Counter()
_OPENCLAW_INGEST_ERROR_COUNTS: Counter[tuple[str, str]] = Counter()
_OPENCLAW_SEARCH_COUNTS: Counter[tuple[str, str]] = Counter()
_OPENCLAW_SEARCH_LATENCY_SUMS: Counter[str] = Counter()
_OPENCLAW_SEARCH_LATENCY_COUNTS: Counter[str] = Counter()
_OPENCLAW_CONTEXT_RESOLVE_SUMS: Counter[str] = Counter()
_OPENCLAW_CONTEXT_RESOLVE_COUNTS: Counter[str] = Counter()
_OPENCLAW_ACTIVE_SESSIONS: dict[str, set[str]] = {}


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
    """Increment HTTP request counter and duration summary for one completed request.

    Feeds ``am_http_requests_total`` and ``am_http_request_duration_seconds``. Method is
    normalized to upper case; path and status are stored as provided.

    Args:
        method: HTTP verb (e.g. ``GET``).
        path: Route or path label used in metrics (caller-defined granularity).
        status_code: Final response status class (e.g. 200, 401).
        duration_seconds: Wall time for the request, in seconds.
    """

    request_key = (method.upper(), path, str(status_code))
    duration_key = (method.upper(), path)
    with _LOCK:
        _REQUEST_COUNTS[request_key] += 1
        _REQUEST_DURATION_SUMS[duration_key] += duration_seconds
        _REQUEST_DURATION_COUNTS[duration_key] += 1


def record_error_response(*, code: str, path: str, status_code: int) -> None:
    """Increment ``am_api_error_responses_total`` for one application-level error.

    Args:
        code: Stable error code string (matches API JSON ``detail.code`` where applicable).
        path: Path label grouping errors for dashboards.
        status_code: HTTP status returned to the client.
    """

    error_key = (code, path, str(status_code))
    with _LOCK:
        _ERROR_COUNTS[error_key] += 1


def record_mcp_surface_request(
    *,
    surface: str,
    mount_path: str,
    auth_surface: str,
    transport: str,
    status_code: int,
) -> None:
    """Increment ``am_mcp_surface_requests_total`` for one MCP HTTP request.

    Labels distinguish logical ``surface`` name, physical ``mount_path``, auth surface
    (``mcp_public`` vs ``mcp_internal``), ``transport``, and HTTP ``status_code``—useful
    to separate public plugin traffic from self-hosted full-tool mounts.

    Args:
        surface: Profile or logical surface name (e.g. from :mod:`am_server.mcp_profiles`).
        mount_path: HTTP mount prefix for this MCP app.
        auth_surface: Auth bucket passed to token validation.
        transport: ``streamable_http`` or ``sse``.
        status_code: HTTP status for this MCP request.
    """

    surface_key = (
        surface,
        mount_path,
        auth_surface,
        transport,
        str(status_code),
    )
    with _LOCK:
        _MCP_SURFACE_COUNTS[surface_key] += 1


def record_openclaw_session_registration(*, workspace_id: str, session_id: str) -> None:
    """Register a session ID for ``workspace_id`` for ``am_active_sessions`` gauge.

    Stores distinct ``session_id`` strings per workspace in-memory. There is no expiry
    or eviction: the set grows until process restart, so the gauge is a coarse
    "ever seen in this process" signal, not concurrent live sessions.

    Args:
        workspace_id: Tenant/workspace key.
        session_id: Opaque session identifier from the client or session layer.
    """

    with _LOCK:
        sessions = _OPENCLAW_ACTIVE_SESSIONS.setdefault(workspace_id, set())
        sessions.add(session_id)


def record_openclaw_turn_ingest(*, workspace_id: str, agent_id: str, source_key: str) -> None:
    """Increment ``am_ingest_turns_total`` after a successful turn ingest.

    Args:
        workspace_id: Tenant/workspace key.
        agent_id: Agent or actor identifier for the ingest.
        source_key: Channel or source label (e.g. tool vs UI).
    """

    ingest_key = (workspace_id, agent_id, source_key)
    with _LOCK:
        _OPENCLAW_INGEST_COUNTS[ingest_key] += 1


def record_openclaw_ingest_error(*, workspace_id: str, error_code: str) -> None:
    """Increment ``am_ingest_errors_total`` for a failed ingest.

    Args:
        workspace_id: Tenant/workspace key.
        error_code: Stable failure classifier for alerting and dashboards.
    """

    error_key = (workspace_id, error_code)
    with _LOCK:
        _OPENCLAW_INGEST_ERROR_COUNTS[error_key] += 1


def record_openclaw_search(
    *,
    workspace_id: str,
    modules: list[str] | None,
    duration_seconds: float,
) -> None:
    """Record one successful OpenClaw search: counts and latency per module label.

    Updates ``am_search_requests_total`` (per ``workspace_id`` and ``module``) and
    ``am_search_latency_seconds`` summaries. Each non-empty, trimmed module in
    ``modules`` gets one count and the full ``duration_seconds`` attributed to that
    module's latency summary. If ``modules`` is empty or all blank, uses the
    synthetic label ``all``.

    Args:
        workspace_id: Tenant/workspace key.
        modules: Optional filter list from the request; drives metric cardinality.
        duration_seconds: End-to-end search time in seconds.
    """

    normalized_modules = sorted({module.strip() for module in (modules or []) if module and module.strip()})
    labels = normalized_modules or ["all"]
    with _LOCK:
        for module in labels:
            _OPENCLAW_SEARCH_COUNTS[(workspace_id, module)] += 1
            _OPENCLAW_SEARCH_LATENCY_SUMS[module] += duration_seconds
            _OPENCLAW_SEARCH_LATENCY_COUNTS[module] += 1


def record_openclaw_context_resolve(*, duration_seconds: float) -> None:
    """Record one successful context-resolution call into ``am_context_resolve_latency_seconds``.

    Currently aggregates under the fixed label ``context_engine="default"``.

    Args:
        duration_seconds: Time spent resolving context, in seconds.
    """

    with _LOCK:
        _OPENCLAW_CONTEXT_RESOLVE_SUMS["default"] += duration_seconds
        _OPENCLAW_CONTEXT_RESOLVE_COUNTS["default"] += 1


def snapshot_metrics() -> dict[str, object]:
    """Return the current in-process metrics as structured Python data.

    Mirrors :func:`render_prometheus_metrics` without parsing text: same label
    dimensions, suitable for dashboard JSON APIs, tests, and debugging.

    Returns:
        Dict with string keys: ``request_counts``, ``duration_summaries``,
        ``error_counts``, ``mcp_surface_counts``, ``openclaw_ingest_counts``,
        ``openclaw_ingest_error_counts``, ``openclaw_search_counts``,
        ``openclaw_search_latency_summaries``, ``openclaw_context_resolve_summaries``,
        ``openclaw_active_sessions``. Each value is a list of dict rows describing
        one label combination (plus ``count``, ``sum_seconds``, or ``avg_seconds``
        where applicable).
    """

    with _LOCK:
        request_counts = [
            {
                "method": method,
                "path": path,
                "status_code": int(status_code),
                "count": count,
            }
            for (method, path, status_code), count in sorted(_REQUEST_COUNTS.items())
        ]
        duration_summaries = [
            {
                "method": method,
                "path": path,
                "count": _REQUEST_DURATION_COUNTS[(method, path)],
                "sum_seconds": _REQUEST_DURATION_SUMS[(method, path)],
                "avg_seconds": (
                    _REQUEST_DURATION_SUMS[(method, path)] / _REQUEST_DURATION_COUNTS[(method, path)]
                    if _REQUEST_DURATION_COUNTS[(method, path)]
                    else 0.0
                ),
            }
            for (method, path) in sorted(_REQUEST_DURATION_COUNTS.keys())
        ]
        error_counts = [
            {
                "code": code,
                "path": path,
                "status_code": int(status_code),
                "count": count,
            }
            for (code, path, status_code), count in sorted(_ERROR_COUNTS.items())
        ]

    return {
        "request_counts": request_counts,
        "duration_summaries": duration_summaries,
        "error_counts": error_counts,
        "mcp_surface_counts": [
            {
                "surface": surface,
                "mount_path": mount_path,
                "auth_surface": auth_surface,
                "transport": transport,
                "status_code": int(status_code),
                "count": count,
            }
            for (surface, mount_path, auth_surface, transport, status_code), count in sorted(
                _MCP_SURFACE_COUNTS.items()
            )
        ],
        "openclaw_ingest_counts": [
            {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "source_key": source_key,
                "count": count,
            }
            for (workspace_id, agent_id, source_key), count in sorted(_OPENCLAW_INGEST_COUNTS.items())
        ],
        "openclaw_ingest_error_counts": [
            {
                "workspace_id": workspace_id,
                "error_code": error_code,
                "count": count,
            }
            for (workspace_id, error_code), count in sorted(_OPENCLAW_INGEST_ERROR_COUNTS.items())
        ],
        "openclaw_search_counts": [
            {
                "workspace_id": workspace_id,
                "module": module,
                "count": count,
            }
            for (workspace_id, module), count in sorted(_OPENCLAW_SEARCH_COUNTS.items())
        ],
        "openclaw_search_latency_summaries": [
            {
                "module": module,
                "count": _OPENCLAW_SEARCH_LATENCY_COUNTS[module],
                "sum_seconds": _OPENCLAW_SEARCH_LATENCY_SUMS[module],
                "avg_seconds": (
                    _OPENCLAW_SEARCH_LATENCY_SUMS[module] / _OPENCLAW_SEARCH_LATENCY_COUNTS[module]
                    if _OPENCLAW_SEARCH_LATENCY_COUNTS[module]
                    else 0.0
                ),
            }
            for module in sorted(_OPENCLAW_SEARCH_LATENCY_COUNTS.keys())
        ],
        "openclaw_context_resolve_summaries": [
            {
                "count": _OPENCLAW_CONTEXT_RESOLVE_COUNTS[label],
                "sum_seconds": _OPENCLAW_CONTEXT_RESOLVE_SUMS[label],
                "avg_seconds": (
                    _OPENCLAW_CONTEXT_RESOLVE_SUMS[label] / _OPENCLAW_CONTEXT_RESOLVE_COUNTS[label]
                    if _OPENCLAW_CONTEXT_RESOLVE_COUNTS[label]
                    else 0.0
                ),
            }
            for label in sorted(_OPENCLAW_CONTEXT_RESOLVE_COUNTS.keys())
        ],
        "openclaw_active_sessions": [
            {
                "workspace_id": workspace_id,
                "count": len(session_ids),
            }
            for workspace_id, session_ids in sorted(_OPENCLAW_ACTIVE_SESSIONS.items())
        ],
    }


def render_prometheus_metrics() -> str:
    """Render all in-process metrics as Prometheus exposition text (newline-terminated).

    Metric names and label sets match the module docstring inventory. Label values are
    escaped per Prometheus rules (backslash, quotes, newlines).

    Returns:
        A single string suitable for HTTP ``text/plain`` scrape bodies.
    """

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

        lines.extend(
            [
                "# HELP am_mcp_surface_requests_total Total requests received by each hosted MCP surface.",
                "# TYPE am_mcp_surface_requests_total counter",
            ]
        )
        for (surface, mount_path, auth_surface, transport, status_code), value in sorted(
            _MCP_SURFACE_COUNTS.items()
        ):
            lines.append(
                'am_mcp_surface_requests_total{surface="%s",mount_path="%s",auth_surface="%s",transport="%s",status_code="%s"} %s'
                % (
                    _escape_label(surface),
                    _escape_label(mount_path),
                    _escape_label(auth_surface),
                    _escape_label(transport),
                    _escape_label(status_code),
                    value,
                )
            )

        lines.extend(
            [
                "# HELP am_ingest_turns_total Total successful OpenClaw turn ingests.",
                "# TYPE am_ingest_turns_total counter",
            ]
        )
        for (workspace_id, agent_id, source_key), value in sorted(_OPENCLAW_INGEST_COUNTS.items()):
            lines.append(
                'am_ingest_turns_total{workspace_id="%s",agent_id="%s",source_key="%s"} %s'
                % (
                    _escape_label(workspace_id),
                    _escape_label(agent_id),
                    _escape_label(source_key),
                    value,
                )
            )

        lines.extend(
            [
                "# HELP am_ingest_errors_total Total OpenClaw ingest failures.",
                "# TYPE am_ingest_errors_total counter",
            ]
        )
        for (workspace_id, error_code), value in sorted(_OPENCLAW_INGEST_ERROR_COUNTS.items()):
            lines.append(
                'am_ingest_errors_total{workspace_id="%s",error_code="%s"} %s'
                % (
                    _escape_label(workspace_id),
                    _escape_label(error_code),
                    value,
                )
            )

        lines.extend(
            [
                "# HELP am_search_requests_total Total successful OpenClaw memory searches.",
                "# TYPE am_search_requests_total counter",
            ]
        )
        for (workspace_id, module), value in sorted(_OPENCLAW_SEARCH_COUNTS.items()):
            lines.append(
                'am_search_requests_total{workspace_id="%s",module="%s"} %s'
                % (
                    _escape_label(workspace_id),
                    _escape_label(module),
                    value,
                )
            )

        lines.extend(
            [
                "# HELP am_search_latency_seconds OpenClaw memory-search latency summary.",
                "# TYPE am_search_latency_seconds summary",
            ]
        )
        for module in sorted(_OPENCLAW_SEARCH_LATENCY_COUNTS.keys()):
            labels = 'module="%s"' % _escape_label(module)
            lines.append(f"am_search_latency_seconds_count{{{labels}}} {_OPENCLAW_SEARCH_LATENCY_COUNTS[module]}")
            lines.append(
                "am_search_latency_seconds_sum{%s} %s"
                % (
                    labels,
                    _OPENCLAW_SEARCH_LATENCY_SUMS[module],
                )
            )

        lines.extend(
            [
                "# HELP am_context_resolve_latency_seconds OpenClaw context-resolution latency summary.",
                "# TYPE am_context_resolve_latency_seconds summary",
            ]
        )
        for label in sorted(_OPENCLAW_CONTEXT_RESOLVE_COUNTS.keys()):
            labels = 'context_engine="%s"' % _escape_label(label)
            lines.append(
                f"am_context_resolve_latency_seconds_count{{{labels}}} {_OPENCLAW_CONTEXT_RESOLVE_COUNTS[label]}"
            )
            lines.append(
                "am_context_resolve_latency_seconds_sum{%s} %s"
                % (
                    labels,
                    _OPENCLAW_CONTEXT_RESOLVE_SUMS[label],
                )
            )

        lines.extend(
            [
                "# HELP am_active_sessions Distinct registered OpenClaw sessions seen by this process.",
                "# TYPE am_active_sessions gauge",
            ]
        )
        for workspace_id, session_ids in sorted(_OPENCLAW_ACTIVE_SESSIONS.items()):
            lines.append(
                'am_active_sessions{workspace_id="%s"} %s'
                % (
                    _escape_label(workspace_id),
                    len(session_ids),
                )
            )

    return "\n".join(lines) + "\n"
