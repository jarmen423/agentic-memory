"""Tests for CLI command behavior and JSON output contracts."""

import argparse
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentic_memory import cli

pytestmark = [pytest.mark.unit]


def _result(payload):
    """Build a mock Neo4j result object with a single() payload."""
    result = Mock()
    result.single.return_value = payload
    return result


def _consume_result(properties_set=0):
    """Build a mock Neo4j result object with consume() counters."""
    result = Mock()
    summary = Mock()
    counters = Mock()
    counters.properties_set = properties_set
    summary.counters = counters
    result.consume.return_value = summary
    return result


def _parse_json_stdout(capsys):
    """Parse JSON output from stdout."""
    stdout = capsys.readouterr().out.strip()
    assert stdout, "expected JSON on stdout"
    return json.loads(stdout)


def _mock_config(
    *,
    exists=True,
    openai_key="test-openai-key",
    indexing=None,
    git_config=None,
    code_provider="gemini",
):
    """Create a mock Config object for CLI tests."""
    config = Mock()
    config.exists.return_value = exists
    config.config_file = Path("/tmp/repo/.codememory/config.json")
    config.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    config.get_openai_key.return_value = openai_key
    config.get_indexing_config.return_value = indexing or {
        "ignore_dirs": [],
        "ignore_files": [],
        "extensions": [".py"],
    }
    config.get_git_config.return_value = git_config or {
        "enabled": False,
        "auto_incremental": True,
        "sync_trigger": "commit",
        "github_enrichment": {"enabled": False, "repo": None},
        "checkpoint": {"last_sha": None},
    }
    config.save_git_config = Mock()
    config.get_graphignore_patterns.return_value = []
    code_model = (
        "text-embedding-3-large" if code_provider == "openai" else "gemini-embedding-2-preview"
    )
    provider_keys = {
        "openai": {"api_key": openai_key if code_provider == "openai" else None},
        "gemini": {"api_key": openai_key if code_provider == "gemini" else None},
        "nemotron": {"api_key": openai_key if code_provider == "nemotron" else None},
    }
    config.get_module_config.side_effect = lambda module_name: {
        "code": {
            "embedding_provider": code_provider,
            "embedding_model": code_model,
            "embedding_dimensions": 3072,
        },
        "web": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_dimensions": 3072,
        },
        "chat": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_dimensions": 3072,
        },
    }[module_name]
    config.get_embedding_provider_config.side_effect = (
        lambda provider_name: provider_keys.get(provider_name.strip().lower(), {})
    )
    return config


def test_status_json_success_envelope(monkeypatch, capsys, tmp_path):
    """Status command emits deterministic JSON envelope on success."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True)
    mock_builder = Mock()
    session = Mock()
    session_context = Mock()
    session_context.__enter__ = Mock(return_value=session)
    session_context.__exit__ = Mock(return_value=None)
    mock_builder.driver.session.return_value = session_context
    session.run.side_effect = [
        _result({"count": 3}),
        _result({"count": 7}),
        _result({"count": 2}),
        _result({"count": 11}),
        _result({"last_updated": "2026-02-01T00:00:00Z"}),
    ]

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))

    cli.cmd_status(argparse.Namespace(json=True))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["metrics"] == {}
    assert payload["data"]["repository"] == str(repo_root)
    assert payload["data"]["stats"] == {
        "files": 3,
        "functions": 7,
        "classes": 2,
        "chunks": 11,
        "last_sync": "2026-02-01T00:00:00Z",
    }


def test_status_json_missing_config_exits_nonzero(monkeypatch, capsys, tmp_path):
    """Status command exits non-zero for missing config in JSON mode."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=False)

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))

    with pytest.raises(SystemExit) as exc:
        cli.cmd_status(argparse.Namespace(json=True))

    assert exc.value.code == 1
    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["metrics"] == {}
    assert "not initialized" in payload["error"].lower()


