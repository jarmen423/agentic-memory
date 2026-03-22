"""Web Research Memory module.

Provides content normalization, chunking, web crawling, and the
ResearchIngestionPipeline for persisting research output to Neo4j.
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
