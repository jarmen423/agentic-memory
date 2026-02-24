# Git Graph Integration

This document defines the git graph integration for Agentic Memory and how to run it in practice.

## Status and Scope

- Code graph behavior remains the default path.
- Git graph is an opt-in domain in the same Neo4j database.
- Local git ingestion is the baseline.
- GitHub enrichment is optional and non-blocking.

If your installed `codememory` build does not yet expose `git-init`, `git-sync`, or `git-status`, update to a build that includes the git graph rollout.

## Architecture: Separate Labels in the Same Database

The git graph uses separate labels and relationships so code queries remain stable and predictable.

Code-domain labels (existing):
- `File`
- `Function`
- `Class`
- `Chunk`

Git-domain labels (new):
- `GitRepo`
- `GitCommit`
- `GitAuthor`
- `GitFileVersion`
- `GitRef`

Optional enrichment labels:
- `GitPullRequest`
- `GitIssue`

Bridge edge between domains:
- `(:GitFileVersion)-[:VERSION_OF]->(:File)`

The bridge edge links commit/file history to current code files without mixing code-domain nodes into git ingestion paths.

## Query Domains

Use explicit domain routing in MCP tool calls:

- `domain=code`: code graph only.
- `domain=git`: git graph only.
- `domain=hybrid`: merges code + git signals.

## CLI Commands

### `codememory git-init`

Initialize git graph metadata and checkpoint state for a repository.

```bash
codememory git-init \
  --repo /absolute/path/to/repo \
  --mode local \
  --full-history
```

Common options:
- `--repo PATH`
- `--mode local|local+github`
- `--full-history`
- `--since <rev>`

Expected output (human-readable):

```text
✅ Git graph initialized
Repository: /absolute/path/to/repo
Mode: local
Checkpoint: <HEAD_SHA>
```

### `codememory git-sync`

Sync commits from git history into the git graph.

```bash
codememory git-sync --repo /absolute/path/to/repo --incremental
```

Common options:
- `--repo PATH`
- `--incremental`
- `--full`
- `--from-ref <ref>`

Expected output (human-readable):

```text
✅ Git sync complete
Mode: incremental
New commits: 3
Updated checkpoint: <NEW_HEAD_SHA>
```

Expected output when no new commits:

```text
✅ Git sync complete
Mode: incremental
New commits: 0
Checkpoint unchanged: <HEAD_SHA>
```

### `codememory git-status`

Show git graph ingestion status for the current repository.

```bash
codememory git-status --repo /absolute/path/to/repo --json
```

Expected JSON envelope:

```json
{
  "ok": true,
  "error": null,
  "data": {
    "repo": "/absolute/path/to/repo",
    "mode": "local",
    "last_synced_sha": "<HEAD_SHA>",
    "commits_indexed": 1240,
    "partial_history": false,
    "github_enrichment": {
      "enabled": false,
      "state": "disabled"
    }
  },
  "metrics": {}
}
```

## Local-Only Baseline and GitHub Enrichment Roadmap

### Baseline (required)

- Ingest local commit graph: commit metadata, parent links, author links, touched files.
- Maintain checkpoint-based incremental sync.
- Keep ingestion idempotent by `(repo_id, sha)`.

### Optional enrichment (roadmap / feature flag)

- Attach PR metadata (`GitPullRequest`) and issue metadata (`GitIssue`) when enabled.
- Continue local ingestion even when enrichment fails.
- Mark enrichment status as stale/disabled in `git-status` rather than failing sync.

## Validation and Expected Results

Quick validation sequence:

```bash
codememory git-init --repo /absolute/path/to/repo --mode local --full-history
codememory git-sync --repo /absolute/path/to/repo --incremental
codememory git-status --repo /absolute/path/to/repo --json
```

Expected behavior:
- `git-init` creates git repo/checkpoint state.
- `git-sync` ingests unseen commits only on repeated runs.
- `git-status` reports checkpoint and ingestion counts.

## Troubleshooting

### `invalid choice: 'git-init'`

Your installed package does not include the git graph CLI yet.

Action:
- Upgrade to a build/release that includes git graph commands.
- Verify with `codememory --help`.

### `Not a git repository`

`--repo` does not point to a valid git working tree.

Action:
- Confirm `.git/` exists under the provided path.
- Re-run with absolute path to the repo root.

### `partial_history: true` in status

Repository is shallow or history is incomplete.

Action:

```bash
git fetch --unshallow
codememory git-sync --full
```

### Diverged/rewritten history after force push

Checkpoint no longer matches reachable history.

Action:

```bash
codememory git-sync --full
```

If reconcile support is enabled in your build, use the reconcile flag documented by `codememory git-sync --help`.

### GitHub enrichment fails (auth/rate limit)

Local ingestion should continue; enrichment should be marked stale/failed in status.

Action:
- Verify token and provider settings.
- Re-run sync later; do not block local-only ingestion.
