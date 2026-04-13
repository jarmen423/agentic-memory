# Anthropic Usage Examples

Current as of April 12, 2026.

Anthropic requires a minimum of three working examples. These examples are written for the hosted `/mcp-claude` surface and map to the frozen public tool contract.

## Example 1: Search the codebase for MCP publication surfaces

- User prompt: `Find where the hosted public MCP surfaces are defined and tell me which endpoint is intended for Claude.`
- Likely tool path:
  - `search_codebase`
- What should happen:
  - Claude searches the codebase for public MCP definitions.
  - The response identifies the hosted public surfaces and highlights `/mcp-claude` as the Claude-facing endpoint.
  - The answer stays grounded in the repo rather than giving generic MCP advice.

## Example 2: Retrieve prior memory about publication planning

- User prompt: `Search memory for prior work on public plugin publication and summarize the Claude-related track.`
- Likely tool path:
  - `search_all_memory`
  - optionally `search_conversations`
- What should happen:
  - Claude retrieves prior stored context relevant to publication planning.
  - The answer distinguishes the Anthropic connector track from OpenAI and Codex-preflight work.
  - If no relevant memory exists, the response says so clearly instead of fabricating prior context.

## Example 3: Save a research finding to memory

- User prompt: `Save this finding to memory: Anthropic directory review requires tool safety annotations on every public tool and at least three usage examples in the documentation.`
- Likely tool path:
  - `memory_ingest_research`
- What should happen:
  - Claude asks for confirmation if the client enforces write approval.
  - The service stores the finding in Agentic Memory's private backend state.
  - The response confirms success or returns a clear validation error.

## Example 4: Save and retrieve a conversation-memory note

- User prompt: `Save this note to memory: Claude directory smoke test passed on the public MCP surface. Then help me find it later.`
- Likely tool path:
  - `add_message`
  - `search_conversations`
  - optionally `get_conversation_context`
- What should happen:
  - The note is stored as conversation memory.
  - A later search can retrieve it with a semantically relevant result.
  - The system does not imply any public posting or external side effects.

## Reviewer note

- If auth is enabled, pre-seed the reviewer account so these flows actually have sample data to operate on.
- If Claude Code is part of the support claim, verify that the chosen auth/network model works from a user machine and does not rely solely on Anthropic cloud IP allowlisting.
