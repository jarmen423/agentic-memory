"""Dashboard-facing OpenClaw read APIs.

This module exposes an authenticated read surface for the Phase 13 dashboard.
The goal is to provide operator-meaningful data without introducing a second
state system:

- product-state remains the source of truth for workspace/device/agent topology
- in-process metrics remain the source of truth for request/error counters
- recent search activity is reconstructed from bounded product-state events

The dashboard wave intentionally keeps this contract read-only. Packaging,
release, and multi-tenant auth work remain out of scope for this phase.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query

from am_server.auth import require_auth
from am_server.dependencies import get_product_store
from am_server.metrics import snapshot_metrics
from am_server.models import (
    OpenClawDashboardAgentSessionModel,
    OpenClawDashboardErrorMetricModel,
    OpenClawDashboardHealthComponentModel,
    OpenClawDashboardMetricCardModel,
    OpenClawDashboardRecentSearchModel,
    OpenClawDashboardRequestMetricModel,
    OpenClawDashboardSummaryModel,
    OpenClawDashboardWorkspaceAgentModel,
    OpenClawDashboardWorkspaceDeviceModel,
    OpenClawDashboardWorkspaceModel,
)

router = APIRouter(dependencies=[Depends(require_auth)])


def _openclaw_integrations(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only integrations that represent registered OpenClaw sessions."""

    integrations = state.get("integrations", [])
    return [
        integration
        for integration in integrations
        if integration.get("surface") == "openclaw" and isinstance(integration.get("config"), dict)
    ]


