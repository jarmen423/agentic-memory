from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from desktop_shell.app import app, get_backend_client


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = "ok"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("backend error")

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self) -> None:
        self.base_url = "http://127.0.0.1:8765"
        self.requests: list[tuple[str, dict | None]] = []
        self.posts: list[tuple[str, dict | None]] = []

    def request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> _FakeResponse:
        if method == "GET":
            self.requests.append((path, params))
            payload_by_path = {
                "/product/status": {
                    "state_path": "C:/Users/jfrie/.agentic-memory/product-state.json",
                    "summary": {"repo_count": 2},
                    "integrations": [],
                    "runtime": {"server": {"status": "healthy", "version": "0.1.0"}},
                },
                "/openclaw/metrics/summary": {
                    "status": "ok",
                    "summary": {"health_score": 92, "cards": []},
                    "request_metrics": [],
                    "error_metrics": [],
                },
                "/openclaw/health/detailed": {
                    "status": "ok",
                    "components": [{"component": "server", "status": "healthy", "details": {}}],
                    "request_metrics": [],
                    "error_metrics": [],
                    "summary": {"health_score": 92, "cards": []},
                },
                "/openclaw/search/recent": {
                    "status": "ok",
                    "recent_searches": [],
                    "summary": {"returned": 0, "limit": params.get("limit", 20) if params else 20},
                },
                "/openclaw/workspaces": {
                    "status": "ok",
                    "workspaces": [
                        {
                            "workspace_id": "workspace-acme",
                            "devices": [{"device_id": "laptop-01", "agents": []}],
                            "active_projects": [],
                            "automations": [],
                        }
                    ],
                    "summary": {"workspace_count": 1, "device_count": 1, "agent_count": 0},
                },
                "/openclaw/agents/openclaw-agent-a/sessions": {
                    "status": "ok",
                    "agent_id": "openclaw-agent-a",
                    "workspace_id": "workspace-acme",
                    "sessions": [],
                },
            }
            return _FakeResponse(payload_by_path[path])
        if method == "POST":
            self.posts.append((path, json))
            return _FakeResponse({"status": "ok", "echo": json or {}})
        raise AssertionError(f"Unexpected method: {method}")

    def close(self) -> None:
        return None


def test_index_serves_shell_markup():
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()
    assert "Agentic Memory" in response.text


