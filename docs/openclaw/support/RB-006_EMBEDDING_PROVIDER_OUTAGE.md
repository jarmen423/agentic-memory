# RB-006 Embedding Provider Outage

## Trigger

- provider auth errors
- provider rate limits
- repeated embedding failures during ingest/search workflows

## Objective

Keep the beta usable enough to continue operator validation while the provider
path is degraded.

## What To Verify

- provider keys are still present in the backend environment
- `/health` is still up
- `/openclaw/health/detailed` reflects backend status
- `/metrics` shows whether request errors are rising

## Operator Impact

During provider trouble, the likely user-visible effects are:

- degraded search quality
- slower ingest/search behavior
- failed semantic enrichment

The exact behavior depends on which pipeline path is affected.

## Immediate Actions

1. Confirm the issue is provider-side rather than basic backend auth.
2. Keep the backend reachable so operators can still validate non-provider
   surfaces like health, setup, and project commands.
3. Tell active partners the environment is in degraded mode and that semantic
   quality may be reduced.
4. Pause onboarding of new partners until the provider path is stable again.

## Escalate When

- multiple partners are degraded at once
- provider failures persist long enough to block the beta schedule
- search quality becomes unusable for the intended workflows

## Follow-Up

Record:

- provider involved
- start and end times
- impacted partners
- whether a fallback path existed in practice for that incident