def _openclaw_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return product-state events emitted by the OpenClaw routes."""

    events = state.get("events", [])
    return [
        event
        for event in events
        if event.get("actor") == "openclaw" and isinstance(event.get("details"), dict)
    ]


def _build_request_metrics(snapshot: dict[str, object]) -> list[OpenClawDashboardRequestMetricModel]:
    """Translate raw metric counters into dashboard-friendly request rows."""

    duration_by_key = {
        (row["method"], row["path"]): row
        for row in snapshot.get("duration_summaries", [])
        if isinstance(row, dict)
    }
    metrics: list[OpenClawDashboardRequestMetricModel] = []
    for row in snapshot.get("request_counts", []):
        if not isinstance(row, dict):
            continue
        duration_row = duration_by_key.get((row["method"], row["path"]), {})
        metrics.append(
            OpenClawDashboardRequestMetricModel(
                method=str(row["method"]),
                path=str(row["path"]),
                status_code=int(row["status_code"]),
                count=int(row["count"]),
                avg_seconds=float(duration_row.get("avg_seconds", 0.0)),
            )
        )
    return metrics


def _build_error_metrics(snapshot: dict[str, object]) -> list[OpenClawDashboardErrorMetricModel]:
    """Translate normalized error counters into dashboard rows."""

    metrics: list[OpenClawDashboardErrorMetricModel] = []
    for row in snapshot.get("error_counts", []):
        if not isinstance(row, dict):
            continue
        metrics.append(
            OpenClawDashboardErrorMetricModel(
                code=str(row["code"]),
                path=str(row["path"]),
                status_code=int(row["status_code"]),
                count=int(row["count"]),
            )
        )
    return metrics


def _calculate_health_score(
    *,
    components: list[OpenClawDashboardHealthComponentModel],
    error_metrics: list[OpenClawDashboardErrorMetricModel],
) -> int:
    """Calculate a simple operator-facing health score for the overview page."""

    score = 100
    degraded_components = sum(1 for component in components if component.status not in {"available", "healthy"})
    score -= degraded_components * 10
    score -= sum(metric.count for metric in error_metrics if metric.status_code >= 500) * 5
    return max(score, 0)


def _build_session_models(state: dict[str, Any]) -> list[OpenClawDashboardAgentSessionModel]:
    """Project the latest OpenClaw session registrations into session cards."""

    events = _openclaw_events(state)
    event_counts_by_session: dict[str, int] = defaultdict(int)
    last_activity_by_session: dict[str, str] = {}
    active_projects = {
        binding.get("session_id"): binding.get("project_id")
        for binding in state.get("active_projects", [])
        if isinstance(binding, dict)
    }

    for event in events:
        details = event.get("details", {})
        session_id = details.get("session_id")
        if not isinstance(session_id, str):
            continue
        event_counts_by_session[session_id] += 1
        last_activity_by_session[session_id] = str(event.get("timestamp") or "")

    sessions: list[OpenClawDashboardAgentSessionModel] = []
    for integration in _openclaw_integrations(state):
        config = integration["config"]
        session_id = str(config.get("session_id") or "")
        if not session_id:
            continue
        sessions.append(
            OpenClawDashboardAgentSessionModel(
                workspace_id=str(config.get("workspace_id") or ""),
                device_id=str(config.get("device_id") or "") or None,
                agent_id=str(config.get("agent_id") or ""),
                session_id=session_id,
                status=str(integration.get("status") or "unknown"),
                mode=str(config.get("mode") or "") or None,
                project_id=active_projects.get(session_id) or (str(config.get("project_id") or "") or None),
                context_engine=str(config.get("context_engine") or "") or None,
                integration_updated_at=str(integration.get("updated_at") or "") or None,
                last_activity_at=last_activity_by_session.get(session_id) or str(integration.get("updated_at") or "") or None,
                event_count=event_counts_by_session.get(session_id, 0),
            )
        )

    sessions.sort(
        key=lambda session: (
            session.workspace_id,
            session.device_id or "",
            session.agent_id,
            session.session_id,
        )
    )
    return sessions


def _build_recent_searches(
    state: dict[str, Any],
    *,
    limit: int,
) -> list[OpenClawDashboardRecentSearchModel]:
    """Return recent search/context activity from the bounded event log."""

    search_event_types = {"openclaw_memory_search", "openclaw_context_resolve"}
    recent: list[OpenClawDashboardRecentSearchModel] = []
    for event in reversed(_openclaw_events(state)):
        event_type = str(event.get("event_type") or "")
        if event_type not in search_event_types:
            continue
        details = event.get("details", {})
        recent.append(
            OpenClawDashboardRecentSearchModel(
                event_type=event_type,
                timestamp=str(event.get("timestamp") or ""),
                workspace_id=str(details.get("workspace_id") or "") or None,
                agent_id=str(details.get("agent_id") or "") or None,
                session_id=str(details.get("session_id") or "") or None,
                query=str(details.get("query") or "") or None,
                result_count=(
                    int(details["result_count"])
                    if isinstance(details.get("result_count"), int)
                    else None
                ),
                project_id=str(details.get("project_id") or "") or None,
            )
        )
        if len(recent) >= limit:
            break
    return recent


def _build_workspace_models(state: dict[str, Any]) -> list[OpenClawDashboardWorkspaceModel]:
    """Group OpenClaw sessions into the workspace/device/agent tree."""

    active_projects_by_workspace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for binding in state.get("active_projects", []):
        if isinstance(binding, dict):
            active_projects_by_workspace[str(binding.get("workspace_id") or "")].append(binding)

    automations_by_workspace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for automation in state.get("project_automations", []):
        if isinstance(automation, dict):
            automations_by_workspace[str(automation.get("workspace_id") or "")].append(automation)

    workspace_devices: dict[str, dict[str, list[OpenClawDashboardWorkspaceAgentModel]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for session in _build_session_models(state):
        workspace_devices[session.workspace_id][session.device_id or "unknown-device"].append(
            OpenClawDashboardWorkspaceAgentModel(
                agent_id=session.agent_id,
                session_id=session.session_id,
                status=session.status,
                project_id=session.project_id,
                mode=session.mode,
                context_engine=session.context_engine,
                updated_at=session.last_activity_at,
            )
        )

    workspaces: list[OpenClawDashboardWorkspaceModel] = []
    for workspace_id, devices in sorted(workspace_devices.items()):
        workspaces.append(
            OpenClawDashboardWorkspaceModel(
                workspace_id=workspace_id,
                devices=[
                    OpenClawDashboardWorkspaceDeviceModel(
                        device_id=device_id,
                        agents=sorted(device_agents, key=lambda agent: agent.agent_id),
                    )
                    for device_id, device_agents in sorted(devices.items())
                ],
                active_projects=sorted(
                    active_projects_by_workspace.get(workspace_id, []),
                    key=lambda project: (
                        str(project.get("agent_id") or ""),
                        str(project.get("session_id") or ""),
                    ),
                ),
                automations=sorted(
                    automations_by_workspace.get(workspace_id, []),
                    key=lambda automation: (
                        str(automation.get("project_id") or ""),
                        str(automation.get("automation_kind") or ""),
                    ),
                ),
            )
        )

    return workspaces


def _build_summary(
    *,
    state: dict[str, Any],
    request_metrics: list[OpenClawDashboardRequestMetricModel],
    error_metrics: list[OpenClawDashboardErrorMetricModel],
) -> OpenClawDashboardSummaryModel:
    """Build the dashboard overview card payload from current state + metrics."""

    sessions = _build_session_models(state)
    active_agents = len({session.agent_id for session in sessions})
    turns_ingested = sum(
        metric.count
        for metric in request_metrics
        if metric.path == "/openclaw/memory/ingest-turn" and metric.status_code < 400
    )
    searches_total = sum(
        metric.count
        for metric in request_metrics
        if metric.path == "/openclaw/memory/search" and metric.status_code < 400
    )
    context_resolves_total = sum(
        metric.count
        for metric in request_metrics
        if metric.path == "/openclaw/context/resolve" and metric.status_code < 400
    )
    components = [
        OpenClawDashboardHealthComponentModel(
            component=name,
            status=str(payload.get("status") or "unknown"),
            details=payload.get("details", {}),
            updated_at=str(payload.get("updated_at") or "") or None,
        )
        for name, payload in sorted(state.get("runtime", {}).get("components", {}).items())
        if isinstance(payload, dict)
    ]
    error_total = sum(metric.count for metric in error_metrics)
    health_score = _calculate_health_score(components=components, error_metrics=error_metrics)

    return OpenClawDashboardSummaryModel(
        active_agents=active_agents,
        active_sessions=len(sessions),
        turns_ingested=turns_ingested,
        searches_total=searches_total,
        context_resolves_total=context_resolves_total,
        error_responses_total=error_total,
        health_score=health_score,
        cards=[
            OpenClawDashboardMetricCardModel(
                key="active_agents",
                label="Active Agents",
                value=active_agents,
                status="healthy" if active_agents else "info",
                description="Distinct OpenClaw agent ids currently registered in product state.",
            ),
            OpenClawDashboardMetricCardModel(
                key="turns_ingested",
                label="Turns Ingested",
                value=turns_ingested,
                status="healthy" if turns_ingested else "info",
                description="Successful `/openclaw/memory/ingest-turn` requests observed since process start.",
            ),
            OpenClawDashboardMetricCardModel(
                key="searches_total",
                label="Searches",
                value=searches_total,
                status="healthy" if searches_total else "info",
                description="Successful `/openclaw/memory/search` requests observed since process start.",
            ),
            OpenClawDashboardMetricCardModel(
                key="health_score",
                label="Health Score",
                value=health_score,
                unit="/100",
                status="healthy" if health_score >= 80 else "warning",
                description="Heuristic score derived from runtime component status and normalized API errors.",
            ),
        ],
    )


@router.get("/openclaw/metrics/summary")
def dashboard_metrics_summary() -> dict[str, object]:
    """Return the operator-facing overview payload for dashboard summary cards."""

    state = get_product_store().status_payload()
    snapshot = snapshot_metrics()
    request_metrics = _build_request_metrics(snapshot)
    error_metrics = _build_error_metrics(snapshot)
    summary = _build_summary(state=state, request_metrics=request_metrics, error_metrics=error_metrics)
    return {
        "status": "ok",
        "summary": summary.model_dump(),
        "request_metrics": [metric.model_dump() for metric in request_metrics],
        "error_metrics": [metric.model_dump() for metric in error_metrics],
    }


@router.get("/openclaw/health/detailed")
def dashboard_health_detailed() -> dict[str, object]:
    """Return runtime component health plus request/error telemetry details."""

    state = get_product_store().status_payload()
    snapshot = snapshot_metrics()
    request_metrics = _build_request_metrics(snapshot)
    error_metrics = _build_error_metrics(snapshot)
    components = [
        OpenClawDashboardHealthComponentModel(
            component=name,
            status=str(payload.get("status") or "unknown"),
            details=payload.get("details", {}),
            updated_at=str(payload.get("updated_at") or "") or None,
        )
        for name, payload in sorted(state.get("runtime", {}).get("components", {}).items())
        if isinstance(payload, dict)
    ]
    return {
        "status": "ok",
        "components": [component.model_dump() for component in components],
        "request_metrics": [metric.model_dump() for metric in request_metrics],
        "error_metrics": [metric.model_dump() for metric in error_metrics],
        "summary": _build_summary(
            state=state,
            request_metrics=request_metrics,
            error_metrics=error_metrics,
        ).model_dump(),
    }


@router.get("/openclaw/search/recent")
def dashboard_recent_searches(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    """Return the most recent dashboard-visible search and context events."""

    state = get_product_store().status_payload()
    recent = _build_recent_searches(state, limit=limit)
    return {
        "status": "ok",
        "recent_searches": [item.model_dump() for item in recent],
        "summary": {
            "returned": len(recent),
            "limit": limit,
        },
    }


@router.get("/openclaw/agents/{agent_id}/sessions")
def dashboard_agent_sessions(
    agent_id: str,
    workspace_id: str | None = Query(default=None),
) -> dict[str, object]:
    """Return the latest-known session records for one OpenClaw agent id."""

    sessions = _build_session_models(get_product_store().status_payload())
    filtered = [
        session
        for session in sessions
        if session.agent_id == agent_id and (workspace_id is None or session.workspace_id == workspace_id)
    ]
    return {
        "status": "ok",
        "agent_id": agent_id,
        "workspace_id": workspace_id,
        "sessions": [session.model_dump() for session in filtered],
    }


@router.get("/openclaw/workspaces")
def dashboard_workspaces() -> dict[str, object]:
    """Return the workspace/device/agent tree for the dashboard workspace page."""

    state = get_product_store().status_payload()
    workspaces = _build_workspace_models(state)
    return {
        "status": "ok",
        "workspaces": [workspace.model_dump() for workspace in workspaces],
        "summary": {
            "workspace_count": len(workspaces),
            "device_count": sum(len(workspace.devices) for workspace in workspaces),
            "agent_count": sum(len(device.agents) for workspace in workspaces for device in workspace.devices),
        },
    }
