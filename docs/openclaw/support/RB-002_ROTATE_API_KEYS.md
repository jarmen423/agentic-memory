# RB-002 Rotate OpenClaw Beta API Keys

## Trigger

- scheduled key rotation
- suspected key exposure
- operator accidentally shared a token

## Objective

Rotate the backend bearer token without breaking every installed plugin at once.

## Repo-Grounded Assumption

The backend accepts `AM_SERVER_API_KEYS`, so rotation can be done with overlap
instead of a hard cutover.

## Procedure

1. Add a new key to `AM_SERVER_API_KEYS` while keeping the old key present.
2. Restart the backend so the new key is active.
3. Verify both old and new keys still work during the transition window:
   - `curl -H "Authorization: Bearer <old>" http://127.0.0.1:8765/metrics`
   - `curl -H "Authorization: Bearer <new>" http://127.0.0.1:8765/metrics`
4. Re-run plugin doctor first for operators that should move to the new key:
   - `openclaw agentic-memory doctor --backend-url http://127.0.0.1:8765`
5. Re-run plugin setup after doctor passes:
   - `openclaw agentic-memory setup --backend-url http://127.0.0.1:8765`
6. After the rollout window, remove the old key from `AM_SERVER_API_KEYS`.
7. Restart the backend again and verify only the new key works.

## Validate

- `/metrics` accepts the new key
- OpenClaw memory search still works after setup refresh
- no partner remains on the retired key

## Current Beta Limitation

- there is no central key-management UI in this beta
- rotation is still an operator runbook, not a product workflow
