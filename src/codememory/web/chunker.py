"""Normalize crawled or pasted content and chunk it for the research pipeline.

``ResearchIngestionPipeline._ingest_report`` calls ``_to_markdown`` and
``chunk_markdown`` after entity extraction on the full report body. Chunk size
policy follows project CONTEXT: **512** token target with **50** token overlap
on recursive splits only (header splits do not overlap).

Formats:
    ``markdown`` and ``text`` pass through; ``html`` uses ``markdownify`` when
    installed; ``pdf`` uses ``pymupdf4llm`` and requires ``RawContent.path``.
"""

import dataclasses
import logging
import re

try:
    from markdownify import markdownify
except ImportError:  # pragma: no cover
    markdownify = None  # type: ignore[assignment]

try:
    import pymupdf4llm
except ImportError:  # pragma: no cover
    pymupdf4llm = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class RawContent:
    """Input content with format hint."""

    text: str
    format: str  # "markdown" | "html" | "pdf" | "text"
    path: str | None = None  # required for PDF


@dataclasses.dataclass
class Chunk:
    """A text chunk with position metadata."""

    text: str
    index: int
    total: int = 0  # Set after all chunks produced


def _token_count(text: str) -> int:
    """Fast token approximation: words * 1.3 (per CONTEXT.md decision).

    Args:
        text: Text string to estimate token count for.

    Returns:
        Approximate token count as integer.
    """
    return int(len(text.split()) * 1.3)


def _to_markdown(content: RawContent) -> str:
    """Normalize content to markdown string.

    Dispatches by format:
    - markdown: pass through
    - html: markdownify with ATX headings
    - pdf: pymupdf4llm page-aware extraction
    - text: pass through

    Args:
        content: RawContent with text, format, and optional path.

    Returns:
        Markdown string.

    Raises:
        ValueError: If format is pdf but path is None.
    """
    if content.format == "markdown":
        return content.text
    elif content.format == "html":
        return markdownify(content.text, heading_style="ATX")  # type: ignore[misc]
    elif content.format == "pdf":
        if content.path is None:
            raise ValueError("PDF format requires a file path in content.path")
        return pymupdf4llm.to_markdown(content.path)  # type: ignore[union-attr]
    else:
        return content.text


def _split_on_headers(markdown: str) -> list[str]:
    """Split markdown text on ## and ### headers.

    Each split includes the header line with its content.

    Args:
        markdown: Full markdown string.

    Returns:
        List of section strings. If no headers found, returns [markdown].
    """
    sections = re.split(r"(?=^#{2,3}\s)", markdown, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]
    return sections if sections else [markdown]


def _recursive_split(
    text: str, max_tokens: int = 512, overlap_tokens: int = 50
) -> list[str]:
    """Split text into chunks of max_tokens with overlap.

    Uses word-boundary splitting with overlap between consecutive chunks.

    Args:
        text: Text to split.
        max_tokens: Maximum tokens per chunk (default 512).
        overlap_tokens: Overlap tokens between chunks (default 50).

    Returns:
        List of text chunks, each <= max_tokens.
    """
    words = text.split()
    if not words:
        return []

    # Convert token limits to approximate word counts
    max_words = int(max_tokens / 1.3)
    overlap_words = int(overlap_tokens / 1.3)

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk_text = " ".join(words[start:end])
        chunks.append(chunk_text)
        if end >= len(words):
            break
        start = end - overlap_words

    return chunks


def chunk_markdown(
    markdown: str, max_tokens: int = 512, overlap_tokens: int = 50
) -> list[Chunk]:
    """Chunk markdown: split on headers, recursive fallback for oversize sections.

    Args:
        markdown: Markdown text to chunk.
        max_tokens: Max tokens per chunk (default 512).
        overlap_tokens: Overlap for recursive splits (default 50).

    Returns:
        List of Chunk objects with index and total set.
    """
    header_sections = _split_on_headers(markdown)
    raw_chunks: list[str] = []

    for section in header_sections:
        if _token_count(section) <= max_tokens:
            raw_chunks.append(section)
        else:
            sub_chunks = _recursive_split(section, max_tokens, overlap_tokens)
            raw_chunks.extend(sub_chunks)

    total = len(raw_chunks)
    return [Chunk(text=text, index=i, total=total) for i, text in enumerate(raw_chunks)]
