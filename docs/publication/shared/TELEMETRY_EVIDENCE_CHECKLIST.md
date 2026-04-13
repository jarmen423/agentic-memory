# Telemetry and Evidence Checklist

This checklist maps the publication wave to the minimum event evidence needed for review, approval, and launch tracking.

## Core events

Record each of these with a timestamp, platform, and enough context to audit the event later:

- `install_attempted`
- `install_completed`
- `first_successful_tool_call`
- `first_successful_memory_write`
- `first_successful_memory_retrieval`
- `review_submitted`
- `review_revision_requested`
- `review_approved`
- `published_or_listed`
- `repair_succeeded`

## Evidence sources

- Hosted backend/operator checks:
  - `/health`
  - `/health/mcp-surfaces`
- ChatGPT developer-mode validation
- OpenAI dashboard case email and publish state
- Anthropic submission confirmation or directory listing evidence
- Manual operator notes where no automated source exists yet

## Minimum per-event fields

- Platform: `openai`, `codex`, `anthropic`, or `shared`
- Surface: `/mcp-openai`, `/mcp-codex`, `/mcp-claude`, or shared operator workflow
- Timestamp in UTC
- Actor or owner
- Environment: `review`, `staging`, or `production`
- Outcome: `success`, `failure`, `pending`
- Evidence link or reference

## Publication-specific evidence

- OpenAI:
  - case id
  - approval email received
  - published listing URL
  - exact-name search confirmation
  - derived Codex distribution confirmation
- Anthropic:
  - submission date
  - reviewer contact or tracking reference if provided
  - approval confirmation
  - directory listing URL

## Current gap

The repo has telemetry and product-state pieces, but the publication event ledger and evidence checklist are not yet wired into a single operator-facing status surface.
