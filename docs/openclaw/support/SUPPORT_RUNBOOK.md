# OpenClaw Support Runbook

This runbook is the front door for support during the OpenClaw private beta.

## Support Goals

- restore a blocked operator quickly
- collect enough evidence to reproduce the problem
- distinguish install/config issues from backend incidents
- keep the first 5 design partners moving without improvising the process

## Severity Model

- `SEV-1`
  - onboarding blocked for all operators
  - backend unavailable
  - widespread auth failure
- `SEV-2`
  - one partner blocked from normal usage
  - repeated empty-result or ingest failures
- `SEV-3`
  - workaround exists
  - docs confusion or single-command failure

## First Response Checklist

Capture these facts first:

- partner name
- OpenClaw host version
- plugin package version
- backend URL host
- mode:
  - `capture_only`
  - `augment_context`
- approximate failure timestamp
- last successful action
- exact command the operator ran
- any `request_id` returned in the backend error envelope

## Required Diagnostics

Ask for:

- output from:
  - `curl http://127.0.0.1:8765/health`
  - `curl -H "Authorization: Bearer replace-with-real-rest-key" http://127.0.0.1:8765/openclaw/health/detailed`
  - `curl -H "Authorization: Bearer replace-with-real-rest-key" http://127.0.0.1:8765/metrics`
- relevant backend logs around the incident timestamp
- OpenClaw command output or screenshot

Current beta limitation:

- there is no repo-documented one-click support bundle export yet
- support evidence is still collected manually

## Top-5 Failure Modes

Route incidents like this:

1. install or package resolution failure
   - start with `D:\code\agentic-memory\docs\TROUBLESHOOTING.md`
2. backend provisioning or environment issue
   - `D:\code\agentic-memory\docs\openclaw\support\RB-001_PROVISION_ENVIRONMENT.md`
3. auth or key-rotation issue
   - `D:\code\agentic-memory\docs\openclaw\support\RB-002_ROTATE_API_KEYS.md`
4. empty results, API failures, or search degradation
   - `D:\code\agentic-memory\docs\openclaw\support\RB-005_API_ERRORS_AND_EMPTY_RESULTS.md`
5. embedding provider outage or degraded semantic quality
   - `D:\code\agentic-memory\docs\openclaw\support\RB-006_EMBEDDING_PROVIDER_OUTAGE.md`

## Escalation Triggers

Escalate from routine support to incident handling when:

- `/health` fails
- `/metrics` cannot be read with a known-good token
- multiple partners are blocked at once
- the same issue repeats after one attempted fix

## Closure Criteria

Do not close the support thread until:

- the operator confirms the blocking action now works
- the likely root cause is recorded
- any missing docs gap is noted for follow-up
