# am-ext Manual Acceptance Checklist

Use this checklist after loading the extension in a browser. Each section maps to a Phase 6 success criterion and includes the expected outcome for the check.

## 1. Install + Onboarding

- [ ] Open `chrome://extensions`, enable **Developer mode**, and load the unpacked extension from `packages/am-ext/`.
- [ ] Verify the onboarding page opens automatically on first install.
- [ ] Enter `http://localhost:8000` as the endpoint, provide a valid API key, and keep the default `browser` project ID unless you need a different one.
- [ ] Click **Test Connection** and verify the status changes to green `Connected`.
- [ ] Verify the ChatGPT, Claude, Gemini, and Perplexity checkboxes are all enabled by default.
- [ ] Click **Save** and verify the `Settings saved.` message appears.

Expected outcome: the full onboarding flow completes in under 2 minutes and leaves the extension ready to capture.

## 2. ChatGPT Capture

- [ ] Navigate to `https://chatgpt.com/` or `https://chat.openai.com/` and open an existing conversation or start a new one.
- [ ] Send a prompt and wait for the assistant response to finish rendering.
- [ ] Query Neo4j with `MATCH (t:Turn) WHERE t.source_key = 'browser_ext_chatgpt' RETURN t LIMIT 5`.
- [ ] Inspect at least one returned node for populated `role`, `content`, and `session_id` properties.

Expected outcome: ChatGPT turns appear in Neo4j with the expected source key and conversation metadata.

## 3. Debounce Timing

- [ ] On ChatGPT or Claude, send a prompt that triggers a visibly streaming response.
- [ ] While the response is still streaming, check Neo4j every few seconds for new `Turn` nodes from that platform.
- [ ] After the response fully settles, query again for the latest turn.

Expected outcome: the debounce behavior produces exactly one stored assistant turn per completed response, not one turn per token batch.

## 4. Platform Disable Toggle

- [ ] Open onboarding or the popup and disable ChatGPT capture, then save the settings.
- [ ] Send a new message on ChatGPT after the setting is saved.
- [ ] Query Neo4j for new turns from the same ChatGPT session.

Expected outcome: no new turns are ingested for the disabled platform until it is re-enabled.

## 5. Global Pause Toggle

- [ ] Open the extension popup on a supported platform page.
- [ ] Click **Pause** and confirm the popup status changes to `Paused`.
- [ ] Send a prompt on any supported platform while the global pause state is active.

Expected outcome: no new turns are ingested while global pause is enabled, and the popup continues to show the paused state.

## 6. Memory Server Unreachable

- [ ] Stop `am-server` so the configured endpoint is unreachable.
- [ ] Send a message in ChatGPT or Claude with the extension still enabled.
- [ ] Watch the page for visible errors and, if you inspect the extension worker console, watch for uncaught extension errors.

Expected outcome: the chat UI continues normally, the extension fails silently, and the unreachable server does not surface user-facing breakage.

## 7. Selector Hotpatch

- [ ] Edit `src/am_server/data/selectors.json` while `am-server` is running.
- [ ] Navigate away from and back to a supported platform page, or reload the page, so the content script starts again.
- [ ] Validate capture behavior using the updated selector set.

Expected outcome: the selector hotpatch takes effect without reinstalling or updating the browser extension package.

## 8. SPA Navigation

- [ ] On `https://claude.ai/`, finish one conversation and then create a new chat within the same browser tab.
- [ ] Send prompts in the new conversation.
- [ ] Query Neo4j for the new turns and compare their `session_id` with the earlier conversation.

Expected outcome: SPA navigation resets capture state for the new conversation, stores turns under a new session ID, and avoids duplicate turns from the earlier chat.
