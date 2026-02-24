# Field Test Template (Re-Run Validation)

Use this template when re-running validation in a user test repository (for example, `radiology-ai-video-v2`).

## Metadata

- Date:
- Operator:
- Repository:
- Branch/commit under test:
- `codememory` version (`codememory --version`):
- Neo4j version:
- Python version:
- Test mode: `local` or `local+github`

## Preflight

- [ ] Neo4j is running and credentials are valid.
- [ ] Repository has a clean/known git state.
- [ ] `.codememory/config.json` matches expected environment values.
- [ ] `codememory --help` includes `git-init`, `git-sync`, `git-status` (if validating git graph CLI).

## Commands Executed

```bash
# 1) Code graph baseline
codememory index
codememory status --json

# 2) Git graph setup + sync
codememory git-init --repo /absolute/path/to/repo --mode local --full-history
codememory git-sync --repo /absolute/path/to/repo --incremental
codememory git-status --repo /absolute/path/to/repo --json

# 3) Optional MCP checks (domain routing)
# search_codebase(query="...", domain="code")
# get_git_file_history(file_path="...", domain="git")
# find_recent_risky_changes(path_or_symbol="...", window_days=30, domain="hybrid")
```

## Metrics Capture

Record exact values from command output.

### Code Graph

- Files indexed:
- Functions indexed:
- Classes indexed:
- Chunks indexed:
- Last code sync timestamp:

### Git Graph

- Commits indexed:
- Authors indexed:
- File versions indexed:
- Last synced SHA:
- Partial history flag (`true/false`):
- GitHub enrichment state (`disabled|ok|stale|error`):

### Performance

- `codememory index` elapsed time:
- `codememory git-sync --incremental` elapsed time:
- Embedding calls:
- Token usage:
- Estimated cost:

## PASS / FAIL Checklist

- [ ] PASS / FAIL: `git-init` succeeds with expected repo metadata.
- [ ] PASS / FAIL: first `git-sync` ingests history and sets checkpoint.
- [ ] PASS / FAIL: second `git-sync --incremental` with no new commits reports zero new commits.
- [ ] PASS / FAIL: `git-status --json` returns stable envelope (`ok`, `error`, `data`, `metrics`).
- [ ] PASS / FAIL: code graph queries still work with git graph enabled.
- [ ] PASS / FAIL: `domain="code"` queries return expected code entities.
- [ ] PASS / FAIL: `domain="git"` queries return commit/file history signals.
- [ ] PASS / FAIL: `domain="hybrid"` queries combine code + git context without duplicates.
- [ ] PASS / FAIL: failures in GitHub enrichment do not block local-only ingestion.

## Evidence

- Console output snippets:
- Cypher verification queries and results:
- Screenshots/log paths:

## Issues Found

- Issue 1:
  - Severity:
  - Repro steps:
  - Expected:
  - Actual:

## Final Verdict

- Overall status: PASS / FAIL
- Recommended next action:
