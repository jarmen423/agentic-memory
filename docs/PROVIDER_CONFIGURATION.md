# Provider Configuration

Agentic Memory now treats embedding-provider selection and extraction-provider selection as separate concerns.

## Two independent provider paths

Embedding providers are used by module retrieval and ingestion:

- `code`
- `web`
- `chat`

Extraction providers are used by:

- entity extraction
- claim extraction
- scheduler variable filling

Do not assume changing one changes the other.

## Embedding provider resolution

Live web and chat runtime factories now resolve embedding configuration from:

1. module-specific env vars
2. generic embedding env vars
3. repo config in `.codememory/config.json`
4. provider defaults

## Supported embedding providers

- `openai`
- `gemini`
- `nemotron`

## Useful embedding env vars

Global:

- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `EMBEDDING_BASE_URL`
- `EMBEDDING_API_KEY`

Module-specific:

- `WEB_EMBEDDING_PROVIDER`
- `WEB_EMBEDDING_MODEL`
- `WEB_EMBEDDING_DIMENSIONS`
- `WEB_EMBEDDING_BASE_URL`
- `WEB_EMBEDDING_API_KEY`
- `CHAT_EMBEDDING_PROVIDER`
- `CHAT_EMBEDDING_MODEL`
- `CHAT_EMBEDDING_DIMENSIONS`
- `CHAT_EMBEDDING_BASE_URL`
- `CHAT_EMBEDDING_API_KEY`
- `CODE_EMBEDDING_PROVIDER`
- `CODE_EMBEDDING_MODEL`
- `CODE_EMBEDDING_DIMENSIONS`
- `CODE_EMBEDDING_BASE_URL`
- `CODE_EMBEDDING_API_KEY`

Provider-specific auth fallbacks:

- OpenAI: `OPENAI_API_KEY`
- Gemini: `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- Nemotron: `NVIDIA_API_KEY` or `NEMOTRON_API_KEY`

## Extraction provider env vars

- `EXTRACTION_LLM_PROVIDER`
- `EXTRACTION_LLM_MODEL`
- `EXTRACTION_LLM_API_KEY`
- `EXTRACTION_LLM_BASE_URL`

Supported extraction providers:

- `groq`
- `cerebras`
- `openai`
- `gemini`

## Example: keep Groq for extraction, switch web embeddings to Nemotron

```powershell
$env:WEB_EMBEDDING_PROVIDER="nemotron"
$env:WEB_EMBEDDING_MODEL="nvidia/nv-embedqa-e5-v5"
$env:NVIDIA_API_KEY="..."
$env:EXTRACTION_LLM_PROVIDER="groq"
$env:GROQ_API_KEY="..."
```

That changes the web embedder only. Extraction stays on Groq.

## Example: switch chat embeddings to OpenAI

```powershell
$env:CHAT_EMBEDDING_PROVIDER="openai"
$env:CHAT_EMBEDDING_MODEL="text-embedding-3-large"
$env:OPENAI_API_KEY="..."
```

## Repo config example

`.codememory/config.json`:

```json
{
  "modules": {
    "code": {
      "embedding_provider": "openai",
      "embedding_model": "text-embedding-3-large",
      "embedding_dimensions": 3072
    },
    "web": {
      "embedding_provider": "gemini",
      "embedding_model": "gemini-embedding-2-preview",
      "embedding_dimensions": 3072
    },
    "chat": {
      "embedding_provider": "gemini",
      "embedding_model": "gemini-embedding-2-preview",
      "embedding_dimensions": 3072
    }
  }
}
```

## Notes

- Gemini supports non-default output dimensionality.
- OpenAI and Nemotron are treated as fixed-dimension providers in config validation.
- Nemotron support is now live in runtime factories and CLI paths, not just the base abstraction.
