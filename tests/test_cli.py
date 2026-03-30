"""Tests for CLI command behavior and JSON output contracts."""

import argparse
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from codememory import cli

pytestmark = [pytest.mark.unit]


def _result(payload):
    """Build a mock Neo4j result object with a single() payload."""
    result = Mock()
    result.single.return_value = payload
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
        "include_paths": [],
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


def test_index_loads_openai_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Index loads OPENAI_API_KEY from <repo>/.env before building the graph."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("OPENAI_API_KEY=from-index-dotenv\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    mock_cfg.get_openai_key.side_effect = lambda: os.getenv("OPENAI_API_KEY")
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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cli.cmd_index(argparse.Namespace(json=False, quiet=True))

    assert os.environ.get("OPENAI_API_KEY") == "from-index-dotenv"
    cli.KnowledgeGraphBuilder.assert_called_once_with(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        openai_key="from-index-dotenv",
        repo_root=repo_root,
        ignore_dirs=set(),
        ignore_files=set(),
        ignore_patterns=set(),
        include_paths=set(),
    )


def test_index_passes_include_paths_to_builder(monkeypatch, tmp_path):
    """Index command passes explicit include_paths from config to the builder."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(
        exists=True,
        indexing={
            "ignore_dirs": [],
            "ignore_files": [],
            "extensions": [".py"],
            "include_paths": ["systemd/AGENTS.md", "docs/runbooks/*.md"],
        },
    )
    mock_builder = Mock()
    mock_builder.run_pipeline.return_value = {
        "embedding_calls": 1,
        "cost_usd": 0.0,
    }

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))

    cli.cmd_index(argparse.Namespace(json=False, quiet=True))

    cli.KnowledgeGraphBuilder.assert_called_once_with(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        openai_key="test-openai-key",
        repo_root=repo_root,
        ignore_dirs=set(),
        ignore_files=set(),
        ignore_patterns=set(),
        include_paths={"systemd/AGENTS.md", "docs/runbooks/*.md"},
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


def test_search_loads_openai_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Search loads OPENAI_API_KEY from <repo>/.env before validating config."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("OPENAI_API_KEY=from-search-dotenv\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    mock_cfg.get_openai_key.side_effect = lambda: os.getenv("OPENAI_API_KEY")

    mock_builder = Mock()
    mock_builder.semantic_search.return_value = []

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))
    monkeypatch.setattr(cli, "KnowledgeGraphBuilder", Mock(return_value=mock_builder))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cli.cmd_search(argparse.Namespace(json=False, query="auth", limit=5))

    assert os.environ.get("OPENAI_API_KEY") == "from-search-dotenv"
    cli.KnowledgeGraphBuilder.assert_called_once_with(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        openai_key="from-search-dotenv",
    )
    mock_builder.semantic_search.assert_called_once_with("auth", limit=5)


def test_search_json_missing_openai_exits_nonzero(monkeypatch, capsys, tmp_path):
    """Search command exits non-zero when OpenAI key is unavailable."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_cfg = _mock_config(exists=True, openai_key=None)

    monkeypatch.setattr(cli, "find_repo_root", Mock(return_value=repo_root))
    monkeypatch.setattr(cli, "Config", Mock(return_value=mock_cfg))

    with pytest.raises(SystemExit) as exc:
        cli.cmd_search(argparse.Namespace(json=True, query="auth", limit=5))

    assert exc.value.code == 1
    payload = _parse_json_stdout(capsys)
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["metrics"] == {}
    assert "openai" in payload["error"].lower()


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
    monkeypatch.setitem(sys.modules, "codememory.server.app", fake_module)
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


def test_watch_loads_openai_key_from_repo_dotenv(monkeypatch, tmp_path):
    """Watch defaults to <repo>/.env when OPENAI_API_KEY is not already exported."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("OPENAI_API_KEY=from-watch-dotenv\n", encoding="utf-8")

    mock_cfg = Mock()
    mock_cfg.exists.return_value = True
    mock_cfg.get_neo4j_config.return_value = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    }
    mock_cfg.get_openai_key.side_effect = lambda: os.getenv("OPENAI_API_KEY")
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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cli.cmd_watch(argparse.Namespace(no_scan=False, env_file=None))

    assert os.environ.get("OPENAI_API_KEY") == "from-watch-dotenv"
    start_watch.assert_called_once_with(
        repo_path=repo_root,
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        openai_key="from-watch-dotenv",
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
