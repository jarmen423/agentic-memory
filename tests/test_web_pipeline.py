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

from agentic_memory.core.graph_writer import GraphWriter


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
        assert "MERGE (c)-[rel:PART_OF]->(r)" in cypher
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
        from agentic_memory.web.chunker import _token_count

        result = _token_count("one two three four five")
        assert result == int(5 * 1.3)


class TestToMarkdown:
    """Tests for _to_markdown content dispatch."""

    def test_to_markdown_passthrough_markdown(self):
        """markdown format returns text unchanged."""
        from agentic_memory.web.chunker import RawContent, _to_markdown

        content = RawContent(text="# Hello", format="markdown")
        assert _to_markdown(content) == "# Hello"

    def test_to_markdown_passthrough_text(self):
        """text format returns text unchanged."""
        from agentic_memory.web.chunker import RawContent, _to_markdown

        content = RawContent(text="plain text here", format="text")
        assert _to_markdown(content) == "plain text here"

    def test_to_markdown_html_calls_markdownify(self):
        """html format calls markdownify with heading_style=ATX."""
        from agentic_memory.web.chunker import RawContent, _to_markdown

        html = "<h1>Title</h1><p>Body</p>"
        with patch("agentic_memory.web.chunker.markdownify") as mock_md:
            mock_md.return_value = "# Title\n\nBody"
            content = RawContent(text=html, format="html")
            result = _to_markdown(content)
            mock_md.assert_called_once_with(html, heading_style="ATX")
            assert result == "# Title\n\nBody"

    def test_to_markdown_pdf_calls_pymupdf4llm(self):
        """pdf format calls pymupdf4llm.to_markdown with the file path."""
        from agentic_memory.web.chunker import RawContent, _to_markdown

        with patch("agentic_memory.web.chunker.pymupdf4llm") as mock_pdf:
            mock_pdf.to_markdown.return_value = "# PDF Content"
            content = RawContent(text="", format="pdf", path="/tmp/doc.pdf")
            result = _to_markdown(content)
            mock_pdf.to_markdown.assert_called_once_with("/tmp/doc.pdf")
            assert result == "# PDF Content"

    def test_to_markdown_pdf_no_path_raises(self):
        """pdf format without path raises ValueError."""
        from agentic_memory.web.chunker import RawContent, _to_markdown

        content = RawContent(text="", format="pdf", path=None)
        with pytest.raises(ValueError, match="path"):
            _to_markdown(content)


class TestChunkMarkdown:
    """Tests for chunk_markdown header splitting and recursive fallback."""

    def test_chunk_markdown_two_headers_two_chunks(self):
        """Two ## headers each under 512 tokens produces exactly 2 chunks."""
        from agentic_memory.web.chunker import chunk_markdown

        markdown = "## Section One\n\nShort content for section one.\n\n## Section Two\n\nShort content for section two."
        chunks = chunk_markdown(markdown)
        assert len(chunks) == 2
        assert chunks[0].index == 0
        assert chunks[1].index == 1
        assert chunks[0].total == 2
        assert chunks[1].total == 2

    def test_chunk_markdown_oversize_triggers_recursive(self):
        """A section > 512 tokens is recursively split into smaller chunks."""
        from agentic_memory.web.chunker import chunk_markdown

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
        from agentic_memory.web.chunker import chunk_markdown

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
        from agentic_memory.web.chunker import _recursive_split

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
        from agentic_memory.web.crawler import crawl_url

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.markdown = "# Page Title\n\nSome content here."

        mock_crawler_instance = AsyncMock()
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)
        mock_crawler_instance.__aenter__ = AsyncMock(return_value=mock_crawler_instance)
        mock_crawler_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("agentic_memory.web.crawler.AsyncWebCrawler", return_value=mock_crawler_instance):
            result = await crawl_url("https://example.com")

        assert result == "# Page Title\n\nSome content here."

    @pytest.mark.asyncio
    async def test_crawl_url_failure_raises_runtime_error(self):
        """crawl_url raises RuntimeError when result.success is False."""
        from agentic_memory.web.crawler import crawl_url

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "timeout"

        mock_crawler_instance = AsyncMock()
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)
        mock_crawler_instance.__aenter__ = AsyncMock(return_value=mock_crawler_instance)
        mock_crawler_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("agentic_memory.web.crawler.AsyncWebCrawler", return_value=mock_crawler_instance):
            with pytest.raises(RuntimeError, match="Crawl failed"):
                await crawl_url("https://example.com")


# ---------------------------------------------------------------------------
# Task 1 (Plan 02): ResearchIngestionPipeline
# ---------------------------------------------------------------------------


