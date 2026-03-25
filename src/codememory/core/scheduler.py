"""Recurring research scheduler for temporal web-memory ingestion.

Uses APScheduler with a persistent SQLite job store to drive recurring
Brave Search runs, then ingests the resulting findings into Neo4j.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from groq import Groq

from codememory.core.connection import ConnectionManager
from codememory.ingestion.graph import CircuitBreaker

logger = logging.getLogger(__name__)

SCHEDULES_DB = Path("~/.config/agentic-memory/schedules.db").expanduser()
MAX_RUNS_PER_DAY_DEFAULT = 5
BRAVE_CIRCUIT_RESET_SECONDS = 3600
BRAVE_FAILURE_THRESHOLD = 3


def _utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_variables(variables: Sequence[str]) -> list[str]:
    """Normalize placeholder names by trimming whitespace and braces."""
    normalized: list[str] = []
    for variable in variables:
        clean = variable.strip()
        if clean.startswith("{") and clean.endswith("}"):
            clean = clean[1:-1].strip()
        if clean:
            normalized.append(clean)
    return normalized


def _apply_template(template: str, values: dict[str, str]) -> str:
    """Apply variable values to a template without raising on missing keys."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _resolve_brave_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve Brave Search API key from explicit input or environment."""
    return explicit_key or os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")


def _build_pipeline_from_env(connection_manager: ConnectionManager | None = None) -> Any:
    """Create a ResearchIngestionPipeline from environment variables."""
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not google_api_key or not groq_api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY/GEMINI_API_KEY and GROQ_API_KEY are required for the research scheduler."
        )

    from codememory.core.embedding import EmbeddingService  # noqa: PLC0415
    from codememory.core.entity_extraction import EntityExtractionService  # noqa: PLC0415
    from codememory.web.pipeline import ResearchIngestionPipeline  # noqa: PLC0415

    conn = connection_manager or _build_connection_from_env()
    embedder = EmbeddingService(provider="gemini", api_key=google_api_key)
    extractor = EntityExtractionService(api_key=groq_api_key)
    return ResearchIngestionPipeline(conn, embedder, extractor)


def _build_connection_from_env() -> ConnectionManager:
    """Create a Neo4j connection manager from environment variables."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    return ConnectionManager(uri, user, password)


def build_scheduler_from_env(
    *,
    start_scheduler: bool = True,
    connection_manager: ConnectionManager | None = None,
    pipeline: Any = None,
    groq_api_key: str | None = None,
    brave_api_key: str | None = None,
    groq_model: str | None = None,
) -> "ResearchScheduler":
    """Create a scheduler instance from environment-backed dependencies."""
    conn = connection_manager or _build_connection_from_env()
    resolved_pipeline = pipeline or _build_pipeline_from_env(conn)
    return ResearchScheduler(
        connection_manager=conn,
        groq_api_key=groq_api_key or os.getenv("GROQ_API_KEY"),
        groq_model=groq_model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        brave_api_key=_resolve_brave_api_key(brave_api_key),
        pipeline=resolved_pipeline,
        start_scheduler=start_scheduler,
    )


def _sync_run_research_job(schedule_id: str) -> None:
    """Run a persisted schedule job from APScheduler's background thread."""
    scheduler = build_scheduler_from_env(start_scheduler=False)
    try:
        scheduler.run_research_session(schedule_id=schedule_id)
    finally:
        scheduler.close()


