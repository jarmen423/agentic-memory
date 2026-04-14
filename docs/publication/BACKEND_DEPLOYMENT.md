# Backend Deployment

This is the operator path for creating the HTTPS backend origin that the
public Cloudflare MCP edge will proxy to.

Use this before `docs/publication/CLOUDFLARE_DEPLOYMENT.md`.

## What this deploys

- one `am-server` runtime on the existing GCP VM
- one production compose stack from `docker-compose.prod.yml` if Neo4j is reachable from Docker
- one backend origin such as `https://backend.agentmemorylabs.com`
- one Cloudflare Tunnel from the existing GCP VM to that backend origin

This backend origin is not the reviewer-facing public MCP hostname. The public
review host stays separate:

- backend origin
  - example: `https://backend.agentmemorylabs.com`
- public MCP host
  - example: `https://mcp.agentmemorylabs.com`

## Current production snapshot

Verified on 2026-04-14:

- `am-server` is currently running directly on the GCP VM under `systemd`
- the current live loopback backend is `http://127.0.0.1:8765`
- the current live Neo4j target is `bolt://127.0.0.1:7667`
- Cloudflare Tunnel publishes `https://backend.agentmemorylabs.com`
- the Cloudflare Worker fronts `https://mcp.agentmemorylabs.com`

That direct-VM path is the truthful current production deployment. Compose
remains useful for alternate operator setups, but it is not the live path
today.

## One supported operator path

1. Use the existing GCP VM that already hosts Neo4j.
2. If Neo4j is loopback-only on that VM, run `am-server` directly under
   `systemd` using the checked-in templates; only use Compose when Neo4j is
   reachable from Docker.
3. Verify `/health` and `/health/onboarding` locally on the VM.
4. Publish `backend.agentmemorylabs.com` through Cloudflare Tunnel from that VM.
5. Put the public Worker in front of that backend only after the backend is healthy.

## Files used

- `D:\code\agentic-memory\docker-compose.prod.yml`
- `D:\code\agentic-memory\.env.production.example`
- `D:\code\agentic-memory\.github\workflows\backend-release.yml`
- `D:\code\agentic-memory\deploy\systemd\am-server.service.example`
- `D:\code\agentic-memory\deploy\systemd\am-server.env.example`

## Required environment values

Start from `.env.production.example` and replace placeholders.

The minimum honest production values are:

- `NEO4J_URI`
  - if Neo4j is reachable from Docker on the VM host, use `bolt://host.docker.internal:<bolt-port>`
- `NEO4J_PASSWORD`
- `AM_SERVER_API_KEYS`
- `AGENTIC_MEMORY_DEPLOYMENT_MODE=managed`
- `AGENTIC_MEMORY_HOSTED_BASE_URL`
  - your backend HTTPS origin
- `AM_PUBLIC_BASE_URL`
  - your reviewer-facing public MCP host
- at least one provider API key

## GitHub Actions path

Run the manual workflow:

- workflow: `backend-release`
- input `image_tag`
  - for example `2026-04-14` or `beta-1`
- input `publish_to_ghcr`
  - set to `true` when you want GHCR to host the image

What it does:

1. validates the publication contract tests
2. renders `docker-compose.prod.yml` against `.env.production.example`
3. builds the backend container image
4. optionally pushes to GHCR as:
   - `ghcr.io/<owner>/agentic-memory-am-server:<tag>`

## Compose deployment alternative

On the existing GCP VM:

```bash
cp .env.production.example .env.production
docker compose -f docker-compose.prod.yml --env-file .env.production config
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build am-server
```

Use this only when Neo4j is reachable from Docker on the VM host.

If you publish to GHCR and want to switch compose to a pulled image instead of
local build, update the `am-server` service image line during deployment.

## Neo4j modes

Compose-friendly variant:

- existing Neo4j on the VM
  - if Neo4j is reachable from Docker, set `NEO4J_URI=bolt://host.docker.internal:<bolt-port>`
  - start only `am-server`

Fallback if you ever want the stack to provision its own graph:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production --profile bundled-neo4j up -d --build
```

That bundled path expects:

- `NEO4J_URI=bolt://neo4j:7687`

## Loopback-only Neo4j

If your current VM Neo4j only listens on `127.0.0.1:<bolt-port>`, the safer path is
to run `am-server` directly on the VM instead of in Docker:

```bash
export NEO4J_URI=bolt://127.0.0.1:<bolt-port>
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=replace-with-real-password
export AM_SERVER_API_KEYS=replace-with-real-rest-key
export AGENTIC_MEMORY_DEPLOYMENT_MODE=managed
export AGENTIC_MEMORY_HOSTED_BASE_URL=https://backend.agentmemorylabs.com
export AM_PUBLIC_BASE_URL=https://mcp.agentmemorylabs.com
python -m am_server.server
```

That avoids Docker host-network edge cases entirely and matches the current
live production deployment.

## systemd persistence

Once the direct VM launch is healthy, switch to the checked-in `systemd`
templates:

- service unit:
  - `deploy/systemd/am-server.service.example`
- env file:
  - `deploy/systemd/am-server.env.example`

Current target shape baked into the env example:

- `AM_SERVER_HOST=127.0.0.1`
- `AM_SERVER_PORT=8765`
- `NEO4J_URI=bolt://127.0.0.1:7667`
- `AGENTIC_MEMORY_HOSTED_BASE_URL=https://backend.agentmemorylabs.com`
- `AM_PUBLIC_BASE_URL=https://mcp.agentmemorylabs.com`

Install flow on the VM:

```bash
sudo mkdir -p /etc/agentic-memory
sudo cp deploy/systemd/am-server.env.example /etc/agentic-memory/am-server.env
sudo cp deploy/systemd/am-server.service.example /etc/systemd/system/am-server.service
sudo editor /etc/agentic-memory/am-server.env
sudo editor /etc/systemd/system/am-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now am-server
sudo systemctl status am-server
```

After the service starts, re-check:

```bash
curl https://backend.agentmemorylabs.com/health
curl https://backend.agentmemorylabs.com/health/onboarding
```

## Cloudflare Tunnel step

After the backend is healthy on the VM, publish it with `cloudflared` so
Cloudflare can reach it without opening the VM broadly to the internet.

Target shape:

- local backend on VM
  - `http://127.0.0.1:8765`
- Cloudflare Tunnel hostname
  - `https://backend.agentmemorylabs.com`
- public Worker hostname
  - `https://mcp.agentmemorylabs.com`

The backend hostname is the `BACKEND_ORIGIN` value for the public Worker.

## First success criterion

On the backend origin:

1. `GET /health` returns `200`
2. `GET /health/onboarding` returns `200`
3. `GET /publication/agentic-memory` returns `200`
4. authenticated `GET /openclaw/health/detailed` returns `200`

Do not put the public Worker in front of the stack until those four checks pass.

## Important notes

- `docker-compose.prod.yml` now passes `AGENTIC_MEMORY_DEPLOYMENT_MODE`,
  `AGENTIC_MEMORY_HOSTED_BASE_URL`, and `AM_PUBLIC_BASE_URL` into `am-server`.
  Without that, the managed/public contract is misreported even if the env file
  contains the values.
- The supported path now assumes the existing GCP VM is the backend host.
- The repo still does not provision the VM or Cloudflare Tunnel for you.
  This document makes the runtime contract explicit so those operator steps are
  unambiguous.
