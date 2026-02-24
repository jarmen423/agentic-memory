"""Git history ingestion into Neo4j for optional provenance graph support."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import neo4j

from codememory.config import Config

logger = logging.getLogger(__name__)
_FIELD_SEP = "\x1f"


@dataclass(frozen=True)
class GitFileChange:
    """A file touched in a commit with basic diff stats."""

    path: str
    change_type: str
    additions: int
    deletions: int


@dataclass(frozen=True)
class GitCommitRecord:
    """Commit metadata and touched files parsed from local git history."""

    sha: str
    parent_count: int
    authored_at: str
    committed_at: str
    author_name: str
    author_email: str
    message_subject: str
    message_body: str
    is_merge: bool
    touched_files: list[GitFileChange]


def parse_numstat_output(output: str) -> dict[str, tuple[int, int]]:
    """Parse `git show --numstat` output into path -> (additions, deletions)."""
    stats: dict[str, tuple[int, int]] = {}
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if len(parts) < 3:
            continue
        additions_raw, deletions_raw = parts[0], parts[1]
        path = parts[-1].strip()
        if not path:
            continue
        additions = int(additions_raw) if additions_raw.isdigit() else 0
        deletions = int(deletions_raw) if deletions_raw.isdigit() else 0
        stats[path.replace("\\", "/")] = (additions, deletions)
    return stats


def parse_name_status_output(output: str) -> list[tuple[str, str]]:
    """Parse `git show --name-status` output into (change_type, path)."""
    rows: list[tuple[str, str]] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if len(parts) < 2:
            continue
        status_token = parts[0].strip()
        change_type = status_token[:1] if status_token else "M"
        if change_type in {"R", "C"} and len(parts) >= 3:
            path = parts[2].strip()
        else:
            path = parts[1].strip()
        if not path:
            continue
        rows.append((change_type, path.replace("\\", "/")))
    return rows


class GitGraphIngestor:
    """Sync local git history into dedicated Git* labels in Neo4j."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        repo_root: Path,
        config: Config,
    ):
        self.repo_root = repo_root.resolve()
        self.repo_id = str(self.repo_root)
        self.config = config
        self.driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        """Close database connection."""
        self.driver.close()

    def initialize(self) -> dict[str, Any]:
        """Ensure schema and create/update GitRepo node for the current repository."""
        self._ensure_git_repo()
        self._ensure_constraints()
        repo_meta = self._repo_metadata()
        self._ensure_repo_node(repo_meta)
        return repo_meta

    def sync(self, *, full: bool = False) -> dict[str, Any]:
        """Run full or incremental commit sync and update checkpoint."""
        self._ensure_git_repo()
        self._ensure_constraints()
        repo_meta = self._repo_metadata()
        self._ensure_repo_node(repo_meta)

        git_cfg = self.config.get_git_config()
        checkpoint_before = git_cfg.get("checkpoint", {}).get("last_sha")
        commit_shas, head_sha, checkpoint_reset = self._resolve_commit_range(
            full=full,
            checkpoint_sha=checkpoint_before,
        )

        commits_synced = 0
        for sha in commit_shas:
            commit = self._read_commit(sha)
            self._upsert_commit(repo_meta, commit)
            self._maybe_github_enrich(commit)
            commits_synced += 1

        checkpoint_after = checkpoint_before
        if full:
            checkpoint_after = head_sha
        elif commit_shas:
            checkpoint_after = commit_shas[-1]
        elif checkpoint_before is None and head_sha:
            checkpoint_after = head_sha

        if checkpoint_after != checkpoint_before:
            self.config.save_git_config({"checkpoint": {"last_sha": checkpoint_after}})

        return {
            "repo_id": self.repo_id,
            "head_sha": head_sha,
            "checkpoint_before": checkpoint_before,
            "checkpoint_after": checkpoint_after,
            "full": full,
            "checkpoint_reset": checkpoint_reset,
            "commits_seen": len(commit_shas),
            "commits_synced": commits_synced,
        }

    def status(self) -> dict[str, Any]:
        """Return sync checkpoint and graph presence status for this repository."""
        self._ensure_git_repo()
        git_cfg = self.config.get_git_config()
        checkpoint_sha = git_cfg.get("checkpoint", {}).get("last_sha")
        head_sha = self._head_sha()

        pending_commits = 0
        if head_sha:
            if (
                checkpoint_sha
                and self._commit_exists(checkpoint_sha)
                and self._is_ancestor(checkpoint_sha)
            ):
                pending_commits = len(self._rev_list(f"{checkpoint_sha}..HEAD"))
            else:
                pending_commits = len(self._rev_list())

        with self.driver.session() as session:
            repo_count = session.run(
                "MATCH (r:GitRepo {repo_id: $repo_id}) RETURN count(r) AS count",
                repo_id=self.repo_id,
            ).single()["count"]
            commit_count = session.run(
                "MATCH (c:GitCommit {repo_id: $repo_id}) RETURN count(c) AS count",
                repo_id=self.repo_id,
            ).single()["count"]
            author_count = session.run(
                "MATCH (a:GitAuthor {repo_id: $repo_id}) RETURN count(a) AS count",
                repo_id=self.repo_id,
            ).single()["count"]
            file_version_count = session.run(
                "MATCH (fv:GitFileVersion {repo_id: $repo_id}) RETURN count(fv) AS count",
                repo_id=self.repo_id,
            ).single()["count"]

        return {
            "repo_id": self.repo_id,
            "repo_path": str(self.repo_root),
            "enabled": bool(git_cfg.get("enabled")),
            "checkpoint_sha": checkpoint_sha,
            "head_sha": head_sha,
            "pending_commits": pending_commits,
            "graph": {
                "repo_node_exists": bool(repo_count),
                "commit_count": commit_count,
                "author_count": author_count,
                "file_version_count": file_version_count,
            },
        }

    def _ensure_constraints(self) -> None:
        queries = [
            "CREATE CONSTRAINT git_repo_id_unique IF NOT EXISTS FOR (r:GitRepo) REQUIRE r.repo_id IS UNIQUE",
            (
                "CREATE CONSTRAINT git_commit_repo_sha_unique IF NOT EXISTS "
                "FOR (c:GitCommit) REQUIRE (c.repo_id, c.sha) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT git_author_repo_email_unique IF NOT EXISTS "
                "FOR (a:GitAuthor) REQUIRE (a.repo_id, a.email_norm) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT git_file_version_unique IF NOT EXISTS "
                "FOR (fv:GitFileVersion) REQUIRE (fv.repo_id, fv.sha, fv.path) IS UNIQUE"
            ),
        ]
        with self.driver.session() as session:
            for query in queries:
                session.run(query)

    def _repo_metadata(self) -> dict[str, Any]:
        remote_url = self._git("remote", "get-url", "origin", check=False).stdout.strip() or None
        default_branch = self._git("branch", "--show-current", check=False).stdout.strip() or None
        return {
            "repo_id": self.repo_id,
            "root_path": str(self.repo_root),
            "remote_url": remote_url,
            "default_branch": default_branch,
        }

    def _ensure_repo_node(self, repo_meta: dict[str, Any]) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (r:GitRepo {repo_id: $repo_id})
                SET r.root_path = $root_path,
                    r.remote_url = $remote_url,
                    r.default_branch = $default_branch
                """,
                **repo_meta,
            )

    def _resolve_commit_range(
        self,
        *,
        full: bool,
        checkpoint_sha: Optional[str],
    ) -> tuple[list[str], Optional[str], bool]:
        head_sha = self._head_sha()
        if not head_sha:
            return [], None, False

        if full:
            return self._rev_list(), head_sha, False

        if not checkpoint_sha:
            return self._rev_list(), head_sha, False

        checkpoint_invalid = (not self._commit_exists(checkpoint_sha)) or (
            not self._is_ancestor(checkpoint_sha)
        )
        if checkpoint_invalid:
            logger.warning("Git checkpoint %s invalid; falling back to full sync.", checkpoint_sha)
            return self._rev_list(), head_sha, True

        return self._rev_list(f"{checkpoint_sha}..HEAD"), head_sha, False

    def _read_commit(self, sha: str) -> GitCommitRecord:
        metadata = self._git(
            "show",
            "--quiet",
            "--no-color",
            f"--format=%H{_FIELD_SEP}%P{_FIELD_SEP}%an{_FIELD_SEP}%ae{_FIELD_SEP}%aI{_FIELD_SEP}%cI{_FIELD_SEP}%B",
            sha,
        ).stdout
        parts = metadata.split(_FIELD_SEP, maxsplit=6)
        if len(parts) < 7:
            raise RuntimeError(f"Unable to parse commit metadata for {sha}")

        parent_count = len(parts[1].split()) if parts[1].strip() else 0
        subject, body = self._split_message(parts[6])
        numstat = parse_numstat_output(
            self._git(
                "show",
                "--no-color",
                "--numstat",
                "--format=",
                "--find-renames",
                "--find-copies",
                sha,
            ).stdout
        )
        name_status = parse_name_status_output(
            self._git(
                "show",
                "--no-color",
                "--name-status",
                "--format=",
                "--find-renames",
                "--find-copies",
                sha,
            ).stdout
        )

        touched_files = self._merge_file_changes(name_status, numstat)
        return GitCommitRecord(
            sha=parts[0].strip(),
            parent_count=parent_count,
            authored_at=parts[4].strip(),
            committed_at=parts[5].strip(),
            author_name=parts[2].strip(),
            author_email=parts[3].strip().lower(),
            message_subject=subject,
            message_body=body,
            is_merge=parent_count > 1,
            touched_files=touched_files,
        )

    def _merge_file_changes(
        self,
        name_status: list[tuple[str, str]],
        numstat: dict[str, tuple[int, int]],
    ) -> list[GitFileChange]:
        merged: list[GitFileChange] = []
        seen_paths: set[str] = set()

        for change_type, path in name_status:
            normalized = path.replace("\\", "/")
            additions, deletions = numstat.get(normalized, (0, 0))
            merged.append(
                GitFileChange(
                    path=normalized,
                    change_type=change_type,
                    additions=additions,
                    deletions=deletions,
                )
            )
            seen_paths.add(normalized)

        for path, (additions, deletions) in numstat.items():
            normalized = path.replace("\\", "/")
            if normalized in seen_paths:
                continue
            merged.append(
                GitFileChange(
                    path=normalized,
                    change_type="M",
                    additions=additions,
                    deletions=deletions,
                )
            )

        return merged

    @staticmethod
    def _split_message(message: str) -> tuple[str, str]:
        stripped = message.strip("\n")
        if not stripped:
            return "", ""
        lines = stripped.splitlines()
        subject = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        return subject, body

    def _upsert_commit(self, repo_meta: dict[str, Any], commit: GitCommitRecord) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (repo:GitRepo {repo_id: $repo_id})
                SET repo.root_path = $root_path,
                    repo.remote_url = $remote_url,
                    repo.default_branch = $default_branch
                MERGE (commit:GitCommit {repo_id: $repo_id, sha: $sha})
                SET commit.parent_count = $parent_count,
                    commit.authored_at = datetime($authored_at),
                    commit.committed_at = datetime($committed_at),
                    commit.message_subject = $message_subject,
                    commit.message_body = $message_body,
                    commit.is_merge = $is_merge
                MERGE (repo)-[:HAS_COMMIT]->(commit)
                MERGE (author:GitAuthor {repo_id: $repo_id, email_norm: $author_email})
                SET author.name_latest = $author_name
                MERGE (commit)-[:AUTHORED_BY]->(author)
                """,
                repo_id=repo_meta["repo_id"],
                root_path=repo_meta["root_path"],
                remote_url=repo_meta["remote_url"],
                default_branch=repo_meta["default_branch"],
                sha=commit.sha,
                parent_count=commit.parent_count,
                authored_at=commit.authored_at,
                committed_at=commit.committed_at,
                message_subject=commit.message_subject,
                message_body=commit.message_body,
                is_merge=commit.is_merge,
                author_email=commit.author_email,
                author_name=commit.author_name,
            )

            if not commit.touched_files:
                return

            session.run(
                """
                UNWIND $files AS file
                MATCH (commit:GitCommit {repo_id: $repo_id, sha: $sha})
                MERGE (fv:GitFileVersion {repo_id: $repo_id, sha: $sha, path: file.path})
                SET fv.change_type = file.change_type,
                    fv.additions = file.additions,
                    fv.deletions = file.deletions
                MERGE (commit)-[:TOUCHES]->(fv)
                WITH fv, file
                OPTIONAL MATCH (code_file:File {path: file.path})
                FOREACH (_ IN CASE WHEN code_file IS NULL THEN [] ELSE [1] END |
                    MERGE (fv)-[:VERSION_OF]->(code_file)
                )
                """,
                repo_id=repo_meta["repo_id"],
                sha=commit.sha,
                files=[
                    {
                        "path": change.path,
                        "change_type": change.change_type,
                        "additions": change.additions,
                        "deletions": change.deletions,
                    }
                    for change in commit.touched_files
                ],
            )

    def _maybe_github_enrich(self, commit: GitCommitRecord) -> None:
        """Placeholder for future optional GitHub metadata hydration."""
        git_cfg = self.config.get_git_config()
        enrichment_cfg = git_cfg.get("github_enrichment", {})
        if not enrichment_cfg.get("enabled"):
            return
        # TODO: Add GitHub API enrichment for pull request and issue metadata.
        logger.debug("GitHub enrichment enabled but not implemented for commit %s.", commit.sha)

    def _rev_list(self, rev_range: Optional[str] = None) -> list[str]:
        args = ["rev-list", "--reverse"]
        if rev_range:
            args.append(rev_range)
        else:
            args.append("HEAD")
        output = self._git(*args).stdout
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _head_sha(self) -> Optional[str]:
        result = self._git("rev-parse", "HEAD", check=False)
        if result.returncode != 0:
            return None
        sha = result.stdout.strip()
        return sha or None

    def _commit_exists(self, sha: str) -> bool:
        result = self._git("cat-file", "-e", f"{sha}^{{commit}}", check=False)
        return result.returncode == 0

    def _is_ancestor(self, sha: str) -> bool:
        result = self._git("merge-base", "--is-ancestor", sha, "HEAD", check=False)
        return result.returncode == 0

    def _ensure_git_repo(self) -> None:
        result = self._git("rev-parse", "--is-inside-work-tree", check=False)
        if result.returncode != 0 or result.stdout.strip().lower() != "true":
            raise RuntimeError(f"Path is not a git repository: {self.repo_root}")

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
        return result
