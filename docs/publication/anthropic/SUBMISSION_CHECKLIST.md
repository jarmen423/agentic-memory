# Anthropic Submission Checklist

Current as of April 14, 2026.

This packet is for the Anthropic public publication path:

1. Validate the hosted remote MCP surface against Claude.
2. Submit the connector through Anthropic's current MCP directory review form.
3. Respond to any revision requests.
4. Verify the final Connectors Directory listing.

## Current release target

- Product name: `Agentic Memory`
- Canonical Anthropic reviewer endpoint: `https://mcp.agentmemorylabs.com/mcp-claude`
- Public tool contract:
  - `search_codebase`
  - `get_file_dependencies`
  - `trace_execution_path`
  - `search_all_memory`
  - `search_web_memory`
  - `memory_ingest_research`
  - `search_conversations`
  - `get_conversation_context`
  - `add_message`
- Public annotations: frozen in `W15-PUB-01`
- Required transport: streamable HTTP

## Gate A: Mandatory technical requirements

- Hosted MCP endpoint is reachable on the public internet over HTTPS/TLS.
- Endpoint supports streamable HTTP.
- CORS is configured for supported browser/cloud clients.
- Every public tool has accurate safety annotations:
  - read-only tools use `readOnlyHint`
  - state-changing tools use `destructiveHint`
- Tool descriptions are clear and match actual behavior.
- Tool results stay within the practical token limits for Claude surfaces.
- Error handling is user-friendly and not just raw backend exceptions.
- Server is production-ready and GA, not beta or alpha.

## Gate B: Auth, identity, and reachability

- The current reviewer dry-run auth model is a bearer API key via `AM_SERVER_PUBLIC_MCP_API_KEYS`.
- The marketplace authenticated publication target is OAuth 2.0 authorization code flow.
- If OAuth is used, the required callback URLs are allowlisted:
  - `http://localhost:6274/oauth/callback`
  - `http://localhost:6274/oauth/callback/debug`
  - `https://claude.ai/api/mcp/auth_callback`
  - `https://claude.com/api/mcp/auth_callback`
- If the server is behind a firewall, Anthropic IP ranges are allowlisted for Claude.ai and Claude Desktop connectivity.
- Public reachability is tested from outside internal networks and VPNs.
- The team understands the Claude Code caveat:
  - IP allowlisting alone does not support Claude Code
  - pure machine-to-machine OAuth is not supported

## Gate C: Documentation and compliance

- Clear setup and usage documentation is published.
- Minimum three working usage examples are documented.
- Privacy policy URL is stable and public.
- Support channel URL or email is stable and public.
- Company/product website URL is stable and public.
- Submission materials describe any account requirements or sign-up constraints.
- If a DPA URL is requested in the form, a stable URL is available.

## Gate D: Reviewer account and testability

- If auth is required, a test account with sample data is prepared.
- Test account has access to every tool being reviewed.
- Reviewer setup instructions are short and unambiguous.
- Review account remains active during the review window and periodic follow-up checks.
- Test account does not require MFA, corporate network access, or manual staff intervention.

## Gate E: Surface validation before submit

- Claude.ai validation passes against `/mcp-claude`.
- Claude Desktop validation passes against `/mcp-claude`.
- Claude Code validation is tested if the chosen auth/network model supports it.
- One code-search scenario passes.
- One conversation-memory read scenario passes.
- One explicit memory-write scenario passes.
- One research-memory write or retrieval scenario passes.
- Connection and auth failure states produce understandable errors.

## Gate F: Directory submission and post-approval

- Submission form fields are complete and consistent.
- Final docs/support/privacy links are live before submission.
- Submission date and any tracking reference are recorded.
- Approval evidence is recorded.
- Final directory listing URL is recorded.
- Post-listing smoke tests are run against the live public connector.

## Remaining blockers on April 14, 2026

- The canonical publication URLs and DPA route are live, but the real Claude-connected validation loop is still outstanding.
- No Anthropic-specific usage examples were checked into the repo before this packet.
- OAuth remains the marketplace target auth posture, but end-to-end implementation and validation are still outstanding.

## Exit criteria for W15-PUB-04

- This checklist is complete and no requirement above is ambiguous.
- `USAGE_EXAMPLES.md` contains at least three realistic reviewer examples.
- `AUTH_AND_REACHABILITY_CHECKLIST.md` covers OAuth, firewall, callback, and Claude Code caveats.
- `REVIEWER_RUNBOOK.md` and `PUBLISH_CHECKS.md` are aligned with the frozen nine-tool contract.
