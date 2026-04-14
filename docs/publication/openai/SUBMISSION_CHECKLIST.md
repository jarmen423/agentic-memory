# OpenAI Submission Checklist

Current as of April 14, 2026.

This packet is for the OpenAI public publication path:

1. Validate in ChatGPT developer mode.
2. Submit through the OpenAI Platform Dashboard review flow.
3. Publish the approved app.
4. Verify the resulting ChatGPT listing and derived Codex distribution.

## Current release target

- Product name: `Agentic Memory`
- Canonical OpenAI reviewer endpoint: `https://mcp.agentmemorylabs.com/mcp-openai`
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

## Gate A: Prerequisites

- `Owner` role confirmed for the submitting OpenAI organization.
- Individual or business verification completed for the publication name.
- Submission project uses global data residency.
- Hosted MCP endpoint is public HTTPS and not a local tunnel or test host.
- Current reviewer dry-run auth is fixed:
  - bearer API key through `AM_SERVER_PUBLIC_MCP_API_KEYS`
- Marketplace authenticated publication target remains:
  - OAuth 2.0 authorization code flow for authenticated review and launch
  - no fallback claim of anonymous multi-tenant access for private memory
- Exact CSP and remote fetch domain inventory is documented for submission.
- Canonical public URLs are deployed and reachable:
  - website: `https://mcp.agentmemorylabs.com/publication/agentic-memory`
  - privacy: `https://mcp.agentmemorylabs.com/publication/privacy`
  - terms: `https://mcp.agentmemorylabs.com/publication/terms`
  - support: `https://mcp.agentmemorylabs.com/publication/support`

## Gate B: Product and metadata readiness

- App name is final and matches the verified publisher identity.
- Short and long descriptions match actual behavior and do not oversell.
- Logo is final and submission-ready.
- Required screenshots are captured from the actual app experience.
- Tool names and descriptions match the hosted public surface.
- Tool annotations are accurate:
  - read tools marked read-only
  - write tools marked non-read-only
  - destructive hints justified
  - open-world hints remain `false` because public tools do not modify public internet state
- Privacy policy discloses returned user-related data categories and memory-write behavior.
- Tool responses are scrubbed of unnecessary internal identifiers, trace ids, request ids, and secrets.
- Mobile behavior is validated if the app is intended to be usable there.

## Gate C: Reviewer packet

- MCP server details are ready for dashboard entry.
- OAuth details are ready if OAuth is selected.
- Test prompts and expected responses are prepared.
- Reviewer/demo account checklist is complete if auth is required.
- Localization and country availability decisions are documented.
- Submission owner is prepared to receive the case email and track the case id.

## Gate D: Developer-mode validation before submit

- ChatGPT developer mode connects to `/mcp-openai`.
- Refresh metadata succeeds after a redeploy.
- Advertised tool list matches the frozen public contract.
- One code-search scenario passes.
- One dependency lookup scenario passes.
- One execution-trace scenario passes.
- One conversation-memory read scenario passes.
- One explicit memory-write scenario passes.
- One research-memory write scenario passes.
- Error handling is understandable when auth fails or the backend is unhealthy.

## Gate E: Publish and post-approval

- Approval email received.
- Approved app is published from the dashboard.
- Direct listing URL is recorded.
- Exact-name directory search finds the listing.
- Derived Codex distribution is confirmed after publication.
- Launch owner records the publish date, case id, and approval evidence.

## Remaining blockers on April 14, 2026

- The canonical publication URLs are live, but the real ChatGPT-connected validation and screenshot pass are still outstanding.
- No reviewer screenshots are checked into `docs/publication/openai/` yet.
- OAuth remains the marketplace target auth posture, but end-to-end implementation and validation are still outstanding.
- No final CSP/fetch-domain inventory is documented in repo docs yet.

## Exit criteria for W15-PUB-02

- This checklist is complete and no item above is ambiguous.
- `DASHBOARD_FIELD_INVENTORY.md` is populated with repo-specific draft values.
- `TEST_PROMPTS.md` and `REVIEWER_RUNBOOK.md` are consistent with the frozen nine-tool contract.
- `DEMO_ACCOUNT_CHECKLIST.md` and `PUBLISH_CHECKS.md` cover the remaining reviewer and launch loops.
