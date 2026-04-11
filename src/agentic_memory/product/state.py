"""Persistent local product-state store used by CLI and desktop control surfaces.

This file now also stores OpenClaw project state, because the product model has
shifted away from a static setup-time ``project_id``. Instead:

- ``workspace_id`` remains the stable OpenClaw home-base boundary.
- ``agent_id`` identifies the OpenClaw agent within that workspace.
- ``session_id`` scopes an active project binding so one agent can work on
  multiple unrelated tasks without every memory inheriting the same tag.
- ``project_id`` becomes an optional active work label, not a permanent install
  choice.

Keeping this state local and explicit lets future agents recover the current
project semantics directly from code and stored JSON rather than from chat
history.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PRODUCT_STATE_ENV_VARS = (
    "AGENTIC_MEMORY_PRODUCT_STATE",
    "CODEMEMORY_PRODUCT_STATE",
)
DEFAULT_PRODUCT_STATE_PATH = Path.home() / ".agentic-memory" / "product-state.json"
DEFAULT_EVENT_CAP = 200
DEFAULT_ONBOARDING_STEPS = (
    "runtime_bootstrap",
    "repo_added",
    "integration_connected",
    "first_index_complete",
    "first_useful_result",
)
DEFAULT_COMPONENTS = {
    "cli": "available",
    "desktop_shell": "unknown",
    "server": "unknown",
    "browser_extension": "unknown",
    "mcp": "unknown",
    "proxy": "unknown",
    "openclaw_memory": "unknown",
    "openclaw_context_engine": "unknown",
}
DEFAULT_PROJECT_AUTOMATION_KIND = "research_ingestion"


def _utc_now() -> str:
    """Return an ISO8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class ProductStateStore:
    """Manage the local persisted state for product-facing workflows."""

    def __init__(self, state_path: str | Path | None = None) -> None:
        self.state_path = Path(state_path or self._resolve_state_path()).expanduser().resolve()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_state_path() -> Path:
        for env_name in DEFAULT_PRODUCT_STATE_ENV_VARS:
            raw = os.environ.get(env_name)
            if raw:
                return Path(raw)
        return DEFAULT_PRODUCT_STATE_PATH

    def _default_state(self) -> dict[str, Any]:
        timestamp = _utc_now()
        return {
            "schema_version": 1,
            "app": {
                "last_seen_at": None,
                "updated_at": timestamp,
                "onboarding": {
                    "required_steps": list(DEFAULT_ONBOARDING_STEPS),
                    "completed_steps": [],
                    "updated_at": timestamp,
                },
            },
            "repos": [],
            "integrations": [],
            "projects": [],
            "active_projects": [],
            "project_automations": [],
            "events": [],
            "runtime": {
                "components": {
                    name: {
                        "status": status,
                        "details": {},
                        "updated_at": timestamp,
                    }
                    for name, status in DEFAULT_COMPONENTS.items()
                }
            },
        }

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            state = self._default_state()
            self._write(state)
            return state

        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = self._default_state()

        return self._normalize(payload)

    def touch(self) -> dict[str, Any]:
        return self._update(lambda state: self._touch_state(state))

    def upsert_repo(
        self,
        repo_path: str | Path,
        *,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = Path(repo_path).expanduser().resolve()
        repo_record = {
            "path": str(resolved),
            "label": label or resolved.name,
            "initialized": self._repo_initialized(resolved),
            "metadata": metadata or {},
            "updated_at": _utc_now(),
        }

        # Inner closure: upsert the repo record into the state dict in-place.
        # _update() calls this with the current loaded state and then writes it back.
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            repos = state["repos"]
            for index, existing in enumerate(repos):
                if existing["path"] == repo_record["path"]:
                    repos[index] = {**existing, **repo_record}
                    self._touch_state(state)
                    return repos[index]

            repos.append(repo_record)
            repos.sort(key=lambda item: item["path"])
            self._touch_state(state)
            return repo_record

        return self._update(mutate)

    def upsert_integration(
        self,
        *,
        surface: str,
        target: str,
        status: str,
        config: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        surface_name = surface.strip()
        target_name = target.strip()
        if not surface_name or not target_name:
            raise ValueError("surface and target are required")

        record = {
            "surface": surface_name,
            "target": target_name,
            "status": status.strip(),
            "config": config or {},
            "last_error": last_error,
            "updated_at": _utc_now(),
        }

        # Inner closure: upsert the integration record, keyed on (surface, target).
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            integrations = state["integrations"]
            for index, existing in enumerate(integrations):
                if existing["surface"] == surface_name and existing["target"] == target_name:
                    integrations[index] = {**existing, **record}
                    self._touch_state(state)
                    return integrations[index]

            integrations.append(record)
            integrations.sort(key=lambda item: (item["surface"], item["target"]))
            self._touch_state(state)
            return record

        return self._update(mutate)

    def upsert_project(
        self,
        *,
        project_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a reusable project definition.

        Project definitions are intentionally lightweight. They are reusable
        across many OpenClaw workspaces and agents, so they do not encode the
        active binding themselves.
        """

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")

        record = {
            "project_id": normalized_project_id,
            "title": (title or normalized_project_id).strip(),
            "metadata": metadata or {},
            "updated_at": _utc_now(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            projects = state["projects"]
            for index, existing in enumerate(projects):
                if existing["project_id"] == normalized_project_id:
                    projects[index] = {**existing, **record}
                    self._touch_state(state)
                    return projects[index]

            projects.append(record)
            projects.sort(key=lambda item: item["project_id"])
            self._touch_state(state)
            return record

        return self._update(mutate)

    def activate_project_for_openclaw_identity(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        project_id: str,
        device_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Bind a project to one OpenClaw workspace/agent/session tuple.

        This is the core state transition behind "start working on project X".
        The binding is session-scoped so the same agent can later work on a
        different task without unrelated turns inheriting the old tag.
        """

        project = self.upsert_project(
            project_id=project_id,
            title=title,
            metadata=metadata or {},
        )
        binding = {
            "workspace_id": workspace_id.strip(),
            "agent_id": agent_id.strip(),
            "session_id": session_id.strip(),
            "device_id": device_id.strip() if device_id else None,
            "project_id": project["project_id"],
            "activated_at": _utc_now(),
            "updated_at": _utc_now(),
            "metadata": metadata or {},
        }
        if not binding["workspace_id"] or not binding["agent_id"] or not binding["session_id"]:
            raise ValueError("workspace_id, agent_id, and session_id are required")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            active_projects = state["active_projects"]
            for index, existing in enumerate(active_projects):
                if (
                    existing["workspace_id"] == binding["workspace_id"]
                    and existing["agent_id"] == binding["agent_id"]
                    and existing["session_id"] == binding["session_id"]
                ):
                    binding["activated_at"] = existing.get("activated_at", binding["activated_at"])
                    active_projects[index] = {**existing, **binding}
                    self._touch_state(state)
                    return active_projects[index]

            active_projects.append(binding)
            active_projects.sort(
                key=lambda item: (item["workspace_id"], item["agent_id"], item["session_id"])
            )
            self._touch_state(state)
            return binding

        return self._update(mutate)

    def deactivate_project_for_openclaw_identity(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Remove the active project binding for one OpenClaw session."""

        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            active_projects = state["active_projects"]
            for index, existing in enumerate(active_projects):
                if (
                    existing["workspace_id"] == workspace_id
                    and existing["agent_id"] == agent_id
                    and existing["session_id"] == session_id
                ):
                    removed = active_projects.pop(index)
                    self._touch_state(state)
                    return removed
            return None

        return self._update(mutate)

    def get_active_project_for_openclaw_identity(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Return the active project binding for one OpenClaw session if any."""

        state = self.load()
        for binding in state["active_projects"]:
            if (
                binding["workspace_id"] == workspace_id
                and binding["agent_id"] == agent_id
                and binding["session_id"] == session_id
            ):
                return binding
        return None

    def get_openclaw_session_registration(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the latest registered OpenClaw session for one identity tuple.

        OpenClaw session registration is currently persisted through the
        integration store rather than a dedicated session table. That is enough
        for project commands because the runtime keeps updating the integration
        config with the current `session_id` during bootstrap.
        """

        normalized_workspace_id = workspace_id.strip()
        normalized_agent_id = agent_id.strip()
        normalized_device_id = device_id.strip() if device_id else None
        if not normalized_workspace_id or not normalized_agent_id:
            raise ValueError("workspace_id and agent_id are required")

        state = self.load()
        for integration in reversed(state["integrations"]):
            if integration.get("surface") != "openclaw":
                continue

            config = integration.get("config", {})
            if not isinstance(config, dict):
                continue

            if config.get("workspace_id") != normalized_workspace_id:
                continue
            if config.get("agent_id") != normalized_agent_id:
                continue
            if normalized_device_id and config.get("device_id") != normalized_device_id:
                continue

            session_id = config.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                return integration

        return None

    def resolve_openclaw_session_id(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        explicit_session_id: str | None = None,
        device_id: str | None = None,
    ) -> str | None:
        """Resolve the active OpenClaw session id for one agent.

        Explicit session ids win. When omitted, the store falls back to the
        last registered OpenClaw session for this workspace/agent pair so the
        user-facing project commands do not need to ask for `--session-id`.
        """

        if explicit_session_id and explicit_session_id.strip():
            return explicit_session_id.strip()

        registration = self.get_openclaw_session_registration(
            workspace_id=workspace_id,
            agent_id=agent_id,
            device_id=device_id,
        )
        if not registration:
            return None

        config = registration.get("config", {})
        if isinstance(config, dict):
            session_id = config.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                return session_id.strip()
        return None

    def upsert_project_automation(
        self,
        *,
        workspace_id: str,
        project_id: str,
        enabled: bool = True,
        automation_kind: str = DEFAULT_PROJECT_AUTOMATION_KIND,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a workspace-scoped automation for a project."""

        normalized_workspace_id = workspace_id.strip()
        normalized_project_id = project_id.strip()
        normalized_kind = automation_kind.strip()
        if not normalized_workspace_id or not normalized_project_id or not normalized_kind:
            raise ValueError("workspace_id, project_id, and automation_kind are required")

        self.upsert_project(project_id=normalized_project_id, metadata=metadata or {})
        record = {
            "workspace_id": normalized_workspace_id,
            "project_id": normalized_project_id,
            "automation_kind": normalized_kind,
            "enabled": bool(enabled),
            "metadata": metadata or {},
            "updated_at": _utc_now(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            automations = state["project_automations"]
            for index, existing in enumerate(automations):
                if (
                    existing["workspace_id"] == normalized_workspace_id
                    and existing["project_id"] == normalized_project_id
                    and existing["automation_kind"] == normalized_kind
                ):
                    automations[index] = {**existing, **record}
                    self._touch_state(state)
                    return automations[index]

            automations.append(record)
            automations.sort(
                key=lambda item: (
                    item["workspace_id"],
                    item["project_id"],
                    item["automation_kind"],
                )
            )
            self._touch_state(state)
            return record

        return self._update(mutate)

    def set_component_status(
        self,
        component: str,
        *,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        component_name = component.strip()
        if component_name not in DEFAULT_COMPONENTS:
            raise ValueError(f"unsupported component: {component_name}")

        # Inner closure: overwrite the component entry under runtime.components.
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            components = state["runtime"]["components"]
            components[component_name] = {
                "status": status.strip(),
                "details": details or {},
                "updated_at": _utc_now(),
            }
            self._touch_state(state)
            return components[component_name]

        return self._update(mutate)

    def record_event(
        self,
        *,
        event_type: str,
        actor: str,
        status: str = "ok",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_type": event_type.strip(),
            "actor": actor.strip(),
            "status": status.strip(),
            "details": details or {},
            "timestamp": _utc_now(),
        }

        # Inner closure: append the event and trim the rolling buffer to DEFAULT_EVENT_CAP.
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            events = state["events"]
            events.append(event)
            if len(events) > DEFAULT_EVENT_CAP:
                del events[:-DEFAULT_EVENT_CAP]
            self._touch_state(state)
            return event

        return self._update(mutate)

    def update_onboarding_step(self, step: str, *, completed: bool = True) -> dict[str, Any]:
        step_name = step.strip()
        if not step_name:
            raise ValueError("step is required")

        # Inner closure: add or remove the step from the completed_steps set.
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            onboarding = state["app"]["onboarding"]
            completed_steps = set(onboarding.get("completed_steps", []))
            if completed:
                completed_steps.add(step_name)
            else:
                completed_steps.discard(step_name)
            onboarding["completed_steps"] = sorted(completed_steps)
            onboarding["updated_at"] = _utc_now()
            self._touch_state(state)
            return onboarding

        return self._update(mutate)

    def status_payload(self, *, repo_root: Path | None = None) -> dict[str, Any]:
        state = self.touch()
        onboarding = state["app"]["onboarding"]
        required_steps = onboarding.get("required_steps", [])
        completed_steps = set(onboarding.get("completed_steps", []))

        payload = {
            "state_path": str(self.state_path),
            "schema_version": state["schema_version"],
            "app": state["app"],
            "repos": state["repos"],
            "integrations": state["integrations"],
            "projects": state["projects"],
            "active_projects": state["active_projects"],
            "project_automations": state["project_automations"],
            "events": state["events"],
            "runtime": state["runtime"],
            "summary": {
                "repo_count": len(state["repos"]),
                "integration_count": len(state["integrations"]),
                "project_count": len(state["projects"]),
                "active_project_count": len(state["active_projects"]),
                "project_automation_count": len(state["project_automations"]),
                "event_count": len(state["events"]),
                "component_count": len(state["runtime"]["components"]),
                "onboarding_completed": bool(required_steps)
                and all(step in completed_steps for step in required_steps),
            },
        }
        if repo_root is not None:
            payload["repo"] = self._repo_status(state, repo_root)
        return payload

    def _repo_status(self, state: dict[str, Any], repo_root: Path) -> dict[str, Any]:
        resolved = repo_root.expanduser().resolve()
        tracked = next((repo for repo in state["repos"] if repo["path"] == str(resolved)), None)
        return {
            "path": str(resolved),
            "tracked": tracked is not None,
            "initialized": self._repo_initialized(resolved),
            "record": tracked,
        }

    def _repo_initialized(self, repo_root: Path) -> bool:
        legacy_config = repo_root / ".codememory" / "config.json"
        renamed_config = repo_root / ".agentic-memory" / "config.json"
        return legacy_config.exists() or renamed_config.exists()

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = self._default_state()
        state.update(
            {
                "schema_version": payload.get("schema_version", state["schema_version"]),
                "app": {**state["app"], **payload.get("app", {})},
                "repos": list(payload.get("repos", [])),
                "integrations": list(payload.get("integrations", [])),
                "projects": list(payload.get("projects", [])),
                "active_projects": list(payload.get("active_projects", [])),
                "project_automations": list(payload.get("project_automations", [])),
                "events": list(payload.get("events", []))[-DEFAULT_EVENT_CAP:],
                "runtime": {**state["runtime"], **payload.get("runtime", {})},
            }
        )
        components = dict(state["runtime"].get("components", {}))
        for component, default_status in DEFAULT_COMPONENTS.items():
            record = components.get(component, {})
            components[component] = {
                "status": record.get("status", default_status),
                "details": record.get("details", {}),
                "updated_at": record.get("updated_at", _utc_now()),
            }
        state["runtime"]["components"] = components

        onboarding = dict(state["app"].get("onboarding", {}))
        onboarding["required_steps"] = list(onboarding.get("required_steps", DEFAULT_ONBOARDING_STEPS))
        onboarding["completed_steps"] = sorted(set(onboarding.get("completed_steps", [])))
        onboarding["updated_at"] = onboarding.get("updated_at", _utc_now())
        state["app"]["onboarding"] = onboarding
        state["app"]["updated_at"] = state["app"].get("updated_at", _utc_now())
        state["app"]["last_seen_at"] = state["app"].get("last_seen_at")
        return state

    def _touch_state(self, state: dict[str, Any]) -> dict[str, Any]:
        timestamp = _utc_now()
        state["app"]["last_seen_at"] = timestamp
        state["app"]["updated_at"] = timestamp
        return state

    def _update(self, mutate: Any) -> Any:
        state = self.load()
        result = mutate(state)
        self._write(state)
        return result

    def _write(self, state: dict[str, Any]) -> None:
        normalized = self._normalize(state)
        temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.state_path)
