# OpenAI Publish Checks

Run these after approval and before calling the release publicly launched.

## Dashboard actions

- Approval email received and archived.
- Case ID recorded in the publication status log.
- Approved app version is published from the OpenAI Platform Dashboard.
- Exact publish timestamp is recorded.

## Directory checks

- Direct ChatGPT app listing URL loads.
- Exact-name search for `Agentic Memory` finds the listing.
- Listing copy, logo, and screenshots match the approved submission.

## Codex distribution checks

- Codex plugin distribution appears after the approved app is published.
- Derived Codex distribution can be reached from its direct listing or exact-name search.
- Post-publish discovery notes are recorded for the launch owner.

## Regression checks

- `/mcp-openai` still exposes the frozen nine-tool contract.
- Reviewer test prompts still pass after publish.
- If auth is enabled, reviewer/demo credentials are rotated or disabled according to policy after approval.

## Versioning note

OpenAI locks submitted information after publish. Any later metadata or behavior change should go through a new draft version and review cycle rather than editing the live record ad hoc.
