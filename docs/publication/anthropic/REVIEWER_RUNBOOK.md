# Anthropic Reviewer Runbook

Current as of April 12, 2026.

This runbook prepares the remote MCP directory submission for the Anthropic connector path.

## Review target

- Product: `Agentic Memory`
- Canonical endpoint: `https://api.agenticmemory.com/mcp-claude`
- Transport: streamable HTTP
- Public tool count: `9`
- Public internet side effects: none
- State-changing tools:
  - `memory_ingest_research`
  - `add_message`

## Reviewer prerequisites

- Hosted endpoint is reachable over public HTTPS.
- Stable privacy, support, and website URLs are ready.
- Auth posture is finalized as OAuth 2.0 authorization code flow.
- If auth is enabled, reviewer test account and sample data are ready.

## Required validation surfaces

- Claude.ai
- Claude Desktop
- Claude Code if and only if the chosen auth/network model truly supports it

## Expected tool contract

Read tools:

- `search_codebase`
- `get_file_dependencies`
- `trace_execution_path`
- `search_all_memory`
- `search_web_memory`
- `search_conversations`
- `get_conversation_context`

Write tools:

- `memory_ingest_research`
- `add_message`

Annotation expectations:

- Read tools: `readOnlyHint=true`, `destructiveHint=false`
- Write tools: `readOnlyHint=false`, `destructiveHint=true`
- Public-internet side effects: none, so current `openWorldHint` posture remains false

## Pre-submission dry run

1. Connect Claude to `https://api.agenticmemory.com/mcp-claude`.
2. Confirm the advertised tool list matches the frozen nine-tool contract.
3. Run the minimum examples in `USAGE_EXAMPLES.md`.
4. Confirm error messaging is understandable for auth or backend failures.
5. If auth is enabled, verify OAuth flow end-to-end.
6. If Claude Code support is claimed, validate a direct Claude Code connection under the same production auth/network assumptions.

## Anthropic-specific review notes

- Streamable HTTP is required.
- Missing tool annotations are a common rejection cause.
- Minimum three usage examples are required.
- If the server requires auth, OAuth 2.0 authorization code flow is the supported model.
- If the service is behind a firewall, Anthropic IP ranges must be allowlisted for brokered Claude surfaces.
- IP allowlisting alone does not support Claude Code.

## Submission packet contents

- `SUBMISSION_CHECKLIST.md`
- `USAGE_EXAMPLES.md`
- `AUTH_AND_REACHABILITY_CHECKLIST.md`
- shared legal/support/runbook docs from `docs/publication/shared/`
- `PUBLISH_CHECKS.md`

## Failure triage before submission

- If Claude.ai or Claude Desktop cannot connect:
  - verify public internet reachability
  - verify firewall allowlisting if applicable
  - verify CORS and HTTPS
- If auth fails:
  - verify OAuth callback allowlisting
  - verify reviewer credentials remain active
  - verify the chosen auth model matches the claimed supported surfaces
- If Claude Code fails while cloud surfaces work:
  - re-check whether the design depends on Anthropic IP allowlisting or unsupported auth assumptions
  - do not claim Claude Code support until the direct connection path is validated
- If outputs are noisy or too large:
  - reduce response size
  - keep tool results token-efficient and relevant

## Internal sign-off before submit

- Backend owner signs off on endpoint stability and annotations.
- Release owner signs off on privacy/support/website readiness.
- Submission owner signs off on auth posture, examples, and reviewer setup instructions.
