# Cloudflare Public MCP Deployment

This runbook is the new operator path for making the public MCP surfaces
reviewable on a real public hostname without migrating the full backend runtime
into Cloudflare on day one.

## What this deploys

- a Cloudflare Worker edge layer
- a public hostname in front of the existing Agentic Memory backend
- the reviewable public paths:
  - `/publication/agentic-memory`
  - `/publication/privacy`
  - `/publication/terms`
  - `/publication/support`
  - `/publication/dpa`
  - `/mcp-openai`
  - `/mcp-codex`
  - `/mcp-claude`

This is intentionally an edge/proxy deployment first.

The existing backend remains the system of record for:

- MCP tool execution
- public publication pages
- auth and future OAuth work
- ingestion and search behavior

## Current live deployment snapshot

Verified on 2026-04-14:

- backend origin
  - `https://backend.agentmemorylabs.com`
- public reviewer host
  - `https://mcp.agentmemorylabs.com`
- public checks
  - `/publication/agentic-memory` -> `200`
  - `/publication/privacy` -> `200`
  - `/health` -> `200`
  - `/mcp-openai` without a key -> `401`

The checked-in Worker config is now aligned with this hostname and rewrites
backend-origin redirects back to the public host.

## One supported operator path

1. Deploy the existing backend on the GCP VM and publish
   `https://backend.agentmemorylabs.com` through Cloudflare Tunnel.
   - use [Backend deployment](BACKEND_DEPLOYMENT.md) for that path
2. Deploy the Cloudflare Worker from `deploy/cloudflare-public-edge/`.
3. Bind the reviewer-facing public subdomain to that Worker.
4. Set `AM_PUBLIC_BASE_URL` in the backend to the final public URL.
5. Re-validate the publication pages and `/mcp-openai` and `/mcp-claude`.

The checked-in Worker config now declares `mcp.agentmemorylabs.com` as a
Cloudflare custom domain, so a successful deploy should attach that hostname in
the same Cloudflare account as the zone.

## Required values

- `BACKEND_ORIGIN`
  - HTTPS origin for the existing backend, for example `https://backend.agentmemorylabs.com`
- `PUBLIC_BASE_URL`
  - external reviewer-facing base URL, for example `https://mcp.agentmemorylabs.com`
- Cloudflare account with Workers deploy access
- custom domain or subdomain you control

## Local validation

From `D:\code\agentic-memory\deploy\cloudflare-public-edge`:

```bash
npm install
npm run check
```

Then deploy:

```bash
npm run deploy
```

## GitHub Actions secrets

The manual deploy workflow expects:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

And these environment variables or workflow inputs:

- `backend_origin`
- `public_base_url`

## First success criterion

On the Cloudflare URL or bound custom domain:

1. `GET /publication/agentic-memory` returns `200`
2. `GET /publication/privacy` returns `200`
3. `GET /health` returns `200`
4. the public MCP paths respond on the same hostname:
   - `/mcp-openai`
   - `/mcp-claude`

That is the minimum honest state before reviewer-mode validation.

## Important limits of this scaffold

- This does not implement OAuth.
- This does not make the backend Cloudflare-native.
- This does assume the backend stays on the GCP VM rather than moving into Workers.
- This does not replace the reviewer/demo account work.
- This only removes the fake-hostname assumption and gives the public MCP
  surface a reproducible Cloudflare deployment path.
