# Auth and Reachability Checklist

This checklist captures the Anthropic-specific network and auth requirements that are easy to get wrong during directory review.

## Current live reviewer dry run

The live public reviewer path today is:

- bearer API key via `AM_SERVER_PUBLIC_MCP_API_KEYS`

That is the truthful current dry-run state. The checklist below still covers the
remaining publication target and alternative paths.

## Chosen public auth posture

The marketplace publication target for authenticated public surfaces is:

- `OAuth 2.0 authorization code flow`

This is the only truthful path for a multi-user memory product that needs user identity, reviewer login support, and future rate limiting across OpenAI and Anthropic surfaces.

## Other supported auth postures

### Option 1: No auth

- Best for low-risk public data and simplest cross-surface compatibility.
- No OAuth setup required.
- Global abuse prevention and rate limiting still need to exist.

### Option 2: OAuth 2.0 authorization code flow

- Required if the connector needs authentication.
- Preferred for per-user identity and rate limiting.
- Must work on Claude.ai and Claude Desktop.
- Should be tested with Claude Code if Claude Code support is claimed.

### Option 3: IP allowlisting without OAuth

- Not preferred.
- May work for Claude.ai and Claude Desktop if Anthropic IP ranges are allowlisted.
- Does not support Claude Code.
- Should not be described as a full multi-surface solution.

## Unsupported or risky patterns

- Pure machine-to-machine OAuth client credentials flow as the only auth method.
- Reviewer login requiring MFA, VPN, or manual intervention.
- Private-network-only endpoints.
- Firewall rules that permit Anthropic cloud traffic but block direct Claude Code connections while still claiming Claude Code support.

## OAuth callback checklist

If OAuth is used, allowlist:

- `http://localhost:6274/oauth/callback`
- `http://localhost:6274/oauth/callback/debug`
- `https://claude.ai/api/mcp/auth_callback`
- `https://claude.com/api/mcp/auth_callback`

Also verify:

- invalid redirect URI errors are resolved
- HEAD requests without tokens are handled gracefully
- token refresh and expired-session behavior are understandable

## Public reachability checklist

- `https://mcp.agentmemorylabs.com/mcp-claude` is reachable from a network outside VPN/internal corp infrastructure.
- TLS certificate is valid.
- CORS is configured for browser/cloud clients.
- If behind firewall, Anthropic IP ranges are allowlisted for brokered Claude surfaces.
- If Claude Code support is claimed, direct user-machine connectivity is also tested.

## Reviewer account checklist

- Test account exists and remains active.
- Sample data covers all demonstrated tools.
- Account can exercise every tool being reviewed.
- Setup instructions fit in a short step-by-step block.

## Submission truthfulness check

Do not claim support for:

- Claude Code if auth/network design prevents it
- per-user identification without OAuth
- private/internal-only services that are not publicly reachable
