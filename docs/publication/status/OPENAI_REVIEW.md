# OpenAI Review Status

Wave:

- `w15-public-plugin-publication`

Official task:

- `W15-PUB-07`

## Current Status

- Submission state: submitted
- Review state: pending
- Publish state: not published

## Preconditions

- `W15-PUB-02` OpenAI submission packet: complete
- `W15-PUB-03` Codex preflight bundle: complete
- `W15-PUB-06` top-level integration: complete
- Stable publication URLs:
  - confirmed live on `https://mcp.agentmemorylabs.com`
- Public auth posture:
  - live reviewer path: OAuth 2.0 authorization code flow with DCR enabled on
    the public OpenAI surface
  - fallback reviewer path: dedicated bearer key via
    `AM_SERVER_PUBLIC_MCP_API_KEYS`
  - implementation: live in production

## Submission Metadata

- Submission owner: `individual`
- Verified publisher identity: `TBD`
- OpenAI project/data residency: `TBD`
- Canonical MCP endpoint: `https://mcp.agentmemorylabs.com/mcp-openai/`
- Case ID: `TBD` (dashboard review pending; no case reference captured yet)
- Submission date: `2026-04-19`
- Review URL: `TBD`
- Published listing URL: `TBD`
- Derived Codex distribution URL: `TBD`

## Activity Log

- 2026-04-12: tracker created for `W15-PUB-07`
- 2026-04-12: packet dependencies confirmed complete (`W15-PUB-02`, `W15-PUB-03`, `W15-PUB-06`)
- 2026-04-14: `backend.agentmemorylabs.com` and `mcp.agentmemorylabs.com`
  verified live; public legal pages and `/health` reachable
- 2026-04-14: dedicated public MCP reviewer-key path configured through
  `AM_SERVER_PUBLIC_MCP_API_KEYS`
- 2026-04-19: real ChatGPT developer-mode validation completed against
  `https://mcp.agentmemorylabs.com/mcp-openai/`
- 2026-04-19: OpenAI dashboard domain verification completed for
  `mcp.agentmemorylabs.com`
- 2026-04-19: OpenAI dashboard tool scan succeeded against the live public MCP
  surface after root/SSE probe aliasing fixes
- 2026-04-19: reviewer screenshots, example prompts, tool annotations, test
  cases, and reviewer credentials prepared for the dashboard flow
- 2026-04-19: app submitted for OpenAI review through the dashboard
- Next update: replace the remaining metadata placeholders immediately after
  OpenAI issues a review/case reference or requests revisions

## Evidence Links

- Submission confirmation email or screenshot: dashboard submission captured
  locally on `2026-04-19` (not yet archived into repo)
- Review case thread export: `TBD`
- Approval email: `TBD`
- Published app listing: `TBD`
- Derived Codex distribution confirmation: `TBD`

## Required Evidence

- App submission packet finalized
- Demo/reviewer credentials prepared
- Screenshots captured from real connected surface
- Case email archived
- Approval email archived
- Published listing URL recorded
- Derived Codex distribution confirmed

## Blocking Items

- OpenAI has not yet approved or published the listing
- review/case reference has not yet been captured into the tracker
- reviewer-facing evidence artifacts are prepared locally but not yet attached in
  repo-tracked form
- derived Codex distribution path remains downstream of OpenAI approval

## Next Action

- Wait for OpenAI review feedback, then capture the exact case/reference,
  archive any reviewer thread, and respond quickly to revision requests if they
  arrive

## Notes

- Public OpenAI path is the current dashboard submission/review/publish flow.
- Codex public distribution is derived from the approved and published OpenAI app.