def _make_pipeline(temporal_bridge: MagicMock | None = None):
    """Return a (pipeline, mock_writer) pair with all dependencies mocked."""
    from agentic_memory.web.pipeline import ResearchIngestionPipeline

    mock_conn = MagicMock()
    mock_session = MagicMock()
    mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 3072

    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = [{"name": "SaaS", "type": "concept"}]

    pipeline = ResearchIngestionPipeline(
        mock_conn,
        mock_embedder,
        mock_extractor,
        temporal_bridge=temporal_bridge,
    )
    pipeline._claim_extractor = MagicMock()
    pipeline._claim_extractor.extract.return_value = []

    # Replace the internal writer with a MagicMock so we can inspect calls
    mock_writer = MagicMock()
    pipeline._writer = mock_writer
    pipeline._test_session = mock_session

    return pipeline, mock_writer


def _report_source(**overrides):
    """Return a minimal report source dict."""
    base = {
        "type": "report",
        "content": "## Section One\n\nSome research content about SaaS churn.\n\n## Section Two\n\nMore findings here.",
        "project_id": "proj-test",
        "session_id": "sess-abc",
        "title": "SaaS Churn Analysis",
        "source_agent": "claude",
        "research_question": "What drives SaaS churn?",
        "format": "markdown",
    }
    base.update(overrides)
    return base


def _finding_source(**overrides):
    """Return a minimal finding source dict."""
    base = {
        "type": "finding",
        "content": "SaaS churn increases 20% when onboarding friction is high.",
        "project_id": "proj-test",
        "session_id": "sess-abc",
        "source_agent": "claude",
        "confidence": "high",
        "research_question": "What drives SaaS churn?",
        "citations": [
            {
                "url": "https://example.com/article",
                "title": "SaaS Study",
                "snippet": "Key finding about churn.",
            }
        ],
    }
    base.update(overrides)
    return base


class TestResearchIngestionPipelineSubclassContract:
    """Tests for class structure and ABC contract."""

    def test_pipeline_subclass_contract(self):
        """ResearchIngestionPipeline is a subclass of BaseIngestionPipeline with DOMAIN_LABEL."""
        from agentic_memory.core.base import BaseIngestionPipeline
        from agentic_memory.web.pipeline import ResearchIngestionPipeline

        assert issubclass(ResearchIngestionPipeline, BaseIngestionPipeline)
        assert ResearchIngestionPipeline.DOMAIN_LABEL == "Research"

    def test_ingest_unknown_type_raises_value_error(self):
        """ingest() with type='banana' raises ValueError."""
        pipeline, _ = _make_pipeline()
        with pytest.raises(ValueError, match="banana"):
            pipeline.ingest({"type": "banana", "content": "x"})


