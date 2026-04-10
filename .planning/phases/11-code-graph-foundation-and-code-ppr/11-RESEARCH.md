# Phase 11: Code Graph Foundation + Code PPR - Research

## Executive Summary

The repo and external research point to the same sequencing:

1. improve graph quality,
2. keep only high-confidence code edges in the first traversal graph,
3. add non-temporal seeded PPR for code retrieval,
4. defer wider graph walks and offline clustering until the graph earns that trust.

## Repo-Grounded Findings

### Why graph quality had to come first

- Import linking previously used a fuzzy path-contains fallback that could create false-positive `IMPORTS` edges.
- Call linking previously matched callees by short function name, which amplified collisions like `run`, `main`, or `load`.
- File-level call extraction contaminated function-level call edges.
- JS/TS call extraction did not have a trustworthy canonical path.

### Why `repo_id` was required

- Code nodes were effectively keyed by path/signature alone.
- The git graph already proved the right identity model:
  - `repo_id` distinguishes same-path files across repositories,
  - git/code joins should happen on `(repo_id, path)`, not `path` alone.

### Why code PPR is non-temporal

- Conversation and research retrieval benefit from validity windows, recency, and contradiction-aware weighting.
- Code queries usually want structure:
  - surrounding subsystem,
  - neighboring files,
  - definitions and imports,
  - “what else should I read?”
- That makes the PPR algorithm itself a fit, but not temporal weighting by default.

## Implementation Thesis

### Retrieval

- Keep vector search as the baseline recall step.
- Use top code hits as the PPR seeds.
- Run a constrained graph walk over:
  - `IMPORTS`
  - `DEFINES`
  - `HAS_METHOD`
- Merge baseline relevance and structural relevance into one explainable score.

### Safety

- Keep `ENABLE_CODE_PPR` off by default until the graph passes fixture and benchmark gates.
- Exclude `CALLS` from the v1 traversal graph because the current conservative same-file implementation is intentionally narrow.

## Benchmark Hypotheses

The PPR path should help most on:

- subsystem discovery,
- “what should I read next?” queries,
- cross-file feature tracing,
- bridge-file discovery from a strong initial semantic hit.

The PPR path should not regress:

- exact symbol lookup,
- short direct function/file search,
- repository-scoped dependency inspection.