def test_index_json_success_envelope(monkeypatch, capsys, tmp_path):
    """Index command emits deterministic JSON envelope on success."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True)
    mock_builder = Mock()
    mock_builder.run_pipeline.return_value = {
        "embedding_calls": 42,
        "cost_usd": 1.2345,
    }

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))

    cli.cmd_index(argparse.Namespace(json=True, quiet=False))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"] == {"repository": str(repo_root)}
    assert payload["metrics"] == {
        "embedding_calls": 42,
        "cost_usd": 1.2345,
    }


def test_index_loads_gemini_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Index loads GEMINI_API_KEY from <repo>/.env before building the graph."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("GEMINI_API_KEY=from-index-dotenv\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    mock_cfg.get_module_config.side_effect = lambda module_name: {
        "code": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_dimensions": 3072,
        }
    }[module_name]
    mock_cfg.get_embedding_provider_config.side_effect = (
        lambda provider_name: {"api_key": os.getenv("GEMINI_API_KEY")}
        if provider_name == "gemini"
        else {}
    )
    mock_cfg.get_indexing_config.return_value = {
        "ignore_dirs": [],
        "ignore_files": [],
        "extensions": [".py"],
    }
    mock_cfg.get_graphignore_patterns.return_value = []

    mock_builder = Mock()
    mock_builder.run_pipeline.return_value = {
        "embedding_calls": 1,
        "cost_usd": 0.0,
    }

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cli.cmd_index(argparse.Namespace(json=False, quiet=True))

    assert os.environ.get("GEMINI_API_KEY") == "from-index-dotenv"
    cli.KnowledgeGraphBuilder.assert_called_once_with(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        openai_key=None,
        config=mock_cfg,
        repo_root=repo_root,
        ignore_dirs=set(),
        ignore_files=set(),
        ignore_patterns=set(),
    )


def test_search_json_success_envelope(monkeypatch, capsys, tmp_path):
    """Search command emits deterministic JSON envelope on success."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True, openai_key="sk-test")
    mock_builder = Mock()
    mock_builder.semantic_search.return_value = [
        {"name": "foo", "score": 0.99, "text": "def foo(): ...", "sig": "foo.py:foo"}
    ]

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))

    cli.cmd_search(argparse.Namespace(json=True, query="auth", limit=5))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["query"] == "auth"
    assert payload["data"]["results"][0]["name"] == "foo"
    assert payload["metrics"] == {"result_count": 1}


def test_search_loads_gemini_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Search loads GEMINI_API_KEY from <repo>/.env before validating config."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("GEMINI_API_KEY=from-search-dotenv\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    mock_cfg.get_module_config.side_effect = lambda module_name: {
        "code": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_dimensions": 3072,
        }
    }[module_name]
    mock_cfg.get_embedding_provider_config.side_effect = (
        lambda provider_name: {"api_key": os.getenv("GEMINI_API_KEY")}
        if provider_name == "gemini"
        else {}
    )

    mock_builder = Mock()
    mock_builder.semantic_search.return_value = []

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cli.cmd_search(argparse.Namespace(json=False, query="auth", limit=5))

    assert os.environ.get("GEMINI_API_KEY") == "from-search-dotenv"
    cli.KnowledgeGraphBuilder.assert_called_once_with(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        openai_key=None,
        config=mock_cfg,
        repo_root=repo_root,
        ignore_dirs=None,
        ignore_files=None,
        ignore_patterns=None,
    )
    mock_builder.semantic_search.assert_called_once_with("auth", limit=5)


def test_search_json_missing_code_provider_key_exits_nonzero(monkeypatch, capsys, tmp_path):
    """Search command exits non-zero when the configured code provider key is unavailable."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True, openai_key=None)

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.cmd_search(argparse.Namespace(json=True, query="auth", limit=5))

    assert exc.value.code == 1
    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["metrics"] == {}
    assert "code embedding api key" in payload["error"].lower()


def test_deps_json_success_uses_graph_method(monkeypatch, capsys, tmp_path):
    """Deps command uses graph dependency method and returns JSON envelope."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True)
    mock_builder = Mock()
    mock_builder.get_file_dependencies.return_value = {
        "imports": ["src/a.py", "src/b.py"],
        "imported_by": ["src/c.py"],
    }

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))

    cli.cmd_deps(argparse.Namespace(json=True, path="src/main.py"))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["path"] == "src/main.py"
    assert payload["data"]["imports"] == ["src/a.py", "src/b.py"]
    assert payload["data"]["imported_by"] == ["src/c.py"]
    assert payload["metrics"] == {
        "imports_count": 2,
        "imported_by_count": 1,
    }
    mock_builder.get_file_dependencies.assert_called_once_with("src/main.py")


