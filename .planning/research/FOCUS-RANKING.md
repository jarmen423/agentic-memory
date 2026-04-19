# Follow-up: Focus-aware ranking

Status: **deferred / research-gated**
Owner: TBD
Last updated: 2026-04-19

## Why this doc exists

The `/project focus` slash command landed in the MCP server as part of the
project-scope work (see `register_project_scope_tools` in
`src/agentic_memory/server/tools.py` and `ActiveScopes` in
`src/agentic_memory/mcp_workspace.py`). The command already:

- accepts one or more `repo_id`s,
- validates them against the set of projects that actually live in the graph,
- persists them in `ActiveScopes.focus`, and
- surfaces them through `project_status`, the `active-scopes` MCP resource,
  and every `/project_*` tool response.

It does **not** influence retrieval today. Focus is informational only. The
user explicitly asked us to stop here and do the ranking work after research,
because a half-baked boost is worse than no boost: it reshuffles results
without telling anyone why and makes the underlying retrieval impossible to
evaluate.

This doc captures the open research question so the next person (likely the
same user, a future agent, or both) has the full framing without rereading
the chat.

## What the signal is today

`ActiveScopes.focus: tuple[str, ...]` — an ordered, deduplicated list of
`repo_id` values. Semantics as written:

- empty tuple = no preference (current retrieval behaviour).
- non-empty tuple = the user prefers results that carry one of these
  `repo_id`s, but results from other projects must still be reachable.

Focus is deliberately **separate** from isolate. Isolate is a hard filter
(results outside the list are invisible). Focus is a soft preference
(results outside the list should rank lower, not disappear).

Focus is also deliberately **separate** from write target. The write target
controls which `repo_id` new memory is tagged with; focus is read-side only.

## Why "just boost the score" is not enough

The naive implementation — multiply the retrieval score by, say, 1.2 when a
hit is in the focus set — fails three ways:

1. **Ranking regime is heterogeneous.** Unified search blends vector
   similarity, temporal priors, and graph-based expansion. A single
   multiplicative boost applied after fusion moves hits in a
   direction that is not stable across query types. Boosts that help on
   code search can hurt on conversation recall.
2. **No regression signal.** Without a gold set that includes focus
   metadata, any change looks plausible in a single anecdote and invisible
   in aggregate. The existing eval fixtures
   (`bench/fixtures/eval/code-gold.jsonl`, `conversation-gold.jsonl`,
   `research-gold.jsonl`) have no `focus` column, so we can't even measure
   "did focus help the user land on the right memory" before/after.
3. **Focus interacts with decay.** Old memory from the focused project may
   become *more* relevant than fresh memory from other projects, which
   inverts the usual freshness prior. A multiplicative boost cannot
   express that without breaking non-focused queries.

## The research question

Given the user has declared a focus list, what is the ranking function that
produces the best retrieval on the existing eval set **without making the
no-focus case worse**?

Minimum viable experiment design:

1. Extend each gold fixture with a `focus` column. For every query, the
   annotator records the `repo_id`s the user would plausibly have focused
   on when asking that question (often empty; sometimes the home repo).
2. Add a synthetic multi-repo corpus. Smoke fixtures
   (`bench/fixtures/eval/*-smoke.jsonl`) currently all tag the same single
   `repo_id`; without cross-repo contamination the focus ranking is a
   no-op. The fix is either (a) run the same fixtures with two additional
   "decoy" repos ingested first, or (b) stitch pairs of fixtures together
   with distinct `repo_id`s and query them jointly.
3. Run the benchmark harness
   (`scripts/run_openclaw_verification_gates.py` or the existing smoke
   driver, whichever is faster to extend) with three ranking variants:
   - baseline (no focus wiring),
   - multiplicative boost,
   - additive rank reshuffle (top-N of focus, then interleave),
   - optional learned variant (logistic regression over
     `{cosine, recency, focus_indicator}` once we have labeled data).
4. Report nDCG@10 and Recall@10 split by `focus == [] / focus != []`. The
   acceptance bar is *no regression on the empty-focus slice* and a
   statistically visible lift on the focused slice.

## Why this was punted

- The benchmarking scaffolding exists, but the fixtures do not yet encode
  focus. Extending them without a retrieval target is premature —
  annotation work compounds noise instead of signal.
- The user explicitly said "defer until diligent research is done". The
  existing slash-command plumbing is already useful for isolation and
  write-target pinning (which *do* change retrieval today), so we chose
  to ship those and leave ranking for a dedicated follow-up.
- The reranker decision doc
  (`.claude/plans/decision-doc-rerankers.md`) and its research report
  (`.claude/plans/research-report-rerankers.md`) cover related but
  separate territory (cross-encoder rerankers over unified search
  output). Any focus-ranking approach should ride on top of whichever
  reranker we land on, not compete with it.

## Concrete next steps

1. Decide whether focus ranking should live inside
   `unified_search.py` or be composed in after the reranker. Probable
   answer: compose after, so focus is always a user-visible, tunable
   post-filter.
2. Extend `bench/fixtures/eval/*-gold.jsonl` with a `focus` column; write
   a migration script that leaves the column empty for legacy rows.
3. Add a `focus` parameter plumbed through `unified_search` (and its
   underlying calls). Default to the current `ActiveScopes.focus` when the
   caller doesn't override. Ship this as a no-op (the parameter is
   accepted but ignored) so the eval harness can start feeding it.
4. Run the experiment matrix above. Promote whichever variant wins the
   empty-focus regression check *and* the focused-slice lift.
5. Only after that: wire `ActiveScopes.focus` into real retrieval and
   remove the "informational only" caveat from
   `register_project_scope_tools`' docstring.

## Quick links

- Scope state: `src/agentic_memory/mcp_workspace.py` (`ActiveScopes`,
  `set_focus`, `get_active_scopes`).
- Tool registration: `src/agentic_memory/server/tools.py`
  (`register_project_scope_tools`, `_scopes_payload`).
- Retrieval entry points to touch:
  `src/agentic_memory/server/unified_search.py`,
  `src/agentic_memory/server/research_search.py`.
- Eval fixtures: `bench/fixtures/eval/*.jsonl`.
- Reranker context: `.claude/plans/decision-doc-rerankers.md`,
  `.claude/plans/research-report-rerankers.md`.
