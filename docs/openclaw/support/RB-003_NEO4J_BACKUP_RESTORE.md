# RB-003 Neo4j Backup And Restore

## Trigger

- scheduled backup
- data-loss concern
- environment migration

## Objective

Protect the Neo4j state behind the OpenClaw beta backend.

## Current Beta Reality

The current repo ships a Docker Compose deployment path. This runbook therefore
assumes Docker-volume backups unless the operator already has a stronger
platform-native backup process.

## Backup Procedure

1. Stop write-heavy activity if possible.
2. Stop the stack cleanly:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production down`
3. Back up the named Neo4j volumes using the operator's standard Docker-volume
   backup process.
4. Restart the stack:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production up -d`
5. Validate:
   - `/health`
   - `/openclaw/health/detailed`

## Restore Procedure

1. Stop the stack.
2. Restore the Neo4j volumes from the chosen backup snapshot.
3. Start the stack again.
4. Verify:
   - `/health`
   - `/openclaw/health/detailed`
   - a known memory search returns expected data

## Notes

- keep backup timing and restore timing in operator notes
- if the environment uses a different Neo4j hosting model, follow the
  platform-native backup/restore process instead of forcing Docker-volume steps
