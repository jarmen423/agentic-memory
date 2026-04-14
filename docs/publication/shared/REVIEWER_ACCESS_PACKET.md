# Reviewer Access Packet

Current as of April 14, 2026.

This document is the operator checklist for preparing authenticated reviewer
access to the currently deployed public MCP surfaces.

## Current live auth posture

The live preflight/reviewer path today is:

- transport
  - streamable HTTP
- auth
  - bearer API key on the public MCP surface
- env var
  - `AM_SERVER_PUBLIC_MCP_API_KEYS`

This is the truthful live state for dry runs and reviewer packet prep.

It is not the same thing as marketplace-ready OAuth.

## Publication honesty

Current blocker for full marketplace submission:

- OAuth 2.0 authorization code flow is still not implemented

That means:

- use this packet for internal dry runs and reviewer-style validation now
- do not claim OAuth-backed production publication is finished until that
  implementation exists and is validated

## One supported key split

- `AM_SERVER_API_KEYS`
  - backend/operator/OpenClaw auth
- `AM_SERVER_PUBLIC_MCP_API_KEYS`
  - dedicated public MCP reviewer key
- `AM_SERVER_INTERNAL_MCP_API_KEYS`
  - optional internal/full-surface key if you later want to separate it too

Recommended current setup:

- keep `AM_SERVER_API_KEYS` unchanged
- set one dedicated value in `AM_SERVER_PUBLIC_MCP_API_KEYS`
- leave `AM_SERVER_INTERNAL_MCP_API_KEYS` blank unless you need it

## Reviewer packet contents

Prepare one packet per review cycle containing:

- product name
  - `Agentic Memory`
- public endpoints
  - `https://mcp.agentmemorylabs.com/mcp-openai`
  - `https://mcp.agentmemorylabs.com/mcp-claude`
  - `https://mcp.agentmemorylabs.com/mcp-codex`
- auth type
  - `Bearer API key`
- reviewer public MCP key
  - one value from `AM_SERVER_PUBLIC_MCP_API_KEYS`
- legal/support URLs
  - `https://mcp.agentmemorylabs.com/publication/agentic-memory`
  - `https://mcp.agentmemorylabs.com/publication/privacy`
  - `https://mcp.agentmemorylabs.com/publication/terms`
  - `https://mcp.agentmemorylabs.com/publication/support`
- sample prompts / examples
  - platform-specific prompt packs from the OpenAI and Anthropic docs

## Validation command

The public MCP mounts are streamable HTTP endpoints, not human-readable web
pages. Use raw `curl` only to smoke-test the auth gate. Use ChatGPT or Claude
for the real reviewer validation.

First verify the missing-key path still fails:

```bash
curl -i https://mcp.agentmemorylabs.com/mcp-openai
```

Then verify that a valid reviewer key changes the auth result:

```bash
curl -i -H "Authorization: Bearer <public-mcp-reviewer-key>" \
  https://mcp.agentmemorylabs.com/mcp-openai
```

Also verify:

```bash
curl https://mcp.agentmemorylabs.com/publication/agentic-memory
curl https://mcp.agentmemorylabs.com/health
```

Expectations:

- missing key should return `401`
- keyed request should stop failing as `auth_missing_api_key`, but may still
  return redirects or transport-specific responses that are not meaningful to a
  human reader

## Rotation

- keep reviewer keys separate from operator keys
- rotate `AM_SERVER_PUBLIC_MCP_API_KEYS` without changing `AM_SERVER_API_KEYS`
- remove old public reviewer keys after the review window closes