def test_bootstrap_reports_backend_configuration(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("DESKTOP_SHELL_BACKEND_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("DESKTOP_SHELL_API_KEY", "secret")
    monkeypatch.setattr(
        "desktop_shell.app._fetch_backend_onboarding_contract",
        lambda settings: {
            "reachable": True,
            "status": "healthy",
            "error": None,
            "onboarding_contract": {
                "status": "ok",
                "plugin_package_name": "agentic-memory-openclaw",
                "plugin_id": "agentic-memory",
                "install_command": "openclaw plugin install agentic-memory-openclaw",
                "setup_command": "openclaw agentic-memory setup",
                "doctor_command": "openclaw agentic-memory doctor",
                "readiness": {
                    "setup_ready": True,
                    "capture_only_ready": True,
                    "augment_context_ready": False,
                    "required_healthy": 3,
                    "required_total": 3,
                    "optional_healthy": 1,
                    "optional_total": 5,
                    "blocking_services": [],
                    "degraded_optional_services": [],
                },
                "required_services": [],
                "optional_services": [],
                "notes": [],
            },
        },
    )

    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"]["url"] == "http://127.0.0.1:8765"
    assert body["backend"]["auth_configured"] is True
    assert body["backend"]["reachable"] is True
    assert body["backend"]["status"] == "healthy"
    assert body["onboarding"]["plugin_package_name"] == "agentic-memory-openclaw"
    assert body["onboarding"]["readiness"]["capture_only_ready"] is True


def test_bootstrap_reports_backend_probe_failure_without_crashing(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("DESKTOP_SHELL_BACKEND_URL", "http://127.0.0.1:9999")
    monkeypatch.delenv("DESKTOP_SHELL_API_KEY", raising=False)
    monkeypatch.setattr(
        "desktop_shell.app._fetch_backend_onboarding_contract",
        lambda settings: {
            "reachable": False,
            "status": "unreachable",
            "error": "Backend onboarding contract unavailable at http://127.0.0.1:9999.",
            "onboarding_contract": None,
        },
    )

    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"]["auth_configured"] is False
    assert body["backend"]["reachable"] is False
    assert body["backend"]["status"] == "unreachable"
    assert "Backend onboarding contract unavailable" in body["backend"]["error"]
    assert body["onboarding"] is None


def test_product_status_proxies_backend_response(monkeypatch):
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.get("/api/product/status")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["repo_count"] == 2
    assert fake_client.requests == [("/product/status", None)]


def test_dashboard_metrics_summary_proxies_backend_get():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.get("/api/openclaw/metrics/summary")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json()["summary"]["health_score"] == 92
    assert fake_client.requests == [("/openclaw/metrics/summary", None)]


def test_recent_searches_proxy_forwards_limit_query():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.get("/api/openclaw/search/recent?limit=12")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json()["summary"]["limit"] == 12
    assert fake_client.requests == [("/openclaw/search/recent", {"limit": 12})]


def test_agent_sessions_proxy_forwards_workspace_query():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.get("/api/openclaw/agents/openclaw-agent-a/sessions?workspace_id=workspace-acme")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json()["agent_id"] == "openclaw-agent-a"
    assert fake_client.requests == [
        ("/openclaw/agents/openclaw-agent-a/sessions", {"workspace_id": "workspace-acme"})
    ]


def test_workspaces_proxy_surfaces_workspace_tree():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.get("/api/openclaw/workspaces")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json()["summary"]["workspace_count"] == 1
    assert fake_client.requests == [("/openclaw/workspaces", None)]


def test_openclaw_session_registration_proxies_backend_post():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.post(
            "/api/openclaw/session/register",
            json={
                "workspace_id": "workspace-acme",
                "device_id": "laptop-01",
                "agent_id": "openclaw-agent-a",
                "session_id": "workspace-acme:laptop-01:openclaw-agent-a:desktop-shell",
                "context_engine": "legacy",
                "metadata": {"source": "desktop_shell"},
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert fake_client.posts == [
        (
            "/openclaw/session/register",
            {
                "workspace_id": "workspace-acme",
                "device_id": "laptop-01",
                "agent_id": "openclaw-agent-a",
                "session_id": "workspace-acme:laptop-01:openclaw-agent-a:desktop-shell",
                "context_engine": "legacy",
                "metadata": {"source": "desktop_shell"},
            },
        )
    ]


def test_openclaw_context_registration_proxies_backend_post():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.post(
            "/api/openclaw/session/register",
            json={
                "workspace_id": "workspace-acme",
                "device_id": "laptop-01",
                "agent_id": "openclaw-agent-a",
                "session_id": "workspace-acme:laptop-01:openclaw-agent-a:desktop-shell",
                "context_engine": "agentic-memory",
                "metadata": {"source": "desktop_shell"},
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert fake_client.posts == [
        (
            "/openclaw/session/register",
            {
                "workspace_id": "workspace-acme",
                "device_id": "laptop-01",
                "agent_id": "openclaw-agent-a",
                "session_id": "workspace-acme:laptop-01:openclaw-agent-a:desktop-shell",
                "context_engine": "agentic-memory",
                "metadata": {"source": "desktop_shell"},
            },
        )
    ]


def test_openclaw_context_resolution_proxies_backend_post():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.post(
            "/api/openclaw/context/resolve",
            json={
                "workspace_id": "workspace-acme",
                "device_id": "laptop-01",
                "agent_id": "openclaw-agent-a",
                "session_id": "workspace-acme:laptop-01:openclaw-agent-a:desktop-shell-verify",
                "query": "Verify shared OpenClaw memory connectivity from the desktop shell.",
                "limit": 3,
                "metadata": {"source": "desktop_shell", "probe": True},
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert fake_client.posts == [
        (
            "/openclaw/context/resolve",
            {
                "workspace_id": "workspace-acme",
                "device_id": "laptop-01",
                "agent_id": "openclaw-agent-a",
                "session_id": "workspace-acme:laptop-01:openclaw-agent-a:desktop-shell-verify",
                "query": "Verify shared OpenClaw memory connectivity from the desktop shell.",
                "limit": 3,
                "metadata": {"source": "desktop_shell", "probe": True},
            },
        )
    ]


def test_repo_upsert_proxies_backend_post():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.post(
            "/api/product/repos",
            json={"repo_path": "D:/code/demo", "label": "Demo", "metadata": {"source": "shell"}},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert fake_client.posts == [
        (
            "/product/repos",
            {"repo_path": "D:/code/demo", "label": "Demo", "metadata": {"source": "shell"}},
        )
    ]


def test_onboarding_proxies_backend_post():
    fake_client = _FakeClient()

    def override() -> _FakeClient:
        return fake_client

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.post(
            "/api/product/onboarding",
            json={"step": "repo_added", "completed": True},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert fake_client.posts == [
        ("/product/onboarding", {"step": "repo_added", "completed": True}),
    ]


def test_product_status_returns_503_when_backend_is_unreachable():
    class _UnavailableClient:
        """Simulate the desktop shell pointing at a backend port with no listener."""

        base_url = "http://127.0.0.1:8765"

        def request(
            self,
            method: str,
            path: str,
            json: dict | None = None,
            params: dict | None = None,
        ) -> _FakeResponse:
            request = httpx.Request(method, f"{self.base_url}{path}")
            raise httpx.ConnectError("[WinError 10061] Connection refused", request=request)

        def close(self) -> None:
            return None

    def override() -> _UnavailableClient:
        return _UnavailableClient()

    app.dependency_overrides = {}
    app.dependency_overrides[get_backend_client] = override

    try:
        client = TestClient(app)
        response = client.get("/api/product/status")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 503
    assert "Backend API unavailable" in response.json()["detail"]
    assert "http://127.0.0.1:8765" in response.json()["detail"]