def test_impact_json_success_uses_graph_method(monkeypatch, capsys, tmp_path):
    """Impact command uses graph impact method and returns JSON envelope."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True)
    mock_builder = Mock()
    mock_builder.identify_impact.return_value = {
        "affected_files": [{"path": "src/caller.py", "depth": 1, "impact_type": "dependents"}],
        "total_count": 1,
    }

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))

    cli.cmd_impact(argparse.Namespace(json=True, path="src/main.py", max_depth=3))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["path"] == "src/main.py"
    assert payload["data"]["affected_files"][0]["path"] == "src/caller.py"
    assert payload["metrics"] == {"total_count": 1, "max_depth": 3}
    mock_builder.identify_impact.assert_called_once_with("src/main.py", max_depth=3)


def _patch_server_module(monkeypatch):
    """Inject a fake codememory.server.app module with a mock run_server."""
    run_server = Mock()
    fake_module = types.SimpleNamespace(run_server=run_server)
    monkeypatch.setitem(sys.modules, "agentic_memory.server.app", fake_module)
    return run_server


def test_serve_repo_path_resolution(monkeypatch, tmp_path):
    """Serve resolves and forwards explicit --repo path to run_server."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    run_server = _patch_server_module(monkeypatch)
    mock_cfg = _mock_config(exists=True)
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))

    cli.cmd_serve(
        argparse.Namespace(
            port=8123,
            repo=str(repo_root / "."),
            env_file=None,
        )
    )

    run_server.assert_called_once_with(port=8123, repo_root=repo_root.resolve())


def test_serve_invalid_repo_exits_nonzero(monkeypatch, tmp_path):
    """Serve exits non-zero when --repo does not exist."""
    run_server = _patch_server_module(monkeypatch)
    invalid_repo = tmp_path / "does-not-exist"

    with pytest.raises(SystemExit) as exc:
        cli.cmd_serve(
            argparse.Namespace(
                port=8000,
                repo=str(invalid_repo),
                env_file=None,
            )
        )

    assert exc.value.code == 1
    run_server.assert_not_called()


def test_serve_loads_openai_key_from_explicit_env_file(monkeypatch, tmp_path):
    """Serve loads OPENAI_API_KEY from --env-file before server start."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    env_file = tmp_path / "custom.env"
    env_file.write_text("OPENAI_API_KEY=from-explicit-env\n", encoding="utf-8")

    run_server = _patch_server_module(monkeypatch)
    mock_cfg = _mock_config(exists=True)
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cli.cmd_serve(
        argparse.Namespace(
            port=8000,
            repo=str(repo_root),
            env_file=str(env_file),
        )
    )

    assert os.environ.get("OPENAI_API_KEY") == "from-explicit-env"
    run_server.assert_called_once_with(port=8000, repo_root=repo_root.resolve())


def test_serve_loads_openai_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Serve defaults to <repo>/.env when --repo is provided and --env-file is omitted."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("OPENAI_API_KEY=from-repo-dotenv\n", encoding="utf-8")

    run_server = _patch_server_module(monkeypatch)
    mock_cfg = _mock_config(exists=True)
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cli.cmd_serve(
        argparse.Namespace(
            port=8000,
            repo=str(repo_root),
            env_file=None,
        )
    )

    assert os.environ.get("OPENAI_API_KEY") == "from-repo-dotenv"
    run_server.assert_called_once_with(port=8000, repo_root=repo_root.resolve())


def test_watch_loads_gemini_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Watch defaults to <repo>/.env when GEMINI_API_KEY is not already exported."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("GEMINI_API_KEY=from-watch-dotenv\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    mock_cfg.get_module_config.side_effect = lambda module_name: {
        "code": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_dimensions": 3072,
        }
    }[module_name]
    mock_cfg.get_embedding_provider_config.side_effect = (
        lambda provider_name: {"api_key": os.getenv("GEMINI_API_KEY")}
        if provider_name == "gemini"
        else {}
    )
    mock_cfg.get_indexing_config.return_value = {
        "ignore_dirs": [],
        "ignore_files": [],
        "extensions": [".py"],
    }
    mock_cfg.get_graphignore_patterns.return_value = []

    start_watch = Mock()
    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "start_continuous_watch", start_watch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cli.cmd_watch(argparse.Namespace(no_scan=False, env_file=None))

    assert os.environ.get("GEMINI_API_KEY") == "from-watch-dotenv"
    start_watch.assert_called_once_with(
        repo_path=repo_root,
        config=mock_cfg,
        ignore_dirs=set(),
        ignore_files=set(),
        ignore_patterns=set(),
        supported_extensions={".py"},
        initial_scan=True,
    )


def test_git_init_json_success_envelope(monkeypatch, capsys, tmp_path):
    """git-init emits standard JSON envelope and enables git config."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True)
    mock_cfg.get_git_config.side_effect = [
        {
            "enabled": False,
            "auto_incremental": True,
            "sync_trigger": "commit",
            "github_enrichment": {"enabled": False, "repo": None},
            "checkpoint": {"last_sha": None},
        },
        {
            "enabled": True,
            "auto_incremental": True,
            "sync_trigger": "commit",
            "github_enrichment": {"enabled": False, "repo": None},
            "checkpoint": {"last_sha": None},
        },
    ]
    mock_ingestor = Mock()
    mock_ingestor.initialize.return_value = {
        "repo_id": str(repo_root.resolve()),
        "root_path": str(repo_root.resolve()),
        "remote_url": None,
        "default_branch": "main",
    }

    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "GitGraphIngestor", Mock(return_value=mock_ingestor))

    cli.cmd_git_init(argparse.Namespace(json=True, repo=str(repo_root)))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["metrics"] == {}
    assert payload["data"]["repository"] == str(repo_root.resolve())
    assert payload["data"]["git"]["enabled"] is True
    mock_cfg.save_git_config.assert_called_once_with({"enabled": True})
    mock_ingestor.close.assert_called_once()


