"""Pydantic request/response models for am_server endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CitationModel(BaseModel):
    """A citation reference for a research finding."""

    url: str
    title: str | None = None
    snippet: str | None = None


class FindingModel(BaseModel):
    """An atomic research finding with optional citations."""

    text: str
    confidence: str | None = None
    citations: list[CitationModel] = Field(default_factory=list)


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


class ConversationIngestRequest(BaseModel):
    """Request body for POST /ingest/conversation.

    session_id MUST come from the caller — the server never generates it.
    turn_index is the 0-based position of this turn within the session.
    """

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    session_id: str  # REQUIRED — caller owns session identity
    project_id: str
    turn_index: int
    source_agent: str | None = None
    model: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    timestamp: str | None = None
    ingestion_mode: str = "active"
    source_key: str = "chat_mcp"


class ProductRepoUpsertRequest(BaseModel):
    """Request body for creating or updating a tracked repository."""

    repo_path: str
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductIntegrationUpsertRequest(BaseModel):
    """Request body for creating or updating an integration status."""

    surface: str
    target: str
    status: str
    config: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


class ProductComponentStatusRequest(BaseModel):
    """Request body for component health updates."""

    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class ProductEventRequest(BaseModel):
    """Request body for product event ingestion."""

    event_type: str
    status: str = "ok"
    actor: str = "api"
    details: dict[str, Any] = Field(default_factory=dict)


class ProductOnboardingStepRequest(BaseModel):
    """Request body for onboarding progress updates."""

    step: str
    completed: bool = True
