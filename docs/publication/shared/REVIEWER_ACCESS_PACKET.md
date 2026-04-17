# Reviewer Access Packet

Current as of April 14, 2026.

This document is the operator checklist for preparing authenticated reviewer
access to the currently deployed public MCP surfaces.

## Current live auth posture

The live public auth picture now has two layers:

- implemented publication auth
  - OAuth 2.0 authorization code flow with PKCE
  - enabled by `AM_SERVER_PUBLIC_OAUTH_ENABLED`
- reviewer fallback auth
  - bearer API key on the public MCP surface
  - `AM_SERVER_PUBLIC_MCP_API_KEYS`
- transport
  - streamable HTTP

This is the truthful mixed state for dry runs and reviewer packet prep:

- OAuth exists in code and can be enabled for the hosted public surface
- bearer-key reviewer fallback may still be used during rollout and review prep

## Publication honesty

Current remaining blockers for full marketplace submission:

- live ChatGPT validation evidence is still missing
- live Claude validation evidence is still missing
- reviewer/demo packet materials still need to be refreshed around the new OAuth path

That means:

- use this packet for reviewer dry runs now
- do not claim marketplace-ready OAuth publication until the hosted OAuth path is validated end to end on real clients

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
- auth types
  - `OAuth 2.0 authorization code flow`
  - `Bearer API key` reviewer fallback during rollout
- reviewer public MCP key
  - one value from `AM_SERVER_PUBLIC_MCP_API_KEYS` when using fallback auth
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

First verify the missing-auth path still fails:

```bash
curl -i https://mcp.agentmemorylabs.com/mcp-openai
```

Then verify that a valid reviewer key changes the auth result when using fallback auth:

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

- missing auth should return `401`
- keyed request should stop failing as `auth_missing_api_key`, but may still
  return redirects or transport-specific responses that are not meaningful to a
  human reader

If validating the OAuth path instead of the fallback key:

- use a real MCP client against `https://mcp.agentmemorylabs.com/mcp-openai`
- expect the public Bearer challenge to advertise
  `/.well-known/oauth-protected-resource`
- verify the client completes the authorization-code flow and reaches the tool list

## Rotation

- keep reviewer keys separate from operator keys
- rotate `AM_SERVER_PUBLIC_MCP_API_KEYS` without changing `AM_SERVER_API_KEYS`
- remove old public reviewer keys after the review window closes
