"""Web research memory: crawl, normalize, chunk, and ingest into Neo4j.

This subpackage supports the **research ingestion pipeline**
(``ResearchIngestionPipeline``): user- or agent-directed URLs and reports are
normalized to markdown, split into embeddable chunks, and written through
``GraphWriter`` with the ``web_crawl4ai`` and ``deep_research_agent`` source
keys registered at import time from ``codememory.web.pipeline``.

Typical flow:
    1. Optional fetch: ``crawl_url`` (Crawl4AI) produces markdown.
    2. Normalization + chunking: ``chunk_markdown`` / ``RawContent`` helpers.
    3. Persistence: ``ResearchIngestionPipeline.ingest`` routes by ``type``.
"""

from codememory.web.chunker import (
    Chunk,
    RawContent,
    _recursive_split,
    _to_markdown,
    _token_count,
    chunk_markdown,
)
from codememory.web.crawler import crawl_url
from codememory.web.pipeline import ResearchIngestionPipeline

__all__ = [
    "Chunk",
    "RawContent",
    "chunk_markdown",
    "_recursive_split",
    "_to_markdown",
    "_token_count",
    "crawl_url",
    "ResearchIngestionPipeline",
]
