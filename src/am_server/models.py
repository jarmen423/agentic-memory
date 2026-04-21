"""Pydantic schemas for ``am_server`` HTTP request and response bodies.

These models are the contract between FastAPI route functions and JSON
payloads. Validation runs automatically when a route declares a body parameter
typed with one of these classes.

OpenClaw-facing types intentionally separate three concerns:

* **Stable identity** — workspace, device, agent, and session identifiers the
  plugin sends on every call.
* **Active project state** — optional server-resolved project binding when the
  client omits ``project_id``.
* **Context mode** — whether the stack only captures turns or also assembles
  custom context for the host (see session registration defaults).

Attributes on each model mirror JSON field names; optional fields map to
nullable or omitted keys per Pydantic defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiErrorModel(BaseModel):
    """Machine-readable API error payload used by the FastAPI exception layer.

    The OpenClaw foundation wave standardizes errors so operators and clients
    can reliably branch on ``code`` while still seeing the request correlation
    id that ties UI failures back to server logs.

    Attributes:
        code: Stable machine-readable error code (contrast with HTTP status).
        message: Human-readable summary for display or logs.
        request_id: Correlation id from middleware/context; matches
            ``X-Request-ID`` on the response when present.
        status: HTTP status code echoed for clients that only parse JSON bodies.
        details: Optional structured payload (validation errors, nested causes).
    """

    code: str
    message: str
    request_id: str
    status: int
    details: Any | None = None


class ApiErrorEnvelopeModel(BaseModel):
    """Top-level error response envelope returned by am-server."""

    error: ApiErrorModel


class OpenClawOnboardingServiceModel(BaseModel):
    """One service or capability reported in the onboarding readiness contract.

    This model exists to make the onboarding contract machine-readable for the
    desktop shell, future plugin doctor commands, and any support tooling that
    needs to answer a practical question:

    *What exactly is blocked right now, and is it truly required?*

    Attributes:
        service_id: Stable machine-readable identifier for the dependency.
        label: Operator-facing label suitable for UI cards or CLI output.
        required: Whether this dependency must be healthy for the basic
            supported OpenClaw onboarding path.
        status: Normalized health state such as ``healthy``, ``degraded``,
            ``missing_config``, or ``unknown``.
        summary: Short human-readable explanation of what the service does.
        component: Optional backing product-state runtime component id when the
            service is derived from ``ProductStateStore.runtime.components``.
        depends_on: Other ``service_id`` values that this service builds on.
        details: Structured diagnostics safe to expose in health/bootstrap
            payloads.
    """

    service_id: str
    label: str
    required: bool
    status: str
    summary: str
    component: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class OpenClawOnboardingReadinessModel(BaseModel):
    """High-level booleans derived from the per-service onboarding contract.

    We separate these rollups from the individual service rows so the shell and
    future plugin-side doctor command can tell users quickly whether they are
    ready for:

    - saving a supported setup configuration at all,
    - basic ``capture_only`` memory capture,
    - richer ``augment_context`` behavior.
    """

    setup_ready: bool
    capture_only_ready: bool
    augment_context_ready: bool
    public_mcp_temporal_status: str = "unknown"
    public_mcp_temporal_ready: bool = False
    public_mcp_publication_ready: bool = False
    required_healthy: int
    required_total: int
    optional_healthy: int
    optional_total: int
    blocking_services: list[str] = Field(default_factory=list)
    degraded_optional_services: list[str] = Field(default_factory=list)


class OpenClawOnboardingContractModel(BaseModel):
    """Whole-stack onboarding contract exposed by the backend health surface.

    The contract deliberately mixes three layers in one payload:

    - install/setup commands the product currently supports,
    - required vs optional services for that path,
    - computed readiness booleans that the shell and plugin can act on.
    """

    status: str
    deployment_mode: str
    supported_deployment_modes: list[str] = Field(default_factory=list)
    auth_strategy: str
    provider_key_mode: str
    hosted_base_url: str | None = None
    plugin_package_name: str
    plugin_id: str
    install_command: str
    setup_command: str
    doctor_command: str
    required_services: list[OpenClawOnboardingServiceModel] = Field(default_factory=list)
    optional_services: list[OpenClawOnboardingServiceModel] = Field(default_factory=list)
    readiness: OpenClawOnboardingReadinessModel
    notes: list[str] = Field(default_factory=list)


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
    repo_id: str | None = None
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


class OpenClawToolSearchCodebaseRequest(OpenClawProjectScopedIdentityModel):
    """Request body for the OpenClaw `search_codebase` tool bridge."""

    query: str
    limit: int = 5
    domain: str = "code"
    repo_id: str | None = None


class OpenClawToolFileDependenciesRequest(OpenClawProjectScopedIdentityModel):
    """Request body for the OpenClaw `get_file_dependencies` tool bridge."""

    file_path: str
    repo_id: str | None = None


class OpenClawToolTraceExecutionPathRequest(OpenClawProjectScopedIdentityModel):
    """Request body for the OpenClaw `trace_execution_path` tool bridge."""

    start_symbol: str
    max_depth: int = 2
    force_refresh: bool = False
    repo_id: str | None = None


class OpenClawToolConversationSearchRequest(OpenClawProjectScopedIdentityModel):
    """Request body for the OpenClaw `search_conversations` tool bridge."""

    query: str
    limit: int = 10
    role: str | None = None
    as_of: str | None = None


class OpenClawToolConversationContextRequest(OpenClawProjectScopedIdentityModel):
    """Request body for the OpenClaw `get_conversation_context` tool bridge."""

    query: str
    limit: int = 5
    include_session_context: bool = True
    as_of: str | None = None


class OpenClawToolIdentityRequest(OpenClawIdentityModel):
    """Identity-only request body for OpenClaw tool routes without extra inputs."""


class OpenClawDashboardMetricCardModel(BaseModel):
    """One top-level dashboard metric card."""

    key: str
    label: str
    value: int | float
    unit: str | None = None
    status: str = "info"
    description: str | None = None


class OpenClawDashboardSummaryModel(BaseModel):
    """Overview payload used by the dashboard home page."""

    active_agents: int
    active_sessions: int
    turns_ingested: int
    searches_total: int
    context_resolves_total: int
    error_responses_total: int
    health_score: int
    cards: list[OpenClawDashboardMetricCardModel] = Field(default_factory=list)


class OpenClawDashboardAgentSessionModel(BaseModel):
    """Latest-known state for one OpenClaw agent session."""

    workspace_id: str
    device_id: str | None = None
    agent_id: str
    session_id: str
    status: str
    mode: str | None = None
    project_id: str | None = None
    context_engine: str | None = None
    integration_updated_at: str | None = None
    last_activity_at: str | None = None
    event_count: int = 0


class OpenClawDashboardHealthComponentModel(BaseModel):
    """Normalized runtime health record for one backend component."""

    component: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None


class OpenClawDashboardRequestMetricModel(BaseModel):
    """Structured request metric suitable for dashboard charts and tables."""

    method: str
    path: str
    status_code: int
    count: int
    avg_seconds: float | None = None


class OpenClawDashboardErrorMetricModel(BaseModel):
    """Structured normalized error counter for dashboard diagnostics."""

    code: str
    path: str
    status_code: int
    count: int


class OpenClawDashboardRecentSearchModel(BaseModel):
    """Recent search or context-resolution activity visible to operators."""

    event_type: str
    timestamp: str
    workspace_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    query: str | None = None
    result_count: int | None = None
    project_id: str | None = None


class OpenClawDashboardWorkspaceAgentModel(BaseModel):
    """One agent grouped under a workspace/device entry."""

    agent_id: str
    session_id: str
    status: str
    project_id: str | None = None
    mode: str | None = None
    context_engine: str | None = None
    updated_at: str | None = None


class OpenClawDashboardWorkspaceDeviceModel(BaseModel):
    """One device node in the dashboard workspace tree."""

    device_id: str
    agents: list[OpenClawDashboardWorkspaceAgentModel] = Field(default_factory=list)


class OpenClawDashboardWorkspaceModel(BaseModel):
    """Workspace topology used by the dashboard workspace page."""

    workspace_id: str
    devices: list[OpenClawDashboardWorkspaceDeviceModel] = Field(default_factory=list)
    active_projects: list[dict[str, Any]] = Field(default_factory=list)
    automations: list[dict[str, Any]] = Field(default_factory=list)
