"""Pydantic request/response models for am_server endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class CitationModel(BaseModel):
    """A citation reference for a research finding."""

    url: str
    title: str | None = None
    snippet: str | None = None


class FindingModel(BaseModel):
    """An atomic research finding with optional citations."""

    text: str
    confidence: str | None = None
    citations: list[CitationModel] = []


class ResearchIngestRequest(BaseModel):
    """Request body for POST /ingest/research.

    session_id MUST come from the caller — the server never generates it.
    This preserves the (project_id, session_id) dedup contract in Neo4j.
    """

    type: str  # "report" | "finding"
    content: str
    project_id: str
    session_id: str  # REQUIRED — caller owns session identity
    source_agent: str  # "claude" | "perplexity" | "chatgpt" | "custom"
    title: str | None = None
    research_question: str | None = None
    confidence: str | None = None
    findings: list[FindingModel] | None = None
    citations: list[CitationModel] | None = None