class TestResearchIngestionPipelineReportFlow:
    """Tests for _ingest_report path."""

    def test_ingest_report_flow(self):
        """ingest(report) calls write_report_node once, write_memory_node per chunk."""
        pipeline, mock_writer = _make_pipeline()
        result = pipeline.ingest(_report_source())

        assert mock_writer.write_report_node.called, "write_report_node was not called"
        assert mock_writer.write_report_node.call_count == 1

        chunk_count = mock_writer.write_memory_node.call_count
        assert chunk_count >= 1, "write_memory_node not called for any chunk"

        # HAS_CHUNK and PART_OF called same number of times as chunk nodes written
        assert mock_writer.write_has_chunk_relationship.call_count == chunk_count
        assert mock_writer.write_part_of_relationship.call_count == chunk_count
        assert mock_writer.write_temporal_relationship.call_count == chunk_count

        assert result["type"] == "report"
        assert "chunks" in result
        assert result["chunks"] == chunk_count

    def test_ingest_report_no_embedding_on_parent(self):
        """write_report_node properties must have embedding_model=None, no 'embedding' key."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_report_source())

        call_kwargs = mock_writer.write_report_node.call_args
        # First positional arg is the properties dict
        props = call_kwargs[0][0]
        assert props.get("embedding_model") is None
        assert "embedding" not in props

    def test_ingest_report_writes_part_of(self):
        """write_part_of_relationship called N times, once per chunk."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_report_source())

        chunk_count = mock_writer.write_memory_node.call_count
        assert mock_writer.write_part_of_relationship.call_count == chunk_count

        # Verify each call has the right project/session IDs
        for call in mock_writer.write_part_of_relationship.call_args_list:
            kwargs = call[1]  # keyword args
            assert kwargs.get("report_project_id") == "proj-test"
            assert kwargs.get("report_session_id") == "sess-abc"
            assert kwargs.get("valid_from")
            assert kwargs.get("confidence") == 1.0

    def test_ingest_report_uses_temporal_relationship_writes(self):
        """Chunk entity wiring uses write_temporal_relationship with valid_from."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_report_source())

        assert mock_writer.write_relationship.call_count == 0
        assert mock_writer.write_temporal_relationship.call_count >= 1
        for call in mock_writer.write_temporal_relationship.call_args_list:
            kwargs = call[1]
            assert kwargs.get("valid_from")
            assert kwargs.get("confidence") == 1.0

    def test_ingest_report_calls_claim_extractor_once(self):
        """Report ingest runs claim extraction after the NER pass."""
        pipeline, _ = _make_pipeline()
        pipeline.ingest(_report_source())

        pipeline._claim_extractor.extract.assert_called_once_with(
            _report_source()["content"]
        )

    def test_ingest_report_claims_write_entity_relationships(self):
        """Extracted claims create direct Entity-to-Entity relationships."""
        pipeline, mock_writer = _make_pipeline()
        pipeline._claim_extractor.extract.return_value = [
            {
                "subject": "Agentic Memory",
                "predicate": "WORKS_AT",
                "object": "Neo4j",
                "valid_from": "2026-03-25T12:00:00+00:00",
                "valid_to": None,
                "confidence": 0.75,
            }
        ]

        pipeline.ingest(_report_source())

        assert mock_writer.upsert_entity.call_count >= 3
        upsert_names = [call.args[0] for call in mock_writer.upsert_entity.call_args_list]
        assert "Agentic Memory" in upsert_names
        assert "Neo4j" in upsert_names

        run_calls = pipeline._test_session.run.call_args_list
        assert any("MERGE (subj)-[r:WORKS_AT]->(obj)" in call.args[0] for call in run_calls)

    def test_ingest_report_claim_failure_is_non_blocking(self):
        """Claim extraction failure is logged and does not break report ingest."""
        pipeline, mock_writer = _make_pipeline()
        pipeline._claim_extractor.extract.side_effect = RuntimeError("boom")

        result = pipeline.ingest(_report_source())

        assert result["type"] == "report"
        assert mock_writer.write_report_node.call_count == 1

    def test_ingest_report_shadow_writes_chunk_relations(self):
        """Chunk-level entity relationships are mirrored to the temporal bridge."""
        bridge = MagicMock()
        bridge.is_available.return_value = True
        pipeline, _ = _make_pipeline(temporal_bridge=bridge)

        pipeline.ingest(_report_source())

        assert bridge.ingest_relation.call_count >= 1
        first_call = bridge.ingest_relation.call_args_list[0].kwargs
        assert first_call["subject_kind"] == "research_chunk"
        assert first_call["evidence"]["sourceKind"] == "research_chunk"
        assert first_call["evidence"]["sourceId"].startswith("web_crawl4ai:")

    def test_ingest_report_shadow_writes_claims(self):
        """Extracted report claims are mirrored with research_chunk evidence ids."""
        bridge = MagicMock()
        bridge.is_available.return_value = True
        pipeline, _ = _make_pipeline(temporal_bridge=bridge)
        pipeline._claim_extractor.extract.return_value = [
            {
                "subject": "Agentic Memory",
                "predicate": "USES",
                "object": "Neo4j",
                "valid_from": "2026-03-25T12:00:00+00:00",
                "valid_to": None,
                "confidence": 0.75,
            }
        ]

        pipeline.ingest(_report_source())

        bridge.ingest_claim.assert_called_once()
        kwargs = bridge.ingest_claim.call_args.kwargs
        assert kwargs["evidence"]["sourceKind"] == "research_chunk"
        assert kwargs["evidence"]["sourceId"].startswith("web_crawl4ai:")

    def test_ingest_report_shadow_write_failures_are_swallowed(self):
        """Temporal shadow write failures do not break report ingest."""
        bridge = MagicMock()
        bridge.is_available.return_value = True
        bridge.ingest_relation.side_effect = RuntimeError("bridge down")
        pipeline, _ = _make_pipeline(temporal_bridge=bridge)

        result = pipeline.ingest(_report_source())

        assert result["type"] == "report"


class TestChunkContentHashSessionScoped:
    """Tests verifying chunk content_hash includes session_id (CONTEXT.md dedup key)."""

    def test_chunk_content_hash_includes_session_id(self):
        """Two reports with same content but different session_ids produce different chunk hashes."""
        pipeline1, writer1 = _make_pipeline()
        pipeline2, writer2 = _make_pipeline()

        same_content = "## Section\n\nIdentical content in both sessions."

        source_s1 = _report_source(content=same_content, session_id="s1")
        source_s2 = _report_source(content=same_content, session_id="s2")

        pipeline1.ingest(source_s1)
        pipeline2.ingest(source_s2)

        # Extract content_hash values from write_memory_node calls
        hashes_s1 = [
            call[0][1]["content_hash"]  # positional: (labels, props)
            for call in writer1.write_memory_node.call_args_list
        ]
        hashes_s2 = [
            call[0][1]["content_hash"]
            for call in writer2.write_memory_node.call_args_list
        ]

        assert len(hashes_s1) > 0, "No chunks written for session s1"
        assert len(hashes_s2) > 0, "No chunks written for session s2"

        # Same content, different session_id -> different hashes
        for h1, h2 in zip(hashes_s1, hashes_s2):
            assert h1 != h2, (
                f"Chunk hash collision: same text but different session_ids should differ. "
                f"Got {h1} for both sessions."
            )


class TestFindingContentHashTextOnly:
    """Tests verifying finding content_hash is text-only (global dedup, not session-scoped)."""

    def test_finding_content_hash_is_text_only(self):
        """Same finding text from different sessions produces identical content_hash."""
        pipeline1, writer1 = _make_pipeline()
        pipeline2, writer2 = _make_pipeline()

        same_text = "SaaS churn increases 20% when onboarding friction is high."

        source_s1 = _finding_source(content=same_text, session_id="sess-1", citations=[])
        source_s2 = _finding_source(content=same_text, session_id="sess-2", citations=[])

        pipeline1.ingest(source_s1)
        pipeline2.ingest(source_s2)

        props1 = writer1.write_memory_node.call_args[0][1]
        props2 = writer2.write_memory_node.call_args[0][1]

        assert props1["content_hash"] == props2["content_hash"], (
            "Finding content_hash must be text-only (sha256 of text), not session-scoped."
        )

    def test_finding_content_hash_deterministic(self):
        """Calling ingest twice with same finding text produces identical content_hash."""
        import hashlib

        pipeline, mock_writer = _make_pipeline()
        text = "SaaS churn increases 20% when onboarding friction is high."
        source = _finding_source(content=text, citations=[])
        pipeline.ingest(source)

        props = mock_writer.write_memory_node.call_args[0][1]
        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        assert props["content_hash"] == expected_hash


class TestResearchIngestionPipelineFindingFlow:
    """Tests for _ingest_finding path."""

    def test_ingest_finding_flow(self):
        """ingest(finding) calls write_memory_node with Finding labels, write_source_node, write_cites_relationship."""
        pipeline, mock_writer = _make_pipeline()
        result = pipeline.ingest(_finding_source())

        assert mock_writer.write_memory_node.call_count == 1
        call_args = mock_writer.write_memory_node.call_args
        labels = call_args[0][0]  # first positional: labels list
        assert "Memory" in labels
        assert "Research" in labels
        assert "Finding" in labels

        assert mock_writer.write_source_node.call_count == 1
        assert mock_writer.write_cites_relationship.call_count == 1

        # CITES relationship content_hash must match Finding node content_hash
        finding_hash = call_args[0][1]["content_hash"]
        cites_call = mock_writer.write_cites_relationship.call_args
        assert cites_call[1]["finding_content_hash"] == finding_hash
        assert cites_call[1]["valid_from"]
        assert cites_call[1]["confidence"] == 1.0
        assert mock_writer.write_temporal_relationship.call_count == 1

        assert result["type"] == "finding"

    def test_ingest_finding_no_citations(self):
        """ingest(finding) with empty citations list does not call write_source_node."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_finding_source(citations=[]))
        assert mock_writer.write_source_node.call_count == 0
        assert mock_writer.write_cites_relationship.call_count == 0

    def test_ingest_finding_shadow_writes_temporal_relation(self):
        """Findings mirror entity relations to the temporal bridge using stable ids."""
        bridge = MagicMock()
        bridge.is_available.return_value = True
        pipeline, _ = _make_pipeline(temporal_bridge=bridge)

        pipeline.ingest(_finding_source(citations=[]))

        bridge.ingest_relation.assert_called_once()
        kwargs = bridge.ingest_relation.call_args.kwargs
        assert kwargs["subject_kind"] == "research_finding"
        assert kwargs["evidence"]["sourceKind"] == "research_finding"
        assert kwargs["evidence"]["sourceId"].startswith("deep_research_agent:")


class TestSourceRegistration:
    """Tests for source registration at module import time."""

    def test_source_registration(self):
        """pipeline module registers deep_research_agent and web_crawl4ai in SOURCE_REGISTRY."""
        import agentic_memory.web.pipeline  # noqa: F401 — ensure module is imported
        from agentic_memory.core.registry import SOURCE_REGISTRY

        assert "deep_research_agent" in SOURCE_REGISTRY
        assert "web_crawl4ai" in SOURCE_REGISTRY
        assert SOURCE_REGISTRY["deep_research_agent"] == ["Memory", "Research", "Finding"]
        assert SOURCE_REGISTRY["web_crawl4ai"] == ["Memory", "Research", "Chunk"]
