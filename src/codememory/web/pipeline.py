"""Research ingestion pipeline — report and finding paths.

ResearchIngestionPipeline subclasses BaseIngestionPipeline to implement
two-branch ingest routing:
- type="report": Report parent (no embed) + Chunk children (embedded)
- type="finding": Single Finding node (embedded) + Source MERGE + CITES
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from codememory.core.base import BaseIngestionPipeline
from codememory.core.connection import ConnectionManager
from codememory.core.embedding import EmbeddingService
from codememory.core.entity_extraction import EntityExtractionService, build_embed_text
from codememory.core.graph_writer import GraphWriter
from codememory.core.registry import register_source
from codememory.web.chunker import RawContent, _to_markdown, chunk_markdown

logger = logging.getLogger(__name__)

# Register sources at import time per CONTEXT.md
register_source("deep_research_agent", ["Memory", "Research", "Finding"])
register_source("web_crawl4ai", ["Memory", "Research", "Chunk"])


class ResearchIngestionPipeline(BaseIngestionPipeline):
    """Concrete pipeline for web research ingestion.

    Orchestrates report and finding ingestion using Phase 1 services:
    EmbeddingService, EntityExtractionService, GraphWriter.

    Args:
        connection_manager: Neo4j ConnectionManager instance.
        embedding_service: EmbeddingService configured for Gemini.
        entity_extractor: EntityExtractionService for named entity extraction.
    """

    DOMAIN_LABEL = "Research"

    def __init__(
        self,
        connection_manager: ConnectionManager,
        embedding_service: EmbeddingService,
        entity_extractor: EntityExtractionService,
    ) -> None:
        """Initialize the research ingestion pipeline.

        Args:
            connection_manager: Configured ConnectionManager instance.
            embedding_service: Configured EmbeddingService (Gemini provider).
            entity_extractor: Configured EntityExtractionService (Groq).
        """
        super().__init__(connection_manager)
        self._embedder = embedding_service
        self._extractor = entity_extractor
        self._writer = GraphWriter(connection_manager)

    def ingest(self, source: dict[str, Any]) -> dict[str, Any]:
        """Route ingestion by content type.

        Args:
            source: Dict with "type" key ("report" or "finding") plus content fields.

        Returns:
            Summary dict with ingestion results.

        Raises:
            ValueError: If source["type"] is not "report" or "finding".
        """
        content_type = source.get("type")
        if content_type == "report":
            return self._ingest_report(source)
        elif content_type == "finding":
            return self._ingest_finding(source)
        else:
            raise ValueError(f"Unknown content type: {content_type!r}")

    def _content_hash(self, text: str) -> str:
        """Deterministic SHA-256 hash for Finding deduplication.

        Findings dedup on content alone — same text = same finding regardless
        of session.

        Args:
            text: The finding text to hash.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        return hashlib.sha256(text.encode()).hexdigest()

    def _chunk_content_hash(self, session_id: str, chunk_index: int, text: str) -> str:
        """Deterministic SHA-256 hash for Chunk deduplication.

        Per CONTEXT.md, Chunk MERGE key is (session_id, chunk_index).
        We encode session_id and chunk_index into content_hash so that
        write_memory_node's MERGE on (source_key, content_hash) effectively
        deduplicates on the correct composite key. This prevents identical
        text from different sessions from collapsing into one Chunk node.

        Args:
            session_id: The session that produced this chunk.
            chunk_index: The chunk's position within its parent report.
            text: The chunk text (included for extra uniqueness).

        Returns:
            Hex-encoded SHA-256 digest of the composite key.
        """
        composite = f"{session_id}:{chunk_index}:{text}"
        return hashlib.sha256(composite.encode()).hexdigest()

    def _now(self) -> str:
        """Current UTC timestamp in ISO format.

        Returns:
            ISO-8601 UTC datetime string.
        """
        return datetime.now(timezone.utc).isoformat()

    def _ingest_report(self, source: dict[str, Any]) -> dict[str, Any]:
        """Ingest a research report: parent node + chunked children.

        1. Extract entities from full content (one LLM call).
        2. Write Report parent node (no text, no embedding).
        3. Chunk content via chunk_markdown.
        4. For each chunk: build_embed_text -> embed -> write Chunk node.
        5. Wire :HAS_CHUNK relationships (Report -> Chunk).
        6. Wire :PART_OF relationships (Chunk -> Report).
        7. Wire :ABOUT/:MENTIONS entity relationships on chunks.

        Args:
            source: Dict with type, content, project_id, session_id,
                source_agent, title, research_question, findings, citations.

        Returns:
            Summary dict with type, chunks count, entities count, findings count.
        """
        now = self._now()
        content = source["content"]
        project_id = source["project_id"]
        session_id = source["session_id"]

        # 1. Entity extraction on full content (one call)
        entities = self._extractor.extract(content)
        entity_names = [e["name"] for e in entities]
        entity_types = [e["type"] for e in entities]

        # 2. Write Report parent (no text, no embedding per CONTEXT.md)
        report_props: dict[str, Any] = {
            "project_id": project_id,
            "session_id": session_id,
            "title": source.get("title", "Untitled Report"),
            "source_agent": source.get("source_agent", "unknown"),
            "source_key": "deep_research_agent",
            "source_type": "web",
            "ingested_at": now,
            "research_question": source.get("research_question"),
            "ingestion_mode": source.get("ingestion_mode", "active"),
            "embedding_model": None,
            "entities": entity_names,
            "entity_types": entity_types,
        }
        self._writer.write_report_node(report_props)

        # 3. Normalize to markdown and chunk
        raw = RawContent(text=content, format=source.get("format", "markdown"))
        markdown = _to_markdown(raw)
        chunks = chunk_markdown(markdown)

        # 4-6. Embed and write each chunk; wire HAS_CHUNK and PART_OF
        chunk_source_key = "web_crawl4ai"
        for chunk in chunks:
            # CRITICAL: Chunk content_hash encodes (session_id, chunk_index, text)
            # per CONTEXT.md Chunk dedup key of (session_id, chunk_index).
            # Prevents identical text from different sessions collapsing into one node.
            chunk_hash = self._chunk_content_hash(session_id, chunk.index, chunk.text)
            embed_text = build_embed_text(chunk.text, entities)
            embedding = self._embedder.embed(embed_text)

            chunk_props: dict[str, Any] = {
                "text": chunk.text,
                "embedding": embedding,
                "chunk_index": chunk.index,
                "chunk_total": chunk.total,
                "session_id": session_id,
                "project_id": project_id,
                "source_agent": source.get("source_agent", "unknown"),
                "ingested_at": now,
                "embedding_model": "gemini-embedding-2-preview",
                "source_key": chunk_source_key,
                "source_type": "web",
                "content_hash": chunk_hash,
                "ingestion_mode": source.get("ingestion_mode", "active"),
                "entities": entity_names,
                "entity_types": entity_types,
            }
            labels = self.node_labels(chunk_source_key)
            self._writer.write_memory_node(labels, chunk_props)

            # Wire HAS_CHUNK (Report -> Chunk)
            self._writer.write_has_chunk_relationship(
                report_project_id=project_id,
                report_session_id=session_id,
                chunk_source_key=chunk_source_key,
                chunk_content_hash=chunk_hash,
                order=chunk.index,
                valid_from=now,
                confidence=1.0,
            )

            # Wire PART_OF (Chunk -> Report) per CONTEXT.md schema
            self._writer.write_part_of_relationship(
                chunk_source_key=chunk_source_key,
                chunk_content_hash=chunk_hash,
                report_project_id=project_id,
                report_session_id=session_id,
                valid_from=now,
                confidence=1.0,
            )

        # 7. Wire entity relationships on each chunk
        for chunk in chunks:
            chunk_hash = self._chunk_content_hash(session_id, chunk.index, chunk.text)
            for entity in entities:
                self._writer.upsert_entity(entity["name"], entity["type"])
                rel_type = "ABOUT" if entity["type"] == "project" else "MENTIONS"
                self._writer.write_temporal_relationship(
                    source_key=chunk_source_key,
                    content_hash=chunk_hash,
                    entity_name=entity["name"],
                    entity_type=entity["type"],
                    rel_type=rel_type,
                    valid_from=now,
                    confidence=1.0,
                )

        # Also ingest inline findings if provided
        findings_written = 0
        for finding_data in source.get("findings") or []:
            finding_source = {
                "type": "finding",
                "content": finding_data["text"],
                "project_id": project_id,
                "session_id": session_id,
                "source_agent": source.get("source_agent", "unknown"),
                "confidence": finding_data.get("confidence", "medium"),
                "research_question": source.get("research_question"),
                "citations": finding_data.get("citations", []),
                "ingestion_mode": source.get("ingestion_mode", "active"),
            }
            self._ingest_finding(finding_source)
            findings_written += 1

        logger.info(
            "Report ingested: project_id=%s session_id=%s chunks=%d entities=%d",
            project_id,
            session_id,
            len(chunks),
            len(entities),
        )

        return {
            "type": "report",
            "chunks": len(chunks),
            "entities": len(entities),
            "findings": findings_written,
            "project_id": project_id,
            "session_id": session_id,
        }

    def _ingest_finding(self, source: dict[str, Any]) -> dict[str, Any]:
        """Ingest an atomic research finding.

        1. Extract entities.
        2. Compute content_hash for dedup (text-only, NOT session-scoped).
        3. build_embed_text -> embed.
        4. Write Finding node as :Memory:Research:Finding.
        5. For each citation: MERGE Entity:Source, write :CITES relationship.
        6. Wire entity relationships.

        Args:
            source: Dict with type, content, project_id, session_id,
                source_agent, confidence, research_question, citations.

        Returns:
            Summary dict with type, content_hash, citations count, entities count.
        """
        now = self._now()
        text = source["content"]
        # Finding dedup is global on content alone (not session-scoped per CONTEXT.md)
        content_hash = self._content_hash(text)
        source_key = "deep_research_agent"

        # 1. Entity extraction
        entities = self._extractor.extract(text)
        entity_names = [e["name"] for e in entities]
        entity_types = [e["type"] for e in entities]

        # 2-3. Embed with entity context
        embed_text = build_embed_text(text, entities)
        embedding = self._embedder.embed(embed_text)

        # 4. Write Finding node as :Memory:Research:Finding
        finding_props: dict[str, Any] = {
            "text": text,
            "embedding": embedding,
            "content_hash": content_hash,
            "confidence": source.get("confidence", "medium"),
            "session_id": source["session_id"],
            "project_id": source["project_id"],
            "source_agent": source.get("source_agent", "unknown"),
            "research_question": source.get("research_question"),
            "ingested_at": now,
            "ingestion_mode": source.get("ingestion_mode", "active"),
            "embedding_model": "gemini-embedding-2-preview",
            "source_key": source_key,
            "source_type": "web",
            "entities": entity_names,
            "entity_types": entity_types,
        }
        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, finding_props)

        # 5. Citations -> Entity:Source + :CITES
        citations = source.get("citations") or []
        for citation in citations:
            url = citation["url"]
            self._writer.write_source_node(url=url, title=citation.get("title"))
            self._writer.write_cites_relationship(
                finding_source_key=source_key,
                finding_content_hash=content_hash,
                source_url=url,
                rel_props={
                    "url": url,
                    "title": citation.get("title"),
                    "snippet": citation.get("snippet"),
                    "accessed_at": now,
                    "source_agent": source.get("source_agent", "unknown"),
                },
                valid_from=now,
                confidence=1.0,
            )

        # 6. Wire entity relationships
        for entity in entities:
            self._writer.upsert_entity(entity["name"], entity["type"])
            rel_type = "ABOUT" if entity["type"] == "project" else "MENTIONS"
            self._writer.write_temporal_relationship(
                source_key=source_key,
                content_hash=content_hash,
                entity_name=entity["name"],
                entity_type=entity["type"],
                rel_type=rel_type,
                valid_from=now,
                confidence=1.0,
            )

        logger.info(
            "Finding ingested: project_id=%s content_hash=%s citations=%d",
            source["project_id"],
            content_hash,
            len(citations),
        )

        return {
            "type": "finding",
            "content_hash": content_hash,
            "citations": len(citations),
            "entities": len(entities),
            "project_id": source["project_id"],
            "session_id": source["session_id"],
        }
