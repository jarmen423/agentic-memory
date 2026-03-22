"""Web Research Memory module.

Provides content normalization, chunking, and web crawling for the
research ingestion pipeline.
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

__all__ = [
    "Chunk",
    "RawContent",
    "chunk_markdown",
    "_recursive_split",
    "_to_markdown",
    "_token_count",
    "crawl_url",
]
