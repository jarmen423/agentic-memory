"""Pydantic request/response models for am_server endpoints.

The OpenClaw-facing models intentionally separate three concerns:

- stable identity: workspace / device / agent / session
- active project state: an optional server-resolved project binding
- context augmentation mode: whether Agentic Memory should only capture turns
  or also assemble custom context for the host
"""

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
    project_id: str | None = None
    turn_index: int
    workspace_id: str | None = None
    device_id: str | None = None
    agent_id: str | None = None
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


class OpenClawIdentityModel(BaseModel):
    """Common identity fields used by OpenClaw-facing endpoints."""

    workspace_id: str
    device_id: str
    agent_id: str
    session_id: str
    project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenClawProjectScopedIdentityModel(OpenClawIdentityModel):
    """OpenClaw identity that may resolve an active project server-side.

    Clients can still send an explicit ``project_id`` when they want a one-off
    override. When omitted, the backend may fill it from the active project
    binding for this workspace/agent/session tuple.
    """


class OpenClawProjectCommandIdentityModel(OpenClawProjectScopedIdentityModel):
    """Project-command identity where `session_id` may be inferred by the server.

    Project lifecycle commands should feel like agent-level actions in
    OpenClaw. The backend therefore accepts an omitted `session_id` and
    resolves the latest registered live session for this workspace/agent when
    possible.
    """

    session_id: str | None = None


class OpenClawProjectActivationRequest(OpenClawProjectCommandIdentityModel):
    """Request body for activating a project for the current OpenClaw session."""

    project_id: str
    title: str | None = None


class OpenClawProjectDeactivationRequest(OpenClawProjectCommandIdentityModel):
    """Request body for clearing the active project for the current session."""


class OpenClawProjectStatusRequest(OpenClawProjectCommandIdentityModel):
    """Request body for querying the active project for the current session."""


class OpenClawProjectAutomationRequest(BaseModel):
    """Request body for configuring project automation.

    Automations are workspace/project scoped because a shared project can have
    different automation policies in different home-base workspaces.
    """

    workspace_id: str
    project_id: str
    automation_kind: str = "research_ingestion"
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenClawSessionRegisterRequest(OpenClawIdentityModel):
    """Request body for registering an OpenClaw agent session."""

    context_engine: str = "agentic-memory"
    mode: str = "capture_only"


class OpenClawMemorySearchRequest(OpenClawProjectScopedIdentityModel):
    """Request body for OpenClaw memory search."""

    query: str
    limit: int = 10
    as_of: str | None = None
    modules: list[str] | None = None


class OpenClawMemoryReadRequest(OpenClawIdentityModel):
    """Request body for canonical OpenClaw memory reads.

    The plugin passes the same stable `rel_path` identifier returned from
    `/openclaw/memory/search`. For conversation hits this is currently the
    `source_id` form `session_id:turn_index`.
    """

    rel_path: str
    from_line: int | None = None
    lines: int | None = None


class OpenClawContextResolveRequest(OpenClawProjectScopedIdentityModel):
    """Request body for OpenClaw context resolution."""

    query: str
    limit: int = 10
    as_of: str | None = None
    modules: list[str] | None = None
    context_budget_tokens: int = 8000
    include_system_prompt: bool = True
    context_engine: str = "agentic-memory"


class OpenClawTurnIngestRequest(OpenClawProjectScopedIdentityModel):
    """Request body for the OpenClaw-native turn-ingestion contract.

    This route exists so the plugin can treat memory capture as its own domain.
    The backend resolves the active project when present and then forwards the
    normalized turn to the existing conversation ingestion pipeline.
    """

    role: str
    content: str
    turn_index: int
    source_agent: str | None = None
    model: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    timestamp: str | None = None
    ingestion_mode: str = "active"
    source_key: str = "chat_openclaw"