def test_git_init_loads_repo_dotenv_for_env_backed_neo4j_config(monkeypatch, tmp_path):
    """git-init loads env-backed Neo4j config from <repo>/.env when --repo is used."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("NEO4J_URI=bolt://from-dotenv:7687\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_git_config.side_effect = [
        {"enabled": False, "auto_incremental": True, "sync_trigger": "commit", "checkpoint": {}},
        {"enabled": True, "auto_incremental": True, "sync_trigger": "commit", "checkpoint": {}},
    ]
    mock_cfg.get_neo4j_config.side_effect = lambda: {
        "uri": os.getenv("NEO4J_URI"),
        "user": "neo4j",
        "password": "password",
    }
    mock_ingestor = Mock()
    mock_ingestor.initialize.return_value = {
        "repo_id": str(repo_root.resolve()),
        "root_path": str(repo_root.resolve()),
        "remote_url": None,
        "default_branch": "main",
    }

    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "GitGraphIngestor", Mock(return_value=mock_ingestor))
    monkeypatch.delenv("NEO4J_URI", raising=False)

    cli.cmd_git_init(argparse.Namespace(json=False, repo=str(repo_root)))

    assert os.environ.get("NEO4J_URI") == "bolt://from-dotenv:7687"
    cli.GitGraphIngestor.assert_called_once_with(
        uri="bolt://from-dotenv:7687",
        user="neo4j",
        password="password",
        repo_root=repo_root.resolve(),
        config=mock_cfg,
    )


def test_git_sync_json_success_envelope(monkeypatch, capsys, tmp_path):
    """git-sync emits JSON envelope with sync metrics."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(
        exists=True,
        git_config={
            "enabled": True,
            "auto_incremental": True,
            "sync_trigger": "commit",
            "github_enrichment": {"enabled": False, "repo": None},
            "checkpoint": {"last_sha": "abc"},
        },
    )
    mock_ingestor = Mock()
    mock_ingestor.sync.return_value = {
        "repo_id": str(repo_root.resolve()),
        "head_sha": "def",
        "checkpoint_before": "abc",
        "checkpoint_after": "def",
        "full": False,
        "checkpoint_reset": False,
        "commits_seen": 1,
        "commits_synced": 1,
    }

    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "GitGraphIngestor", Mock(return_value=mock_ingestor))

    cli.cmd_git_sync(argparse.Namespace(json=True, repo=str(repo_root), full=False))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["repository"] == str(repo_root.resolve())
    assert payload["data"]["sync"]["checkpoint_after"] == "def"
    assert payload["metrics"] == {
        "commits_seen": 1,
        "commits_synced": 1,
        "checkpoint_reset": False,
    }
    mock_ingestor.sync.assert_called_once_with(full=False)
    mock_ingestor.close.assert_called_once()


