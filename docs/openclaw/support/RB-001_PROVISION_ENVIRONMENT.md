# RB-001 Provision New OpenClaw Beta Environment

## Trigger

- new partner onboarding
- new internal beta environment
- environment rebuild after data wipe or drift

## Objective

Bring up a working backend environment that can support the OpenClaw plugin.

## Primary References

- `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`
- `D:\code\agentic-memory\docker-compose.prod.yml`

## Procedure

1. Prepare `.env.production` with real values for:
   - `NEO4J_USER`
   - `NEO4J_PASSWORD`
   - `AM_SERVER_API_KEYS`
   - at least one embedding/extraction provider key
2. Render the compose file before deployment:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production config`
3. Start the stack:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`
4. Validate:
   - `GET /health`
   - `GET /openclaw/health/detailed`
   - `GET /metrics`
5. Hand the operator:
   - backend URL
   - bearer token delivery method
   - install command
   - setup command

## Success Criteria

- backend responds on `/health`
- authenticated `/openclaw/health/detailed` succeeds
- authenticated `/metrics` succeeds

## If It Fails

- check env-file values
- confirm Neo4j credentials
- confirm provider keys
- fall back to the deployment runbook for compose/log inspection
