# Anthropic Review Status

Wave:

- `w15-public-plugin-publication`

Official task:

- `W15-PUB-07`

## Current Status

- Submission state: not submitted
- Review state: not started
- Listing state: not listed

## Preconditions

- `W15-PUB-04` Anthropic submission packet: complete
- `W15-PUB-06` top-level integration: complete
- Stable publication URLs:
  - confirmed live on `https://mcp.agentmemorylabs.com`
- Public auth posture:
  - live reviewer path: bearer API key via `AM_SERVER_PUBLIC_MCP_API_KEYS`
  - marketplace target: `OAuth 2.0 authorization code flow`
  - implementation: pending

## Submission Metadata

- Submission owner: `TBD`
- Canonical MCP endpoint: `https://mcp.agentmemorylabs.com/mcp-claude`
- Submission date: `TBD`
- Tracking reference: `TBD`
- Claimed supported surfaces: `TBD`
- Review URL: `TBD`
- Final directory listing URL: `TBD`

## Activity Log

- 2026-04-12: tracker created for `W15-PUB-07`
- 2026-04-12: packet dependencies confirmed complete (`W15-PUB-04`, `W15-PUB-06`)
- 2026-04-14: `backend.agentmemorylabs.com` and `mcp.agentmemorylabs.com`
  verified live; public legal pages and `/health` reachable
- 2026-04-14: dedicated public MCP reviewer-key path configured through
  `AM_SERVER_PUBLIC_MCP_API_KEYS`
- Next update: replace the placeholders in `Submission Metadata` immediately after submission

## Evidence Links

- Submission confirmation email or screenshot: `TBD`
- Review thread or ticket export: `TBD`
- Approval email: `TBD`
- Directory listing page: `TBD`

## Required Evidence

- Anthropic submission packet finalized
- Minimum three usage examples finalized
- Reviewer/test account prepared
- OAuth callback allowlist configured if auth is enabled
- Public reachability confirmed from Anthropic-compatible paths
- Approval evidence archived
- Final directory listing URL recorded

## Blocking Items

- OAuth not implemented
- real Claude validation and usage-example capture not complete
- reviewer/test packet not finalized
- final truthfulness check for Claude Code support not complete

## Next Action

- Run real Claude.ai and Claude Desktop validation against the live host,
  capture the required examples, and only then close the remaining auth and
  supported-surface claims before submission

## Notes

- Streamable HTTP is required.
- IP allowlisting alone is not a sufficient basis to claim Claude Code support.