def test_git_status_json_success_envelope(monkeypatch, capsys, tmp_path):
    """git-status emits JSON envelope with status and pending commit metric."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(
        exists=True,
        git_config={
            "enabled": True,
            "auto_incremental": True,
            "sync_trigger": "commit",
            "github_enrichment": {"enabled": False, "repo": None},
            "checkpoint": {"last_sha": "abc"},
        },
    )
    mock_ingestor = Mock()
    mock_ingestor.status.return_value = {
        "repo_id": str(repo_root.resolve()),
        "repo_path": str(repo_root.resolve()),
        "enabled": True,
        "checkpoint_sha": "abc",
        "head_sha": "def",
        "pending_commits": 2,
        "graph": {
            "repo_node_exists": True,
            "commit_count": 10,
            "author_count": 3,
            "file_version_count": 20,
        },
    }

    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "GitGraphIngestor", Mock(return_value=mock_ingestor))

    cli.cmd_git_status(argparse.Namespace(json=True, repo=str(repo_root)))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["status"]["checkpoint_sha"] == "abc"
    assert payload["metrics"] == {"pending_commits": 2}
    mock_ingestor.close.assert_called_once()


def test_product_status_json_success_envelope(monkeypatch, capsys, tmp_path):
    """product-status emits the standard JSON envelope with summary metrics."""
    state_path = tmp_path / "product-state.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))

    cli.cmd_product_status(argparse.Namespace(json=True, repo=None))

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["state_path"] == str(state_path)
    assert payload["metrics"]["repo_count"] == 0


def test_product_repo_add_json_tracks_initialized_repo(monkeypatch, capsys, tmp_path):
    """product-repo-add registers the repo and returns it in JSON mode."""
    state_path = tmp_path / "product-state.json"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    codememory_dir = repo_root / ".codememory"
    codememory_dir.mkdir()
    (codememory_dir / "config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))

    cli.cmd_product_repo_add(
        argparse.Namespace(
            json=True,
            path=str(repo_root),
            label="Dogfood Repo",
            metadata_json='{"tier":"alpha"}',
        )
    )

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["data"]["repo"]["label"] == "Dogfood Repo"
    assert payload["data"]["repo"]["initialized"] is True
    assert payload["metrics"]["repo_count"] == 1


def test_product_integration_set_json_updates_record(monkeypatch, capsys, tmp_path):
    """product-integration-set persists integration state and returns JSON."""
    state_path = tmp_path / "product-state.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))

    cli.cmd_product_integration_set(
        argparse.Namespace(
            json=True,
            surface="mcp",
            target="claude_desktop",
            status="configured",
            config_json='{"command":"codememory"}',
            last_error=None,
        )
    )

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["data"]["integration"]["surface"] == "mcp"
    assert payload["data"]["integration"]["config"]["command"] == "codememory"
    assert payload["metrics"]["integration_count"] == 1


def test_openclaw_setup_writes_config_and_updates_product_state(monkeypatch, capsys, tmp_path):
    """openclaw-setup writes capture-first config with lightweight defaults."""
    state_path = tmp_path / "product-state.json"
    config_path = tmp_path / ".openclaw" / "agentic-memory.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))
    monkeypatch.setenv("COMPUTERNAME", "TEST-LAPTOP")
    monkeypatch.setenv("USERNAME", "Jordan")

    cli.cmd_openclaw_setup(
        argparse.Namespace(
            json=True,
            workspace_id="workspace-acme",
            device_id=None,
            agent_id=None,
            session_id=None,
            backend_url="http://127.0.0.1:8765",
            api_key_env="AGENTIC_MEMORY_API_KEY",
            config_path=str(config_path),
            enable_context_augmentation=False,
            enable_context_engine=False,
        )
    )

    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["data"]["config_path"] == str(config_path)
    assert payload["data"]["config"]["plugins"]["slots"]["memory"] == "agentic-memory"
    assert payload["data"]["config"]["plugins"]["slots"]["contextEngine"] == "agentic-memory"
    assert (
        payload["data"]["config"]["plugins"]["entries"]["agentic-memory"]["config"]["apiKey"]
        == "${AGENTIC_MEMORY_API_KEY}"
    )
    assert (
        payload["data"]["config"]["plugins"]["entries"]["agentic-memory"]["config"]["mode"]
        == "capture_only"
    )
    assert "projectId" not in payload["data"]["config"]["plugins"]["entries"]["agentic-memory"]["config"]
    assert payload["data"]["memory_integration"]["surface"] == "openclaw_memory"
    assert payload["data"]["context_integration"] is None
    assert payload["data"]["event"]["event_type"] == "openclaw_setup_completed"
    assert payload["metrics"]["config_written"] is True
    assert payload["metrics"]["context_augmentation_enabled"] is False
    assert payload["data"]["memory_integration"]["config"]["device_id"] == "TEST-LAPTOP"
    assert payload["data"]["memory_integration"]["config"]["agent_id"] == "claw-jordan"
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved_config["plugins"]["entries"]["agentic-memory"]["config"]["mode"] == "capture_only"


def test_help_uses_agentic_memory_as_primary_command(capsys):
    """CLI help text advertises the broader product command name first."""
    import unittest.mock as _mock

    with _mock.patch("sys.argv", ["agentic-memory", "--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "agentic-memory init" in out
    assert "Legacy alias still supported: codememory" in out


def test_pyproject_registers_agentic_memory_console_script():
    """Packaging metadata exposes the new primary CLI alias."""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'agentic-memory = "agentic_memory.cli:main"' in pyproject


def test_agentic_memory_namespace_imports_cli():
    """The new public namespace exposes the CLI entrypoint."""
    from agentic_memory.cli import main as renamed_main

    assert renamed_main is cli.main


# ---------------------------------------------------------------------------
# Stub command tests (Phase 2 / Phase 4 placeholders)
# ---------------------------------------------------------------------------


def test_web_init_calls_setup_database_on_connection(monkeypatch, capsys):
    """web-init calls ConnectionManager.setup_database() when connection succeeds."""
    from unittest.mock import Mock, patch

    mock_conn = Mock()
    with patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)):
        cli.cmd_web_init(argparse.Namespace())

    mock_conn.setup_database.assert_called_once()
    out = capsys.readouterr().out
    assert "ready" in out.lower()


def test_web_ingest_prints_not_implemented_and_exits_zero(capsys):
    """web-ingest with no URL argument exits 1 with missing URL message."""
    with pytest.raises(SystemExit) as exc:
        cli.cmd_web_ingest(argparse.Namespace(url=None))
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "URL argument required" in out or "url" in out.lower() or "argument" in out.lower()


def test_web_search_prints_not_implemented_and_exits_zero(capsys):
    """web-search prints stub message and exits 0."""
    with pytest.raises(SystemExit) as exc:
        cli.cmd_web_search(argparse.Namespace())
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Not yet implemented" in out


def test_chat_init_calls_setup_and_fix_dimensions(monkeypatch, capsys):
    """chat-init calls setup_database() and fix_vector_index_dimensions()."""
    from unittest.mock import Mock, patch

    mock_conn = Mock()
    mock_conn_class = Mock(return_value=mock_conn)

    with patch("agentic_memory.core.connection.ConnectionManager", mock_conn_class):
        cli.cmd_chat_init(argparse.Namespace())

    mock_conn.setup_database.assert_called_once()
    mock_conn.fix_vector_index_dimensions.assert_called_once()
    out = capsys.readouterr().out
    assert "chat-init" in out


def test_chat_ingest_requires_project_id(capsys):
    """chat-ingest exits non-zero when --project-id is missing (argparse enforcement)."""
    import unittest.mock as _mock

    with _mock.patch("sys.argv", ["codememory", "chat-ingest"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    # argparse exits 2 for missing required args — this confirms --project-id is enforced
    assert exc.value.code == 2


def test_stub_commands_are_registered_in_parser():
    """Web and chat commands are registered in the argument parser (exit code != 2)."""
    import unittest.mock as _mock
    from unittest.mock import Mock, patch

    # Commands that can be invoked without required args — exit != 2 means registered.
    # Commands with required args are invoked below with minimal valid placeholders.
    # chat-ingest is excluded: it requires --project-id, so argparse exits 2 by design.
    mock_conn = Mock()
    mock_session = Mock()
    mock_conn.session.return_value.__enter__ = Mock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = Mock(return_value=None)
    mock_session.run.return_value = _consume_result()
    registered_commands = ["web-init", "web-ingest", "web-search", "migrate-temporal", "chat-init"]
    for cmd in registered_commands:
        try:
            with _mock.patch("sys.argv", ["codememory", cmd]), \
                 patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)):
                cli.main()
            # No exception = command ran and returned normally (fine)
        except SystemExit as exc:
            # 2 = argparse "unrecognized command" — anything else means it's registered
            assert exc.code != 2, (
                f"Command '{cmd}' exited with code {exc.code} — likely not registered"
            )

    commands_with_args = [
        ["web-schedule", "--template", "Research {topic}", "--variables", "topic", "--cron", "0 9 * * 1", "--project-id", "proj1"],
        ["web-run-research", "--project-id", "proj1", "--template", "Research {topic}", "--variables", "topic"],
    ]
    for argv in commands_with_args:
        try:
            with _mock.patch("sys.argv", ["codememory", *argv]), \
                 patch.object(cli, "_resolve_scheduler_dependencies", Mock(side_effect=SystemExit(0))):
                cli.main()
        except SystemExit as exc:
            assert exc.code != 2, (
                f"Command '{argv[0]}' exited with code {exc.code} — likely not registered"
            )


# ---------------------------------------------------------------------------
# Web CLI tests (Phase 2 implementations)
# ---------------------------------------------------------------------------


def test_web_init_calls_setup_database(monkeypatch, capsys):
    """web-init calls ConnectionManager.setup_database() and prints 'ready'."""
    from unittest.mock import Mock, patch

    mock_conn = Mock()
    mock_conn_class = Mock(return_value=mock_conn)

    with patch("agentic_memory.core.connection.ConnectionManager", mock_conn_class):
        cli.cmd_web_init(argparse.Namespace())

    mock_conn.setup_database.assert_called_once()
    out = capsys.readouterr().out
    assert "ready" in out.lower()


def test_web_ingest_calls_pipeline(monkeypatch, capsys):
    """web-ingest URL crawls via crawl_url and calls pipeline.ingest() with format='markdown'."""
    from unittest.mock import Mock, patch

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    mock_conn = Mock()
    mock_embedder = Mock()
    mock_extractor = Mock()
    mock_pipeline = Mock()

    captured_source = {}

    def capture_ingest(source):
        captured_source.update(source)
        return {"chunks": 2, "type": "report"}

    mock_pipeline.ingest.side_effect = capture_ingest

    async def fake_crawl_url(url, timeout_ms=30000):
        return "# Test Page\nSome content here."

    with patch("agentic_memory.web.crawler.crawl_url", fake_crawl_url), \
         patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)), \
         patch("agentic_memory.core.runtime_embedding.build_embedding_service", Mock(return_value=mock_embedder)), \
         patch("agentic_memory.core.entity_extraction.EntityExtractionService", Mock(return_value=mock_extractor)), \
         patch("agentic_memory.web.pipeline.ResearchIngestionPipeline", Mock(return_value=mock_pipeline)):

        cli.cmd_web_ingest(argparse.Namespace(url="https://example.com"))

    mock_pipeline.ingest.assert_called_once()
    assert captured_source["format"] == "markdown"
    assert captured_source["type"] == "report"


def test_web_ingest_pdf_format_detection(monkeypatch, capsys):
    """web-ingest with .pdf path sets format='pdf' and does NOT call crawl_url."""
    from unittest.mock import Mock, patch

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    mock_conn = Mock()
    mock_embedder = Mock()
    mock_extractor = Mock()
    mock_pipeline = Mock()

    captured_source = {}

    def capture_ingest(source):
        captured_source.update(source)
        return {"chunks": 1, "type": "report"}

    mock_pipeline.ingest.side_effect = capture_ingest

    crawl_url_spy = Mock()

    with patch("agentic_memory.web.crawler.crawl_url", crawl_url_spy), \
         patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)), \
         patch("agentic_memory.core.runtime_embedding.build_embedding_service", Mock(return_value=mock_embedder)), \
         patch("agentic_memory.core.entity_extraction.EntityExtractionService", Mock(return_value=mock_extractor)), \
         patch("agentic_memory.web.pipeline.ResearchIngestionPipeline", Mock(return_value=mock_pipeline)), \
         patch("os.path.isfile", return_value=True):

        cli.cmd_web_ingest(argparse.Namespace(url="/some/path/doc.pdf"))

    mock_pipeline.ingest.assert_called_once()
    assert captured_source["format"] == "pdf"
    assert captured_source.get("path") == "/some/path/doc.pdf"
    crawl_url_spy.assert_not_called()


def test_web_ingest_pdf_url_detection(monkeypatch, capsys):
    """web-ingest with URL ending in .pdf detects format='pdf'."""
    from unittest.mock import Mock, patch

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    mock_conn = Mock()
    mock_embedder = Mock()
    mock_extractor = Mock()
    mock_pipeline = Mock()

    captured_source = {}

    def capture_ingest(source):
        captured_source.update(source)
        return {"chunks": 1, "type": "report"}

    mock_pipeline.ingest.side_effect = capture_ingest

    mock_httpx_resp = Mock()
    mock_httpx_resp.raise_for_status = Mock()
    mock_httpx_resp.content = b"%PDF fake content"

    with patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)), \
         patch("agentic_memory.core.runtime_embedding.build_embedding_service", Mock(return_value=mock_embedder)), \
         patch("agentic_memory.core.entity_extraction.EntityExtractionService", Mock(return_value=mock_extractor)), \
         patch("agentic_memory.web.pipeline.ResearchIngestionPipeline", Mock(return_value=mock_pipeline)), \
         patch("httpx.get", Mock(return_value=mock_httpx_resp)), \
         patch("os.path.isfile", return_value=False):

        cli.cmd_web_ingest(argparse.Namespace(url="https://example.com/report.pdf"))

    mock_pipeline.ingest.assert_called_once()
    assert captured_source["format"] == "pdf"


def test_web_ingest_missing_embedding_key_exits_1(monkeypatch, capsys):
    """web-ingest exits with code 1 when no embedding-provider key can be resolved."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    with pytest.raises(SystemExit) as exc:
        cli.cmd_web_ingest(argparse.Namespace(url="https://example.com"))

    assert exc.value.code == 1


