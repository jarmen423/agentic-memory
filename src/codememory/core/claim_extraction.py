"""Structured claim extraction for Subject-Predicate-Object triples."""

import json
import logging
from typing import Any

from groq import Groq

logger = logging.getLogger(__name__)

DEFAULT_PREDICATES: list[str] = [
    "KNOWS",
    "WORKS_AT",
    "RESEARCHED",
    "REFERENCES",
    "USES",
    "LEADS",
    "PART_OF",
    "LOCATED_IN",
    "CREATED_BY",
    "CONTRADICTS",
]

CLAIM_EXTRACTION_PROMPT = """\
Extract factual claims from the text as Subject-Predicate-Object triples.
Return a JSON object with key "claims" containing a list of objects, each with:
  "subject": entity name (person, project, technology, business, or concept)
  "predicate": MUST be one of: {predicates}
  "object": entity name (same types as subject)
  "valid_from": ISO-8601 date if claim has a known start time, else null
  "valid_to": ISO-8601 date if claim is no longer valid, else null
  "confidence": float 0.0-1.0 for your confidence this claim is true

Use REFERENCES as catch-all if no other predicate fits.
Only extract claims clearly present in the text.
If no claims found, return {{"claims": []}}."""


class ClaimExtractionService:
    """LLM-based claim extraction using Groq JSON mode."""

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        predicates: list[str] | None = None,
    ) -> None:
        """Initialize the claim extraction service.

        Args:
            api_key: Groq API key.
            model: Groq model name for claim extraction.
            predicates: Optional closed predicate catalog.
        """
        self._client = Groq(api_key=api_key)
        self.model = model
        self.predicates = predicates or DEFAULT_PREDICATES.copy()

    def extract(self, document_text: str) -> list[dict[str, Any]]:
        """Extract structured claims from a document.

        Args:
            document_text: The document text to process. Truncated to 8000 chars.

        Returns:
            A list of normalized claim dicts with subject, predicate, object,
            valid_from, valid_to, and confidence keys.

        Raises:
            RuntimeError: If the Groq request fails or returns invalid JSON.
        """
        prompt = CLAIM_EXTRACTION_PROMPT.format(
            predicates=", ".join(self.predicates)
        )
        truncated_text = document_text[:8000]

        try:
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
        except Exception as exc:
            logger.error("Claim extraction failed: %s", exc)
            raise RuntimeError(f"Claim extraction failed: {exc}") from exc

        raw_claims = data.get("claims", [])
        if not isinstance(raw_claims, list):
            return []

        normalized: list[dict[str, Any]] = []
        for claim in raw_claims:
            if not isinstance(claim, dict):
                continue

            subject = claim.get("subject")
            predicate = claim.get("predicate") or "REFERENCES"
            object_name = claim.get("object")
            if not subject or not object_name:
                continue

            if predicate not in self.predicates:
                predicate = "REFERENCES"

            normalized.append(
                {
                    "subject": subject,
                    "predicate": predicate,
                    "object": object_name,
                    "valid_from": claim.get("valid_from"),
                    "valid_to": claim.get("valid_to"),
                    "confidence": claim.get("confidence", 1.0),
                }
            )

        logger.debug(
            "Extracted %d claims from document (%d chars)",
            len(normalized),
            len(truncated_text),
        )
        return normalized
