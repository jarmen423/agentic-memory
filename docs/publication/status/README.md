# Publication Status

This directory tracks live review and launch evidence for the publication wave.
It is the authoritative `W15-PUB-07` tracking surface.

## Current Files

- [OpenAI review status](OPENAI_REVIEW.md)
- [Anthropic review status](ANTHROPIC_REVIEW.md)
- [Launch gate](LAUNCH_GATE.md)
- [Evidence ledger](EVIDENCE.md)
- [Revision response checklist](REVISION_RESPONSE_CHECKLIST.md)

## Current Wave State

- `W15-PUB-01`: complete
- `W15-PUB-02`: complete
- `W15-PUB-03`: complete
- `W15-PUB-04`: complete
- `W15-PUB-05`: complete
- `W15-PUB-06`: complete
- `W15-PUB-07`: complete

## What "Done" Means For W15-PUB-07

- the review trackers exist and are structured for case tracking
- the evidence ledger exists and can hold approval artifacts
- the revision response checklist exists
- the launch gate record exists

External submission and approval events still happen after task closure; those
events update these trackers and close gates `G3`, `G4`, and `G5`.

## Current Live Baseline

- Public publication/legal pages are live on `https://mcp.agentmemorylabs.com`.
- Public health is live on `https://mcp.agentmemorylabs.com/health`.
- Managed backend health and onboarding are live on
  `https://backend.agentmemorylabs.com`.
- The public MCP mounts are currently auth-gated with a dedicated reviewer key
  path via `AM_SERVER_PUBLIC_MCP_API_KEYS`.

## Shared Outstanding Items

- Implement OAuth 2.0 authorization code flow in `am-server`.
- Run real ChatGPT and Claude validation loops against the live public MCP
  surfaces and capture screenshots/examples.
- Finalize reviewer/demo/test packet materials and key-rotation plan.
- Record real OpenAI and Anthropic submission evidence.
