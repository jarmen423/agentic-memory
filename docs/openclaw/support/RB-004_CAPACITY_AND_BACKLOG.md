# RB-004 Capacity Pressure And Backlog Handling

## Trigger

- rising ingest latency
- repeated backend timeouts
- signs of Neo4j pool exhaustion

## Objective

Stabilize the beta environment when load or backlog pressure grows.

## Current Beta Limitation

The current beta build does not yet expose a dedicated async ingest queue or a
documented horizontal autoscaling surface in this repo.

That means backlog handling is operational and observational, not automated.

## What To Check

- `/openclaw/health/detailed`
  - backend component status
  - Neo4j pool details if present
- `/metrics`
  - request and error counters
  - ingest/search latency trends

## Immediate Mitigations

1. Pause new partner onboarding until the environment stabilizes.
2. Reduce concurrent operator activity if multiple partners share one backend.
3. Restart `am-server` if the process is unhealthy but Neo4j is still healthy.
4. Restart the full stack if both backend and Neo4j health are degraded.

## Escalate When

- `/health` is healthy but `/openclaw/health/detailed` shows repeated backend
  degradation
- request errors continue after a clean restart
- multiple partners hit search or ingest latency at the same time

## Follow-Up

Record:

- number of affected partners
- observed latencies/errors
- whether the issue looked search-heavy, ingest-heavy, or auth-related
