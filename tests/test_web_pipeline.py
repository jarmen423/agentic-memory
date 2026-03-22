"""Unit tests for Phase 2 web research pipeline components.

Tests cover:
- GraphWriter extension methods (write_report_node, write_source_node,
  write_cites_relationship, write_has_chunk_relationship, write_part_of_relationship)
- Content normalization (_to_markdown dispatch, _token_count)
- Markdown chunker (chunk_markdown header split + recursive fallback with overlap)
- Crawl4AI wrapper (crawl_url success + failure)

All tests mock Neo4j connections — no live services required.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from codememory.core.graph_writer import GraphWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_writer():
    """Return a (GraphWriter, mock_conn, mock_session) triple."""
    mock_conn = MagicMock()
    mock_session = MagicMock()
    mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)
    writer = GraphWriter(mock_conn)
    return writer, mock_conn, mock_session


# ---------------------------------------------------------------------------
# Task 1: GraphWriter extensions
# ---------------------------------------------------------------------------


class TestGraphWriterReportNode:
    """Tests for GraphWriter.write_report_node()."""

    def test_write_report_node_merge_key(self):
        """write_report_node uses MERGE on (project_id, session_id)."""
        writer, _, mock_session = _make_writer()
        props = {
            "project_id": "proj1",
            "session_id": "sess1",
            "title": "Test Report",
            "source_agent": "claude",
            "source_key": "deep_research_agent",
            "source_type": "web",
            "ingested_at": "2026-01-01T00:00:00Z",
            "research_question": "test?",
            "ingestion_mode": "active",
            "embedding_model": None,
            "entities": ["SaaS"],
            "entity_types": ["concept"],
        }
        writer.write_report_node(props)
        assert mock_session.run.called, "session.run() was not called"
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE" in cypher
        assert "project_id: $project_id" in cypher
        assert "session_id: $session_id" in cypher
        assert "Memory:Research:Report" in cypher


class TestGraphWriterSourceNode:
    """Tests for GraphWriter.write_source_node()."""

    def test_write_source_node_merge_on_url(self):
        """write_source_node uses MERGE on url for Entity:Source nodes."""
        writer, _, mock_session = _make_writer()
        writer.write_source_node(url="https://example.com", title="Example")
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE (s:Entity:Source {url: $url})" in cypher


class TestGraphWriterCitesRelationship:
    """Tests for GraphWriter.write_cites_relationship()."""

    def test_write_cites_relationship_merge_pattern(self):
        """write_cites_relationship uses MERGE (f)-[r:CITES]->(s) with ON CREATE SET."""
        writer, _, mock_session = _make_writer()
        rel_props = {
            "url": "https://example.com",
            "title": "Ex",
            "snippet": "text",
            "accessed_at": "2026-01-01",
            "source_agent": "claude",
        }
        writer.write_cites_relationship(
            finding_source_key="deep_research_agent",
            finding_content_hash="abc123",
            source_url="https://example.com",
            rel_props=rel_props,
        )
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE (f)-[r:CITES]->(s)" in cypher
        assert "ON CREATE SET r += $rel_props" in cypher


class TestGraphWriterHasChunkRelationship:
    """Tests for GraphWriter.write_has_chunk_relationship()."""

    def test_write_has_chunk_relationship(self):
        """write_has_chunk_relationship writes :HAS_CHUNK with order property."""
        writer, _, mock_session = _make_writer()
        writer.write_has_chunk_relationship(
            report_project_id="proj1",
            report_session_id="sess1",
            chunk_source_key="web_crawl4ai",
            chunk_content_hash="def456",
            order=0,
        )
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert ":HAS_CHUNK" in cypher
        assert "order: $order" in cypher


class TestGraphWriterPartOfRelationship:
    """Tests for GraphWriter.write_part_of_relationship()."""

    def test_write_part_of_relationship(self):
        """write_part_of_relationship writes Chunk -> Report PART_OF MERGE."""
        writer, _, mock_session = _make_writer()
        writer.write_part_of_relationship(
            chunk_source_key="web_crawl4ai",
            chunk_content_hash="def456",
            report_project_id="proj1",
            report_session_id="sess1",
        )
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE (c)-[:PART_OF]->(r)" in cypher
        # Should match Chunk by (source_key, content_hash)
        assert "source_key: $source_key" in cypher
        assert "content_hash: $content_hash" in cypher
        # Should match Report by (project_id, session_id)
        assert "project_id: $project_id" in cypher
        assert "session_id: $session_id" in cypher


class TestGraphWriterRegression:
    """Regression tests — existing GraphWriter methods still pass."""

    def test_write_memory_node_still_works(self):
        """write_memory_node is not broken by new methods."""
        writer, _, mock_session = _make_writer()
        props = {
            "source_key": "code_treesitter",
            "content_hash": "abc123",
            "session_id": "sess-1",
            "source_type": "code",
            "ingested_at": "2026-01-01T00:00:00Z",
            "ingestion_mode": "active",
            "embedding_model": "text-embedding-3-large",
            "project_id": "proj-1",
            "entities": ["FastAPI"],
            "entity_types": ["technology"],
            "embedding": [0.1, 0.2],
            "text": "def main(): pass",
        }
        writer.write_memory_node(["Memory", "Code", "Chunk"], props)
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE" in cypher.upper()

    def test_upsert_entity_still_works(self):
        """upsert_entity is not broken by new methods."""
        writer, _, mock_session = _make_writer()
        writer.upsert_entity("FastAPI", "technology")
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE" in cypher.upper()
        assert "Entity" in cypher

    def test_write_relationship_still_works(self):
        """write_relationship is not broken by new methods."""
        writer, _, mock_session = _make_writer()
        writer.write_relationship("code_treesitter", "abc123", "FastAPI", "technology", "ABOUT")
        cypher = mock_session.run.call_args[0][0]
        assert "ABOUT" in cypher


# ---------------------------------------------------------------------------
# Task 2: Content normalization and chunking
# ---------------------------------------------------------------------------


class TestTokenCount:
    """Tests for _token_count approximation."""

    def test_token_count_five_words(self):
        """_token_count returns int(word_count * 1.3)."""
        from codememory.web.chunker import _token_count

        result = _token_count("one two three four five")
        assert result == int(5 * 1.3)


class TestToMarkdown:
    """Tests for _to_markdown content dispatch."""

    def test_to_markdown_passthrough_markdown(self):
        """markdown format returns text unchanged."""
        from codememory.web.chunker import RawContent, _to_markdown

        content = RawContent(text="# Hello", format="markdown")
        assert _to_markdown(content) == "# Hello"

    def test_to_markdown_passthrough_text(self):
        """text format returns text unchanged."""
        from codememory.web.chunker import RawContent, _to_markdown

        content = RawContent(text="plain text here", format="text")
        assert _to_markdown(content) == "plain text here"

    def test_to_markdown_html_calls_markdownify(self):
        """html format calls markdownify with heading_style=ATX."""
        from codememory.web.chunker import RawContent, _to_markdown

        html = "<h1>Title</h1><p>Body</p>"
        with patch("codememory.web.chunker.markdownify") as mock_md:
            mock_md.return_value = "# Title\n\nBody"
            content = RawContent(text=html, format="html")
            result = _to_markdown(content)
            mock_md.assert_called_once_with(html, heading_style="ATX")
            assert result == "# Title\n\nBody"

    def test_to_markdown_pdf_calls_pymupdf4llm(self):
        """pdf format calls pymupdf4llm.to_markdown with the file path."""
        from codememory.web.chunker import RawContent, _to_markdown

        with patch("codememory.web.chunker.pymupdf4llm") as mock_pdf:
            mock_pdf.to_markdown.return_value = "# PDF Content"
            content = RawContent(text="", format="pdf", path="/tmp/doc.pdf")
            result = _to_markdown(content)
            mock_pdf.to_markdown.assert_called_once_with("/tmp/doc.pdf")
            assert result == "# PDF Content"

    def test_to_markdown_pdf_no_path_raises(self):
        """pdf format without path raises ValueError."""
        from codememory.web.chunker import RawContent, _to_markdown

        content = RawContent(text="", format="pdf", path=None)
        with pytest.raises(ValueError, match="path"):
            _to_markdown(content)


class TestChunkMarkdown:
    """Tests for chunk_markdown header splitting and recursive fallback."""

    def test_chunk_markdown_two_headers_two_chunks(self):
        """Two ## headers each under 512 tokens produces exactly 2 chunks."""
        from codememory.web.chunker import chunk_markdown

        markdown = "## Section One\n\nShort content for section one.\n\n## Section Two\n\nShort content for section two."
        chunks = chunk_markdown(markdown)
        assert len(chunks) == 2
        assert chunks[0].index == 0
        assert chunks[1].index == 1
        assert chunks[0].total == 2
        assert chunks[1].total == 2

    def test_chunk_markdown_oversize_triggers_recursive(self):
        """A section > 512 tokens is recursively split into smaller chunks."""
        from codememory.web.chunker import chunk_markdown

        # Generate a big section: ~1000 words = ~1300 tokens
        big_section = "## Big Section\n\n" + " ".join(["word"] * 1000)
        chunks = chunk_markdown(big_section, max_tokens=512)
        # Should produce multiple chunks all within limit
        assert len(chunks) > 1
        for chunk in chunks:
            # Each chunk should be well under 512 tokens
            word_count = len(chunk.text.split())
            # max ~512/1.3 ~ 394 words per chunk, give some margin
            assert word_count <= 420, f"Chunk too large: {word_count} words"

    def test_chunk_markdown_chunk_objects_have_correct_fields(self):
        """Chunk objects have text, index, and total attributes."""
        from codememory.web.chunker import chunk_markdown

        markdown = "## Header\n\nsome content here"
        chunks = chunk_markdown(markdown)
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert hasattr(chunk, "text")
        assert hasattr(chunk, "index")
        assert hasattr(chunk, "total")
        assert isinstance(chunk.text, str)
        assert isinstance(chunk.index, int)
        assert isinstance(chunk.total, int)