class ResearchScheduler:
    """Persistent recurring research scheduler backed by APScheduler and Neo4j."""

    def __init__(
        self,
        connection_manager: ConnectionManager,
        groq_api_key: str | None,
        groq_model: str,
        brave_api_key: str | None,
        pipeline: Any,
        *,
        start_scheduler: bool = True,
    ) -> None:
        """Initialize a scheduler instance.

        Args:
            connection_manager: Neo4j connection manager for schedule reads/writes.
            groq_api_key: Groq API key for variable filling.
            groq_model: Groq model name used for variable filling.
            brave_api_key: Brave Search API key.
            pipeline: ResearchIngestionPipeline used to ingest search results.
            start_scheduler: When True, starts the APScheduler background worker.
        """
        self._conn = connection_manager
        self._pipeline = pipeline
        self._groq_model = groq_model
        self._groq_api_key = groq_api_key
        self._brave_api_key = brave_api_key
        self._client = Groq(api_key=groq_api_key) if groq_api_key else None
        self._scheduler: BackgroundScheduler | None = None
        self._brave_breaker = CircuitBreaker(
            failure_threshold=BRAVE_FAILURE_THRESHOLD,
            recovery_timeout=BRAVE_CIRCUIT_RESET_SECONDS,
        )
        self._brave_failures = 0
        self._brave_circuit_open_until = 0.0

        if start_scheduler:
            SCHEDULES_DB.parent.mkdir(parents=True, exist_ok=True)
            jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{SCHEDULES_DB}")}
            self._scheduler = BackgroundScheduler(jobstores=jobstores, daemon=True)
            self._scheduler.start()

    def close(self) -> None:
        """Release scheduler and Neo4j resources owned by this instance."""
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                logger.debug("Scheduler shutdown skipped during close.", exc_info=True)
        self._conn.close()

    def create_schedule(
        self,
        template: str,
        variables: Sequence[str],
        cron_expr: str,
        project_id: str,
        max_runs_per_day: int = MAX_RUNS_PER_DAY_DEFAULT,
    ) -> str:
        """Persist and register a recurring research schedule.

        Args:
            template: Query template containing ``{variable}`` placeholders.
            variables: Variable names to fill via the LLM.
            cron_expr: Standard 5-field cron expression.
            project_id: Project identifier used for schedule scoping.
            max_runs_per_day: Maximum number of runs to allow before skipping.

        Returns:
            The generated schedule UUID.
        """
        if self._scheduler is None:
            raise RuntimeError("Background scheduler is disabled for this instance.")

        schedule_id = str(uuid.uuid4())
        normalized_variables = _normalize_variables(variables)
        created_at = _utc_now()

        with self._conn.session() as session:
            session.run(
                """
                MERGE (s:Schedule {schedule_id: $schedule_id})
                SET s.template = $template,
                    s.variables = $variables,
                    s.cron_expr = $cron_expr,
                    s.project_id = $project_id,
                    s.created_at = $created_at,
                    s.last_run_at = null,
                    s.run_count = 0,
                    s.max_runs_per_day = $max_runs_per_day
                """,
                schedule_id=schedule_id,
                template=template,
                variables=normalized_variables,
                cron_expr=cron_expr,
                project_id=project_id,
                created_at=created_at,
                max_runs_per_day=max_runs_per_day,
            )

        self._scheduler.add_job(
            func=_sync_run_research_job,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=schedule_id,
            replace_existing=True,
            kwargs={"schedule_id": schedule_id},
        )
        return schedule_id

    def run_research_session(
        self,
        schedule_id: str | None = None,
        ad_hoc_template: str | None = None,
        ad_hoc_variables: Sequence[str] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a scheduled or ad hoc research session synchronously.

        Args:
            schedule_id: Optional persisted schedule identifier.
            ad_hoc_template: Template used for ad hoc execution.
            ad_hoc_variables: Variable names for ad hoc execution.
            project_id: Project ID for ad hoc execution.

        Returns:
            Dict containing run status, result count, and the final query.
        """
        schedule: dict[str, Any] | None = None
        if schedule_id:
            schedule = self._load_schedule(schedule_id)
            if not schedule:
                return {"status": "error", "error": f"Schedule not found: {schedule_id}"}
        elif ad_hoc_template and project_id:
            schedule = {
                "schedule_id": None,
                "template": ad_hoc_template,
                "variables": _normalize_variables(ad_hoc_variables or []),
                "project_id": project_id,
                "run_count": 0,
                "max_runs_per_day": MAX_RUNS_PER_DAY_DEFAULT,
            }
        else:
            return {
                "status": "error",
                "error": "Provide schedule_id or (project_id + ad_hoc_template).",
            }

        schedule_project_id = str(schedule["project_id"])
        if schedule_id and int(schedule.get("run_count", 0)) >= int(
            schedule.get("max_runs_per_day", MAX_RUNS_PER_DAY_DEFAULT)
        ):
            logger.warning("Skipping schedule %s: max_runs_per_day reached.", schedule_id)
            return {"status": "skipped", "reason": "max_runs_per_day"}

        if time.time() < self._brave_circuit_open_until:
            logger.warning("Skipping schedule %s: Brave circuit is open.", schedule_id)
            return {"status": "skipped", "reason": "brave_circuit_open"}

        filled_values = self._fill_variable_values(
            template=str(schedule["template"]),
            variables=schedule.get("variables") or [],
            project_id=schedule_project_id,
        )
        filled_query = _apply_template(str(schedule["template"]), filled_values)
        if not filled_query.strip():
            return {"status": "skipped", "reason": "empty_query"}

        search_payload = self._brave_search(filled_query)
        if search_payload.get("status") != "ok":
            return search_payload

        results = search_payload["results"]
        run_started_at = _utc_now()
        ingested = 0
        for index, result in enumerate(results):
            text = result.get("description") or result.get("title") or filled_query
            citation = {
                "url": result.get("url"),
                "title": result.get("title"),
                "snippet": result.get("description"),
            }
            self._pipeline.ingest(
                {
                    "type": "finding",
                    "content": text,
                    "project_id": schedule_project_id,
                    "session_id": (
                        f"scheduled:{schedule_id or 'adhoc'}:{run_started_at}:{index}"
                    ),
                    "source_agent": "scheduler",
                    "research_question": filled_query,
                    "confidence": "medium",
                    "citations": [citation] if citation["url"] else [],
                    "ingestion_mode": "scheduled",
                }
            )
            ingested += 1

        self._record_researched_topic(
            project_id=schedule_project_id,
            topic=filled_values.get("topic") or filled_query,
            valid_from=run_started_at,
        )

        if schedule_id:
            with self._conn.session() as session:
                session.run(
                    """
                    MATCH (s:Schedule {schedule_id: $schedule_id})
                    SET s.last_run_at = $last_run_at,
                        s.run_count = coalesce(s.run_count, 0) + 1
                    """,
                    schedule_id=schedule_id,
                    last_run_at=run_started_at,
                )

        return {"status": "ok", "results": ingested, "query": filled_query}

    def list_schedules(self, project_id: str) -> list[dict[str, Any]]:
        """List all schedules for a given project."""
        with self._conn.session() as session:
            results = session.run(
                """
                MATCH (s:Schedule {project_id: $project_id})
                RETURN s{.*} AS schedule
                ORDER BY s.created_at ASC
                """,
                project_id=project_id,
            ).data()
        return [row["schedule"] for row in results]

    def _load_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        """Load one schedule record from Neo4j."""
        with self._conn.session() as session:
            row = session.run(
                """
                MATCH (s:Schedule {schedule_id: $schedule_id})
                RETURN s{.*} AS schedule
                """,
                schedule_id=schedule_id,
            ).single()
        if not row:
            return None
        return row["schedule"]

    def _fill_variables(
        self,
        template: str,
        variables: Sequence[str],
        project_id: str,
    ) -> str:
        """Return a rendered query string after LLM-backed variable filling."""
        values = self._fill_variable_values(template, variables, project_id)
        return _apply_template(template, values)

    def _fill_variable_values(
        self,
        template: str,
        variables: Sequence[str],
        project_id: str,
    ) -> dict[str, str]:
        """Fill template variables using recent RESEARCHED edges and Groq JSON mode."""
        variable_names = _normalize_variables(variables)
        if not variable_names:
            return {}

        with self._conn.session() as session:
            rows = session.run(
                """
                MATCH ()-[r:RESEARCHED]->(e)
                WHERE r.project_id = $project_id
                RETURN e.name AS topic, r.valid_from AS researched_at
                ORDER BY r.valid_from DESC
                LIMIT 10
                """,
                project_id=project_id,
            ).data()

        if self._client is None:
            logger.warning("Groq client not configured; falling back to empty variable fill.")
            return {name: "" for name in variable_names}

        prompt = (
            "Fill the requested template variables for a recurring research schedule.\n"
            f"Template: {template}\n"
            f"Variables: {json.dumps(variable_names)}\n"
            f"Project ID: {project_id}\n"
            f"Recent researched topics: {json.dumps(rows)}\n"
            "Return a JSON object with one string value per variable name. "
            "Prefer uncovered angles and avoid repeating recent topics."
        )
        try:
            response = self._client.chat.completions.create(
                model=self._groq_model,
                messages=[
                    {"role": "system", "content": "You generate research schedule variables."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            payload = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:
            logger.error("Variable fill failed for project %s: %s", project_id, exc)
            return {name: "" for name in variable_names}

        return {
            name: str(payload.get(name, "")).strip()
            for name in variable_names
        }

    def _brave_search(self, query: str, count: int = 5) -> dict[str, Any]:
        """Execute Brave Search with circuit-breaker handling."""
        if not self._brave_api_key:
            return {
                "status": "error",
                "error": "BRAVE_SEARCH_API_KEY or BRAVE_API_KEY is required.",
            }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "X-Subscription-Token": self._brave_api_key,
                        "Accept": "application/json",
                    },
                    params={"q": query, "count": max(1, min(int(count), 20))},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            self._record_brave_failure()
            logger.error("Brave Search failed for %r: %s", query, exc)
            return {"status": "error", "error": str(exc)}

        self._reset_brave_failures()
        return {"status": "ok", "results": payload.get("web", {}).get("results", [])}

    def _record_brave_failure(self) -> None:
        """Record a Brave Search failure and open the circuit if needed."""
        self._brave_breaker._record_failure()
        self._brave_failures = self._brave_breaker.failure_count
        if self._brave_breaker.state == "OPEN":
            opened_at = self._brave_breaker.last_failure_time or time.time()
            self._brave_circuit_open_until = opened_at + BRAVE_CIRCUIT_RESET_SECONDS

    def _reset_brave_failures(self) -> None:
        """Reset Brave Search failure tracking after a successful call."""
        self._brave_breaker.failure_count = 0
        self._brave_breaker.last_failure_time = None
        self._brave_breaker.state = "CLOSED"
        self._brave_failures = 0
        self._brave_circuit_open_until = 0.0

    def _record_researched_topic(self, project_id: str, topic: str, valid_from: str) -> None:
        """Write a temporal RESEARCHED relationship for steering future runs."""
        clean_topic = topic.strip()
        if not clean_topic:
            return

        with self._conn.session() as session:
            session.run(
                """
                MERGE (p:Entity {name: $project_id, type: 'project'})
                MERGE (t:Entity {name: $topic, type: 'concept'})
                MERGE (p)-[r:RESEARCHED]->(t)
                ON CREATE SET r.valid_from = $valid_from,
                              r.valid_to = null,
                              r.confidence = 1.0,
                              r.support_count = 1,
                              r.contradiction_count = 0,
                              r.project_id = $project_id
                ON MATCH SET  r.support_count = coalesce(r.support_count, 0) + 1,
                              r.project_id = $project_id,
                              r.confidence = CASE
                                  WHEN coalesce(r.confidence, 0.0) < 1.0 THEN 1.0
                                  ELSE r.confidence
                              END
                """,
                project_id=project_id,
                topic=clean_topic,
                valid_from=valid_from,
            )
