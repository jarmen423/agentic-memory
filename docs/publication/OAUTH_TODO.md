# OAuth Execution Setup

Last updated: 2026-04-17
Owner: publication orchestrator

This file is the human-readable entrypoint for finishing OAuth on the public MCP
publication path.

It is not the task registry.

The execution source of truth for OAuth work lives in:

- `.planning/execution-oauth/README.md`
- `.planning/execution-oauth/ROADMAP.md`
- `.planning/execution-oauth/tasks.json`

## Goal

Finish a truthful OAuth 2.0 authorization code flow for the hosted public MCP
surfaces so `mcp.agentmemorylabs.com` can move from reviewer-key preflight to
real authenticated marketplace publication.

Primary target surfaces:

- `https://mcp.agentmemorylabs.com/mcp-openai`
- `https://mcp.agentmemorylabs.com/mcp-claude`

Secondary impact surfaces:

- `/health/onboarding`
- publication/reviewer docs
- reviewer/demo account packet
- live submission evidence

## Current starting point

Already true:

- public MCP mounts are live
- public legal/publication pages are live
- `am-server` is live on the GCP VM
- current public reviewer auth is bearer key via `AM_SERVER_PUBLIC_MCP_API_KEYS`
- OAuth metadata, authorization, and token endpoints now exist in `src/am_server/routes/oauth.py`
- product-state persistence now stores OAuth users, authorization codes, access tokens, and refresh tokens
- public MCP can now accept issued OAuth access tokens when `AM_SERVER_PUBLIC_OAUTH_ENABLED=1`

Not yet true:

- the reviewer/demo packet and platform-specific submission docs still need a final OAuth-first pass
- no production OAuth validation evidence exists

## Required implementation outcome

Done means all of these are true:

- `am-server` exposes real OAuth authorization-code-flow endpoints and state handling
- public MCP auth can use OAuth-backed identity instead of only env-backed static keys
- callback allowlists and redirect handling are explicit and tested
- token/session expiry and refresh behavior are handled clearly
- `/health/onboarding` and publication docs describe deployed auth truthfully
- ChatGPT and Claude validation evidence exists against the live OAuth-enabled flow

## Wave map

### Wave O0: Orchestrator lock

Create and lock the dedicated OAuth execution registry.

### Wave O1: Contract lock

Lock the OAuth architecture before parallel implementation starts:

- auth strategy boundaries
- persistence model
- callback surface
- reviewer/demo identity model
- fallback policy

### Wave O2: Parallel implementation

Parallel tracks only after the contract is stable:

- backend auth core
- OAuth HTTP routes and state handling
- product-store / identity persistence
- docs and reviewer packet prep

### Wave O3: Integration

Reconnect the parallel tracks into:

- public MCP auth path
- health/onboarding truth
- publication docs
- status/evidence docs

### Wave O4: Validation

Run:

- automated auth regressions
- live backend verification
- ChatGPT validation
- Claude validation

## Immediate next task

Finish the live validation and submission-evidence work:

- run real ChatGPT validation against the hosted OAuth-enabled flow
- run real Claude validation against the hosted OAuth-enabled flow
- attach screenshots/examples and update `docs/publication/status/*`