def test_web_search_stub_prints_not_implemented(capsys):
    """web-search prints 'Not yet implemented' stub message."""
    with pytest.raises(SystemExit) as exc:
        cli.cmd_web_search(argparse.Namespace())
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Not yet implemented" in out


def test_web_schedule_calls_scheduler(capsys):
    """web-schedule instantiates ResearchScheduler and prints the new schedule id."""
    from unittest.mock import Mock, patch

    mock_pipeline = Mock()
    mock_pipeline._conn = Mock()
    mock_scheduler = Mock()
    mock_scheduler.create_schedule.return_value = "sched-1"

    with patch.object(
        cli,
        "_resolve_scheduler_dependencies",
        Mock(return_value=(mock_pipeline, "groq-key", "brave-key")),
    ), patch("agentic_memory.core.scheduler.ResearchScheduler", Mock(return_value=mock_scheduler)):
        cli.cmd_web_schedule(
            argparse.Namespace(
                template="Research {topic}",
                variables=["topic"],
                cron_expr="0 9 * * 1",
                project_id="proj1",
                max_runs_per_day=5,
            )
        )

    mock_scheduler.create_schedule.assert_called_once_with(
        template="Research {topic}",
        variables=["topic"],
        cron_expr="0 9 * * 1",
        project_id="proj1",
        max_runs_per_day=5,
    )
    mock_scheduler.close.assert_called_once()
    out = capsys.readouterr().out
    assert "sched-1" in out


