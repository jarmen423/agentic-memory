from __future__ import annotations

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
        self.requests: list[str] = []
        self.posts: list[tuple[str, dict | None]] = []

    def request(self, method: str, path: str, json: dict | None = None) -> _FakeResponse:
        if method == "GET":
            self.requests.append(path)
            return _FakeResponse(
                {
                    "state_path": "C:/Users/jfrie/.agentic-memory/product-state.json",
                    "summary": {"repo_count": 2},
                    "integrations": [],
                    "runtime": {"server": {"status": "healthy", "version": "0.1.0"}},
                }
            )
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
    assert "Agentic Memory Desktop" in response.text


def test_bootstrap_reports_backend_configuration(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("DESKTOP_SHELL_BACKEND_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("DESKTOP_SHELL_API_KEY", "secret")

    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"]["url"] == "http://127.0.0.1:8765"
    assert body["backend"]["auth_configured"] is True


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
    assert fake_client.requests == ["/product/status"]


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