class TestRecursiveSplitOverlap:
    """Tests for _recursive_split overlap behavior."""

    def test_recursive_split_produces_overlap(self):
        """Last ~50 tokens of chunk N appear at start of chunk N+1."""
        from codememory.web.chunker import _recursive_split

        # Build a text that forces at least 2 chunks
        # 500 unique words that won't fit in one 512-token chunk
        words = [f"word{i}" for i in range(500)]
        text = " ".join(words)
        chunks = _recursive_split(text, max_tokens=200, overlap_tokens=50)
        assert len(chunks) >= 2

        # Check overlap: last ~38 words of chunk 0 (50/1.3) should appear in chunk 1
        overlap_words = int(50 / 1.3)  # ~38
        chunk0_words = chunks[0].split()
        chunk1_words = chunks[1].split()
        # The tail of chunk0 should match the start of chunk1
        tail = chunk0_words[-overlap_words:]
        head = chunk1_words[:overlap_words]
        assert tail == head, f"No overlap found: tail={tail[:5]}... head={head[:5]}..."


# ---------------------------------------------------------------------------
# Task 2: Crawl4AI wrapper
# ---------------------------------------------------------------------------


class TestCrawlUrl:
    """Tests for crawl_url async wrapper."""

    @pytest.mark.asyncio
    async def test_crawl_url_success(self):
        """crawl_url returns markdown string when crawl succeeds."""
        from codememory.web.crawler import crawl_url

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.markdown = "# Page Title\n\nSome content here."

        mock_crawler_instance = AsyncMock()
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)
        mock_crawler_instance.__aenter__ = AsyncMock(return_value=mock_crawler_instance)
        mock_crawler_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("codememory.web.crawler.AsyncWebCrawler", return_value=mock_crawler_instance):
            result = await crawl_url("https://example.com")

        assert result == "# Page Title\n\nSome content here."

    @pytest.mark.asyncio
    async def test_crawl_url_failure_raises_runtime_error(self):
        """crawl_url raises RuntimeError when result.success is False."""
        from codememory.web.crawler import crawl_url

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "timeout"

        mock_crawler_instance = AsyncMock()
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)
        mock_crawler_instance.__aenter__ = AsyncMock(return_value=mock_crawler_instance)
        mock_crawler_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("codememory.web.crawler.AsyncWebCrawler", return_value=mock_crawler_instance):
            with pytest.raises(RuntimeError, match="Crawl failed"):
                await crawl_url("https://example.com")