def test_web_run_research_calls_scheduler_for_ad_hoc_run(capsys):
    """web-run-research supports ad hoc execution without a schedule id."""
    from unittest.mock import Mock, patch

    mock_pipeline = Mock()
    mock_pipeline._conn = Mock()
    mock_scheduler = Mock()
    mock_scheduler.run_research_session.return_value = {
        "status": "ok",
        "results": 1,
        "query": "Research AI agents",
    }

    with patch.object(
        cli,
        "_resolve_scheduler_dependencies",
        Mock(return_value=(mock_pipeline, "groq-key", "brave-key")),
    ), patch("agentic_memory.core.scheduler.ResearchScheduler", Mock(return_value=mock_scheduler)):
        cli.cmd_web_run_research(
            argparse.Namespace(
                schedule_id=None,
                project_id="proj1",
                template="Research {topic}",
                variables=["topic"],
            )
        )

    mock_scheduler.run_research_session.assert_called_once_with(
        schedule_id=None,
        ad_hoc_template="Research {topic}",
        ad_hoc_variables=["topic"],
        project_id="proj1",
    )
    mock_scheduler.close.assert_called_once()
    out = capsys.readouterr().out
    assert '"status": "ok"' in out


def test_resolve_scheduler_dependencies_uses_web_embedding_runtime(monkeypatch):
    """Scheduler dependency builder resolves the web embedder via shared runtime config."""
    from unittest.mock import Mock, patch

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave-key")

    mock_conn = Mock()
    mock_embedder = Mock()
    mock_extractor = Mock()
    mock_pipeline = Mock()

    with patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)), \
         patch("agentic_memory.core.runtime_embedding.build_embedding_service", Mock(return_value=mock_embedder)) as build_embedder, \
         patch("agentic_memory.core.entity_extraction.EntityExtractionService", Mock(return_value=mock_extractor)), \
         patch("agentic_memory.web.pipeline.ResearchIngestionPipeline", Mock(return_value=mock_pipeline)):
        pipeline, extraction_llm, brave_api_key = cli._resolve_scheduler_dependencies()

    assert pipeline is mock_pipeline
    assert extraction_llm.api_key == "test-groq-key"
    assert brave_api_key == "test-brave-key"
    build_embedder.assert_called_once_with("web")


def test_migrate_temporal_runs_all_backfill_statements(capsys):
    """migrate-temporal executes the full ordered backfill and prints a summary."""
    from unittest.mock import Mock, patch

    mock_conn = Mock()
    mock_session = Mock()
    mock_conn.session.return_value.__enter__ = Mock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = Mock(return_value=None)
    mock_session.run.return_value = _consume_result(properties_set=5)

    with patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)):
        cli.cmd_migrate_temporal(argparse.Namespace())

    assert mock_session.run.call_count == 14
    out = capsys.readouterr().out
    assert "migrate-temporal: ABOUT backfill complete" in out
    assert "14 relationship types processed" in out


def test_migrate_temporal_handles_unavailable_neo4j(capsys):
    """migrate-temporal exits non-zero with a clear message on connection failure."""
    from unittest.mock import Mock, patch

    mock_conn = Mock()
    mock_session = Mock()
    mock_conn.session.return_value.__enter__ = Mock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = Mock(return_value=None)
    mock_session.run.side_effect = cli.neo4j.exceptions.ServiceUnavailable("down")

    with patch("agentic_memory.core.connection.ConnectionManager", Mock(return_value=mock_conn)):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_migrate_temporal(argparse.Namespace())

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Neo4j unavailable" in out
