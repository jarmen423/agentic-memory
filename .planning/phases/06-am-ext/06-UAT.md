---
status: partial
phase: 06-am-ext
source:
  - 06-01-SUMMARY.md
  - 06-02-SUMMARY.md
  - 06-03-SUMMARY.md
  - 06-04-SUMMARY.md
started: 2026-03-25T23:16:31.8571563Z
updated: 2026-03-25T23:50:00.0000000Z
---

## Current Test

[testing paused - 5 items outstanding]

## Tests

### 1. Install + Onboarding
expected: Load the unpacked extension from `packages/am-ext/` in Chrome with Developer mode enabled. The onboarding page should open automatically on first install. Using `http://localhost:8000`, a valid API key, and the default `browser` project id, clicking `Test Connection` should show a green `Connected` status. All four platform checkboxes should be enabled by default, and clicking `Save` should show `Settings saved.`. The full onboarding flow should complete in under 2 minutes and leave the extension ready to capture.
result: pass

### 2. ChatGPT Turn Capture
expected: On `chatgpt.com` or `chat.openai.com`, after sending a prompt and waiting for the assistant response to finish rendering, Neo4j should contain at least one `Turn` node with `source_key = 'browser_ext_chatgpt'` and populated `role`, `content`, and `session_id` properties for that conversation.
result: blocked
blocked_by: server
reason: "Deferred by user for later verification because the Neo4j instance backing am-server is not confirmed in the current setup."

### 3. Debounced Streaming Capture
expected: On a visibly streaming response in ChatGPT or Claude, no duplicate partial assistant turns should be stored while tokens stream. After the response fully settles, exactly one completed assistant turn should be stored for that response.
result: skipped
reason: "Deferred by user to continue system architecture work before more manual browser verification."

### 4. Platform Disable Toggle
expected: After disabling ChatGPT capture in onboarding or the popup and saving the setting, sending a new ChatGPT message should not ingest any new turns for that platform until it is re-enabled.
result: [pending]

### 5. Global Pause Toggle
expected: On a supported platform page, opening the popup and clicking `Pause` should change the popup status to `Paused`. While paused, sending prompts on supported platforms should not ingest new turns.
result: [pending]

### 6. Memory Server Unreachable
expected: If `am-server` is stopped or unreachable, supported chat pages should continue working normally and the extension should fail silently without surfacing user-facing errors.
result: [pending]

### 7. Selector Hotpatch
expected: After editing `src/am_server/data/selectors.json` while `am-server` is running and then reloading or revisiting a supported chat page, capture behavior should reflect the updated selector set without reinstalling the extension.
result: [pending]

### 8. SPA Navigation Session Reset
expected: On `claude.ai`, starting a new chat in the same browser tab should reset capture state. New turns should be stored under a new `session_id` and should not duplicate turns from the previous conversation.
result: [pending]

## Summary

total: 8
passed: 1
issues: 0
pending: 5
skipped: 1
blocked: 1

## Gaps
