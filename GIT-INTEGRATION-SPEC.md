# Git History Graph as an Optional, Separate Domain in the Same
  Neo4j DB

  ## Summary

  Add an opt-in git-history graph to CodeMemory that lives in the
  same Neo4j database but uses separate labels and relationships.
  Keep current code graph behavior unchanged by default. Introduce
  routing modes so tools can query code, git, or hybrid depending on
  task intent. Support local git first, with a defined enrichment
  layer for GitHub PR/issue metadata.

  ## Product Goals and Success Criteria

  1. Goal: Preserve high signal for current code intelligence while
     enabling provenance, ownership, and historical context.
  2. Goal: Avoid graph noise by strict label isolation and explicit
     query routing.
  3. Goal: Provide fast incremental sync keyed to new commits.
  4. Success criteria:
  5. codememory current commands keep existing outputs and
     performance envelopes when git graph is disabled.
  6. Git sync can ingest full history and then incrementally process
     only unseen commits.
  7. Hybrid query mode can answer at least these classes of
     questions:
  8. “Who last changed this file/function and why?”
  9. “Which recent commits touch high-centrality files?”
  10. “What PR introduced this dependency edge?”
  11. No duplicate commit/file-version nodes across reruns.
  12. End-to-end tests cover local-only and local+GitHub-enriched
     paths.

  ## Scope

  1. In scope:
  2. New git graph schema, ingestion pipeline, checkpoints, CLI
     commands, MCP/tool routing, docs, tests.
  3. Local git ingestion from repository metadata.
  4. Optional GitHub enrichment spec and implementation hooks.
  5. Out of scope for v1:
  6. Full GitHub-only ingestion mode as primary path.
  7. Cross-repo global identity resolution beyond one repository at a
     time.
  8. Blame-level line attribution for every symbol on every commit.

  ## Storage and Schema Design

  1. Storage model:
  2. Same Neo4j DB, separate labels and relationships.
  3. Existing labels remain untouched: File, Function, Class, Chunk.
  4. New labels:
  5. GitRepo {repo_id, root_path, remote_url, default_branch}
  6. GitCommit {repo_id, sha, parent_count, authored_at,
     committed_at, message_subject, message_body, is_merge}
  7. GitAuthor {repo_id, email_norm, name_latest}
  8. GitFileVersion {repo_id, path, sha, change_type, additions,
     deletions}
  9. GitRef {repo_id, ref_name, ref_type}
  10. Optional enrichment labels:
  11. GitPullRequest {repo_id, provider, number, title, state,
     merged_at, url}
  12. GitIssue {repo_id, provider, number, title, state, url}
  13. New relationships:
  14. (:GitRepo)-[:HAS_COMMIT]->(:GitCommit)
  15. (:GitCommit)-[:PARENT]->(:GitCommit)
  16. (:GitCommit)-[:AUTHORED_BY]->(:GitAuthor)
  17. (:GitCommit)-[:TOUCHES]->(:GitFileVersion)
  18. (:GitFileVersion)-[:VERSION_OF]->(:File) where path matches
     current code graph file path
  19. (:GitRef)-[:POINTS_TO]->(:GitCommit)
  20. Optional enrichment edges:
  21. (:GitCommit)-[:PART_OF_PR]->(:GitPullRequest)
  22. (:GitCommit)-[:REFERENCES_ISSUE]->(:GitIssue)
  23. Constraints and indexes:
  24. Unique GitRepo.repo_id
  25. Unique composite for commit identity via repo_id + sha
  26. Unique composite for author identity via repo_id + email_norm
  27. Index GitFileVersion.path, GitCommit.committed_at,
     GitPullRequest.number

  ## Public Interfaces and API Changes

  1. CLI additions:
  2. codememory git-init [--repo PATH] [--mode local|local+github]
     [--full-history|--since <rev>]
  3. codememory git-sync [--repo PATH] [--incremental|--full]
     [--from-ref <ref>]
  4. codememory git-status [--repo PATH] [--json]
  5. codememory git-query --query "<text>" --domain git|hybrid
     [--json]
  6. CLI behavior defaults:
  7. Manual setup required.
  8. After setup, incremental sync is enabled by default on new
     commits.
  9. Opt-out flag in config: git.auto_incremental=false.
  10. Existing command changes:
  11. codememory watch checks if git-sync is enabled; if yes, it
     syncs only new commits at safe intervals.
  12. codememory index remains code-graph only unless --with-git is
     passed.
  13. MCP/tooling changes:
  14. Add optional domain parameter to relevant tools: code default,
     git, hybrid.
  15. Add new tools:
  16. get_git_file_history(path, limit, domain=git)
  17. get_commit_context(sha, include_diff_stats=true)
  18. find_recent_risky_changes(path_or_symbol, window_days,
     domain=hybrid)
  19. Config additions in .codememory/config.json:
  20. git.enabled, git.auto_incremental, git.sync_trigger=commit|
     push|both, git.github_enrichment.enabled,
     git.github_enrichment.repo, git.checkpoint.last_sha.

  ## Ingestion and Data Flow

  1. Setup:
  2. git-init resolves repo root and creates GitRepo node plus
     initial checkpoint.
  3. Full sync:
  4. Stream commits from git rev-list and metadata from git show
     --name-status --numstat.
  5. Normalize identities and write commit, author, file-version
     nodes.
  6. Link GitFileVersion.path to existing File.path when present.
  7. Incremental sync:
  8. Compute unseen commits from checkpoint to HEAD.
  9. Process only delta commits, idempotently upserting by repo_id +
     sha.
  10. Trigger behavior:
  11. Manual git-sync always available.
  12. Auto-incremental triggers on local new commits.
  13. Optional push-trigger mode for GitHub enrichment polling on
     remote updates.
  14. GitHub enrichment:
  15. Parse PR numbers from commit message conventions when
     available.
  16. Optional API lookup to hydrate PR and issue nodes.
  17. Keep enrichment resilient and non-blocking for core local
     ingestion.

  ## Query Routing Strategy

  1. Routing modes:
  2. code: current code graph only.
  3. git: git graph only.
  4. hybrid: execute scoped subqueries and merge/rerank.
  5. Hybrid merge policy:
  6. Candidate set from code semantic search.
  7. Attach git signals such as recency, author concentration, and PR
     linkage.
  8. Rerank with explicit weighted score:
  9. score = 0.65*semantic + 0.20*structural + 0.15*git_signal
     default.
  10. Expose weights in config for tuning.

  ## Edge Cases and Failure Modes

  1. Rewritten history:
  2. Detect force-push divergence and support git-sync --full
     --reconcile.
  3. File renames:
  4. Capture rename status and map old/new paths; maintain linkage
     continuity.
  5. Detached HEAD or shallow clones:
  6. Warn and degrade gracefully; mark partial-history state in git-
     status.
  7. Missing GitHub auth or API rate limits:
  8. Continue local ingestion; mark enrichment as stale, never block
     core sync.
  9. Multiple authors with same name:
  10. Key identity by normalized email, not display name.

  ## Testing Plan

  1. Unit tests:
  2. Commit parser normalization.
  3. Checkpoint delta computation.
  4. Idempotent upsert behavior.
  5. Rename/change-type handling.
  6. Integration tests:
  7. Full local history import into test Neo4j.
  8. Incremental sync after creating new commits.
  9. Hybrid query returns combined signals without duplicate
     entities.
  10. Regression tests:
  11. Existing search, deps, impact, watch outputs unchanged when git
     disabled.
  12. Performance tests:
  13. Baseline ingest time and query latency before/after git graph
     enabled.
  14. Acceptance scenarios:
  15. User asks file ownership question and receives correct last
     committer and PR context.
  16. Re-running sync with no new commits produces zero new nodes.

  ## Rollout Plan

  1. Phase 1:
  2. Ship local git graph ingestion with manual commands and
     checkpoints.
  3. Phase 2:
  4. Enable optional auto-incremental trigger on commits during watch
     sessions.
  5. Phase 3:
  6. Add GitHub enrichment behind feature flag.
  7. Phase 4:
  8. Promote hybrid MCP tools to default recommendations after
     benchmark validation.

  ## Documentation Updates

  1. Add docs/GIT_GRAPH.md with schema, commands, and examples.
  2. Update docs/MCP_INTEGRATION.md with domain routing and hybrid
     tool usage.
  3. Update docs/TROUBLESHOOTING.md for shallow clone, rewrite, and
     auth cases.
  4. Add “when to use code vs git vs hybrid” decision table.

  ## Assumptions and Defaults

  1. Default behavior remains current code graph only unless user
     enables git graph.
  2. Git graph uses same Neo4j DB with strict label isolation.
  3. Manual setup is required; incremental sync defaults to enabled
     after setup.
  4. Trigger default is commit; optional push or both.
  5. Local git ingestion is required baseline; GitHub enrichment is
     optional and non-blocking.
  6. Hybrid query mode is explicit, not implicit, for predictable
     behavior and cost.
