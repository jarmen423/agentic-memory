"""Entity extraction service using provider-configurable JSON mode.

Provides EntityExtractionService for extracting named entities from document text,
and build_embed_text for prepending entity context to chunk text before embedding.
"""

import json
import logging
from typing import Any

from agentic_memory.core.extraction_llm import (
    build_extraction_openai_client,
    resolve_extraction_llm_config,
)

logger = logging.getLogger(__name__)

ENTITY_EXTRACTION_PROMPT = """\
Extract named entities from the following text.
Return a JSON object with key "entities" containing a list of objects,
each with "name" (string) and "type" (one of: {allowed_types}).
Only extract entities clearly present in the text.
Do not invent entities. If no entities found, return {{"entities": []}}."""


class EntityExtractionService:
    """LLM-based entity extraction using an OpenAI-compatible JSON mode client.

    Makes one extraction call per document (not per chunk). Uses
    response_format={"type": "json_object"} and temperature=0.0 for
    deterministic structured output.

    Args:
        api_key: Provider API key.
        model: Model name to use for extraction.
        provider: Extraction provider name.
        base_url: Optional OpenAI-compatible base URL override.
        allowed_types: Entity types to extract. Defaults to core taxonomy.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        provider: str = "groq",
        base_url: str | None = None,
        allowed_types: list[str] | None = None,
    ) -> None:
        """Initialize the entity extraction service.

        Args:
            api_key: Provider API key.
            model: Provider model name. Defaults to 'llama-3.3-70b-versatile'.
            provider: Provider name. Defaults to 'groq'.
            base_url: Optional OpenAI-compatible base URL override.
            allowed_types: List of entity type strings to constrain extraction.
                Defaults to ['project', 'person', 'business', 'technology', 'concept'].
        """
        resolved = resolve_extraction_llm_config(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        self._client = build_extraction_openai_client(resolved)
        self.api_key = resolved.api_key or api_key
        self.provider = resolved.provider
        self.model = resolved.model
        self.base_url = resolved.base_url
        self.allowed_types = allowed_types or [
            "project",
            "person",
            "business",
            "technology",
            "concept",
        ]

    @classmethod
    def from_env(
        cls,
        *,
        allowed_types: list[str] | None = None,
    ) -> "EntityExtractionService":
        """Build an extractor from the env-driven extraction LLM configuration."""
        resolved = resolve_extraction_llm_config()
        return cls(
            api_key=resolved.api_key or "",
            model=resolved.model,
            provider=resolved.provider,
            base_url=resolved.base_url,
            allowed_types=allowed_types,
        )

    def extract(self, document_text: str) -> list[dict[str, str]]:
        """Extract named entities from a document.

        Makes one LLM call using JSON mode. Truncates input to 8000 chars
        as a budget guard. Filters entities whose type is not in allowed_types.
        Falls back to first list value if JSON key is not "entities" (Pitfall 4).

        Args:
            document_text: The document to extract entities from. Truncated to 8000 chars.

        Returns:
            List of entity dicts, each with 'name' and 'type' keys.
        """
        prompt = ENTITY_EXTRACTION_PROMPT.format(
            allowed_types=", ".join(self.allowed_types)
        )
        # Budget guard: truncate to first 8000 characters (per RESEARCH.md)
        truncated_text = document_text[:8000]

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": truncated_text},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        data: dict[str, Any] = json.loads(response.choices[0].message.content)

        # Primary key lookup — if missing, scan values for first list (Pitfall 4 fallback)
        entities = data.get("entities")
        if entities is None:
            entities = next(
                (v for v in data.values() if isinstance(v, list)),
                [],
            )

        # Filter to only allowed entity types for consistency
        filtered: list[dict[str, str]] = [
            {"name": e["name"], "type": e["type"]}
            for e in entities
            if isinstance(e, dict) and e.get("type") in self.allowed_types
        ]

        logger.debug(
            "Extracted %d entities from document (%d chars)",
            len(filtered),
            len(truncated_text),
        )
        return filtered


def build_embed_text(chunk_text: str, entities: list[dict[str, str]]) -> str:
    """Prepend entity context to chunk text before embedding.

    Entity-enriched embedding makes semantically related chunks cluster in
    vector space even when wording differs (per CONTEXT.md locked decision).

    Args:
        chunk_text: The text chunk to embed.
        entities: List of entity dicts with 'name' and 'type' keys.

    Returns:
        If entities is empty, returns chunk_text unchanged.
        Otherwise returns 'Context: {entity_str}\\n\\n{chunk_text}'.
    """
    if not entities:
        return chunk_text
    entity_str = ", ".join(f"{e['name']} ({e['type']})" for e in entities)
    return f"Context: {entity_str}\n\n{chunk_text}"
