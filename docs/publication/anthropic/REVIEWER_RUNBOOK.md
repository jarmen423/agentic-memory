# Anthropic Reviewer Runbook

Current as of April 14, 2026.

This runbook prepares the remote MCP directory submission for the Anthropic connector path.

## Review target

- Product: `Agentic Memory`
- Canonical endpoint: `https://mcp.agentmemorylabs.com/mcp-claude`
- Transport: streamable HTTP
- Public tool count: `9`
- Public internet side effects: none
- State-changing tools:
  - `memory_ingest_research`
  - `add_message`

## Reviewer prerequisites

- Hosted endpoint is reachable over public HTTPS.
- Stable privacy, support, and website URLs are ready.
- Current live reviewer auth packet is prepared from `../shared/REVIEWER_ACCESS_PACKET.md`.
- If auth is enabled, reviewer credentials and sample data are ready.
- Marketplace publication still requires OAuth 2.0 authorization code flow to
  be validated on real Anthropic clients before that blocker can be closed.
- The live public MCP host may still use bearer-key reviewer fallback auth during rollout, even though OAuth is now implemented server-side.

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

1. Connect Claude to `https://mcp.agentmemorylabs.com/mcp-claude`.
2. Confirm the advertised tool list matches the frozen nine-tool contract.
3. Run the minimum examples in `USAGE_EXAMPLES.md`.
4. Confirm error messaging is understandable for auth or backend failures.
5. Verify whichever auth path is actually enabled for the live dry run:
   - OAuth authorization-code flow on the hosted public surface
   - or the dedicated bearer-key reviewer fallback path
6. If Claude Code support is claimed, validate a direct Claude Code connection under the same production auth/network assumptions.

## Anthropic-specific review notes

- Streamable HTTP is required.
- Missing tool annotations are a common rejection cause.
- Minimum three usage examples are required.
- OAuth now exists in the hosted backend, but reviewer fallback bearer-key auth may still be used during rollout and evidence prep.
- If the service is behind a firewall, Anthropic IP ranges must be allowlisted for brokered Claude surfaces.
- IP allowlisting alone does not support Claude Code.

## Submission packet contents

- `SUBMISSION_CHECKLIST.md`
- `USAGE_EXAMPLES.md`
- `AUTH_AND_REACHABILITY_CHECKLIST.md`
- `../shared/REVIEWER_ACCESS_PACKET.md`
- shared legal/support/runbook docs from `docs/publication/shared/`
- `PUBLISH_CHECKS.md`

## Failure triage before submission

- If Claude.ai or Claude Desktop cannot connect:
  - verify public internet reachability
  - verify firewall allowlisting if applicable
  - verify CORS and HTTPS
- If auth fails:
  - verify the reviewer key remains active for the current dry run
  - verify OAuth callback allowlisting only if/when OAuth is enabled
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
