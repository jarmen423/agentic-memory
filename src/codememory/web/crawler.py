"""Crawl4AI wrapper: fetch a URL to markdown for the web research pipeline.

Primary consumer is the CLI path that feeds ``ResearchIngestionPipeline`` (or
equivalent) with ``format="markdown"`` text. On failure, raises
``RuntimeError`` with the crawler error message; alternate browser fallbacks are
out of scope here per project CONTEXT.
"""

import logging

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

logger = logging.getLogger(__name__)


async def crawl_url(url: str, timeout_ms: int = 30000) -> str:
    """Fetch URL via Crawl4AI and return markdown content.

    Args:
        url: The URL to crawl.
        timeout_ms: Page timeout in milliseconds (default 30000).

    Returns:
        Clean markdown string of the page content.

    Raises:
        RuntimeError: If crawl fails or returns empty content.
    """
    config = CrawlerRunConfig(
        wait_until="networkidle",
        page_timeout=timeout_ms,
    )
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)

    if not result.success:
        raise RuntimeError(f"Crawl failed for {url}: {result.error_message}")

    # result.markdown may be a MarkdownGenerationResult object or string
    markdown = result.markdown
    if hasattr(markdown, "raw_markdown"):
        markdown = markdown.raw_markdown

    if not markdown or not markdown.strip():
        raise RuntimeError(f"Crawl returned empty content for {url}")

    logger.info("Crawled %s: %d chars markdown", url, len(markdown))
    return markdown
