# RB-005 API Errors And Empty Results

## Trigger

- `/openclaw/*` requests fail
- operators report empty search results
- project status or session registration breaks

## Objective

Quickly separate auth/config issues from backend/search-quality issues.

## Triage Order

1. Check liveness:
   - `curl http://127.0.0.1:8765/health`
2. Check authenticated operator health:
   - `curl -H "Authorization: Bearer replace-with-real-rest-key" http://127.0.0.1:8765/openclaw/health/detailed`
3. Check authenticated metrics:
   - `curl -H "Authorization: Bearer replace-with-real-rest-key" http://127.0.0.1:8765/metrics`

## Interpret The Failure

- `401` / `403`
  - likely token/config issue
  - route to RB-002 if rotation or token mismatch is involved
- `/health` fails
  - environment-level incident
  - route to RB-001 / deployment runbook
- health succeeds but search is empty
  - confirm:
    - session registration happened
    - turn ingestion happened
    - the partner is searching the expected workspace/agent/session context

## Empty-Result Checklist

Confirm the operator has:

- run setup against the correct backend URL
- used the expected token
- generated at least one ingested turn before expecting recall
- not switched identities unexpectedly:
  - workspace
  - device
  - agent

## Diagnostics To Capture

- failing command
- error payload including `request_id`
- health output
- time of the first empty result
- whether the problem affects:
  - search only
  - ingest only
  - both

## Recovery

- if auth is wrong, re-run setup
- if backend is unhealthy, recover the environment first
- if ingestion is not happening, validate the OpenClaw session path before
  debugging search quality
