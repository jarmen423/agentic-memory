"""Tests for git graph ingestion parsing and checkpoint behavior."""

from unittest.mock import Mock, patch

import pytest

from codememory.ingestion.git_graph import (
    GitCommitRecord,
    GitFileChange,
    GitGraphIngestor,
    parse_name_status_output,
    parse_numstat_output,
)

pytestmark = [pytest.mark.unit]


def test_parse_git_show_outputs_smoke():
    """Parser handles normal, binary, and rename rows."""
    numstat = "\n".join(
        [
            "12\t4\tsrc/core.py",
            "-\t-\tassets/logo.png",
            "5\t1\told_name.py\tnew_name.py",
        ]
    )
    name_status = "\n".join(
        [
            "M\tsrc/core.py",
            "A\tassets/logo.png",
            "R100\told_name.py\tnew_name.py",
        ]
    )

    parsed_numstat = parse_numstat_output(numstat)
    parsed_status = parse_name_status_output(name_status)

    assert parsed_numstat["src/core.py"] == (12, 4)
    assert parsed_numstat["assets/logo.png"] == (0, 0)
    assert parsed_numstat["new_name.py"] == (5, 1)
    assert ("M", "src/core.py") in parsed_status
    assert ("A", "assets/logo.png") in parsed_status
    assert ("R", "new_name.py") in parsed_status


def test_sync_updates_checkpoint_after_incremental_path(tmp_path, monkeypatch):
    """Incremental sync writes updated checkpoint when commits are ingested."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    mock_driver = Mock()
    session = Mock()
    mock_driver.session.return_value.__enter__ = Mock(return_value=session)
    mock_driver.session.return_value.__exit__ = Mock(return_value=None)

    mock_config = Mock()
    mock_config.get_git_config.return_value = {
        "enabled": True,
        "auto_incremental": True,
        "sync_trigger": "commit",
        "github_enrichment": {"enabled": False, "repo": None},
        "checkpoint": {"last_sha": "old-sha"},
    }

    with patch("neo4j.GraphDatabase.driver", return_value=mock_driver):
        ingestor = GitGraphIngestor(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
            repo_root=repo_root,
            config=mock_config,
        )

    monkeypatch.setattr(ingestor, "_ensure_git_repo", Mock())
    monkeypatch.setattr(ingestor, "_ensure_constraints", Mock())
    monkeypatch.setattr(
        ingestor,
        "_repo_metadata",
        Mock(
            return_value={
                "repo_id": str(repo_root.resolve()),
                "root_path": str(repo_root.resolve()),
                "remote_url": None,
                "default_branch": "main",
            }
        ),
    )
    monkeypatch.setattr(ingestor, "_ensure_repo_node", Mock())
    monkeypatch.setattr(
        ingestor,
        "_resolve_commit_range",
        Mock(return_value=(["new-sha"], "new-sha", False)),
    )
    monkeypatch.setattr(
        ingestor,
        "_read_commit",
        Mock(
            return_value=GitCommitRecord(
                sha="new-sha",
                parent_count=1,
                authored_at="2026-01-01T00:00:00+00:00",
                committed_at="2026-01-01T00:00:00+00:00",
                author_name="Example",
                author_email="example@example.com",
                message_subject="subject",
                message_body="body",
                is_merge=False,
                touched_files=[
                    GitFileChange(path="src/core.py", change_type="M", additions=1, deletions=1)
                ],
            )
        ),
    )
    monkeypatch.setattr(ingestor, "_upsert_commit", Mock())
    monkeypatch.setattr(ingestor, "_maybe_github_enrich", Mock())

    result = ingestor.sync(full=False)

    assert result["checkpoint_before"] == "old-sha"
    assert result["checkpoint_after"] == "new-sha"
    assert result["commits_synced"] == 1
    mock_config.save_git_config.assert_called_once_with({"checkpoint": {"last_sha": "new-sha"}})
