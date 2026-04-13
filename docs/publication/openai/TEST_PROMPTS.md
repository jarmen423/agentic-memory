# OpenAI Reviewer Test Prompts

Current as of April 12, 2026.

These prompts are designed to match the frozen public contract on `/mcp-openai`. Expected responses are intentionally high-level so the packet stays stable across minor implementation changes while still giving reviewers something concrete to validate.

## 1. Code search

- Prompt: `Search this codebase for the hosted public MCP surfaces and tell me where the OpenAI-facing endpoint is defined.`
- Expected primary tool: `search_codebase`
- Pass criteria:
  - Response identifies the public MCP surface implementation and/or profile definitions.
  - Response mentions `/mcp-openai`.
  - Response does not expose internal-only tools.

## 2. File dependency lookup

- Prompt: `Show the dependencies for src/am_server/app.py and summarize what that file is responsible for.`
- Expected primary tool: `get_file_dependencies`
- Pass criteria:
  - Response returns file dependency information for `src/am_server/app.py`.
  - Summary is grounded in the file and not generic filler.

## 3. Execution trace

- Prompt: `Trace the likely execution path starting from create_app in src/am_server/app.py.`
- Expected primary tool: `trace_execution_path`
- Pass criteria:
  - Response shows a bounded likely execution path.
  - Response stays scoped to likely execution neighbors instead of claiming a full runtime proof.

## 4. Unified memory read

- Prompt: `Search all memory for public plugin publication work and summarize the current publication tracks.`
- Expected primary tool: `search_all_memory`
- Pass criteria:
  - Response spans code, docs, or stored memory where available.
  - Summary distinguishes OpenAI, Codex preflight, and Anthropic tracks if those artifacts are present.

## 5. Conversation memory retrieval

- Prompt: `Search conversation memory for earlier discussion about the OpenAI publication plan.`
- Expected primary tool: `search_conversations`
- Pass criteria:
  - Response returns relevant prior conversation snippets or clearly says none were found.
  - Response does not fabricate prior conversations.

## 6. Explicit conversation memory write

- Prompt: `Save this note to conversation memory: "OpenAI publication smoke test note created during review."`
- Expected primary tool: `add_message`
- Pass criteria:
  - Response confirms the note was stored or clearly reports why it could not be stored.
  - Tool is treated as a write action and requires confirmation where the client enforces it.

## 7. Conversation memory read-after-write

- Prompt: `Find the note I just saved about the OpenAI publication smoke test.`
- Expected primary tools: `search_conversations`, possibly `get_conversation_context`
- Pass criteria:
  - Newly written note is retrievable.
  - Retrieval is semantically relevant and not a stale unrelated result.

## 8. Research memory write

- Prompt: `Save this research finding to memory: OpenAI app review currently uses a dashboard-based submission flow and publishing the approved app creates the Codex plugin distribution.`
- Expected primary tool: `memory_ingest_research`
- Pass criteria:
  - Response confirms a research-memory write or gives a clear validation error.
  - Write remains private to Agentic Memory state and does not imply public internet publication.

## Reviewer note

- If auth is enabled, run all prompts using the provided demo account and sample data.
- If a prompt requires seed data that is not present in the reviewer account, note that explicitly in the final packet and pre-seed the account before submission.
