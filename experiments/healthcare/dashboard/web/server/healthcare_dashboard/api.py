"""Read-only HTTP API for healthcare experiment dashboard data.

SQL mirrors ``DASHBOARD_BUILD_AGENT_PROMPT.md``; user filters are always passed
as query parameters (parameterized) to avoid injection.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from psycopg import OperationalError, ProgrammingError

from healthcare_dashboard.db import cursor

router = APIRouter(prefix="/api")

ANSWER_SORT_COLUMNS = frozenset(
    {"exp3_focus_score", "total_tokens", "latency_ms", "estimated_cost_usd"}
)


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; does not require DB."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> dict[str, str]:
    """Verify Postgres connectivity."""
    try:
        with cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
        if not row or row.get("ok") != 1:
            raise HTTPException(status_code=503, detail="unexpected_db_response")
        return {"status": "ok", "database": "connected"}
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc


@router.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    sql = """
        SELECT
            run_id,
            experiment,
            variant,
            context_arm,
            n_tasks,
            requested_model,
            reasoning_effort,
            imported_at
        FROM experiment_runs
        ORDER BY imported_at DESC
    """
    try:
        with cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return jsonable_encoder(rows)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc


@router.get("/arms/summary")
def arms_summary(
    include_smoke: Annotated[
        bool,
        Query(
            description="If false, exclude NULL/empty context_arm (smoke/dev rows).",
        ),
    ] = False,
) -> list[dict[str, Any]]:
    if include_smoke:
        where = "TRUE"
    else:
        where = "context_arm IS NOT NULL AND context_arm <> ''"
    sql = f"""
        SELECT
            context_arm,
            count(*) AS answers,
            round(avg(exp3_focus_score)::numeric, 4) AS avg_focus,
            round(avg(total_tokens)::numeric, 1) AS avg_tokens,
            round(avg(latency_ms)::numeric, 1) AS avg_latency_ms,
            round(avg(estimated_cost_usd)::numeric, 6) AS avg_cost
        FROM experiment_model_answers
        WHERE {where}
        GROUP BY context_arm
        ORDER BY context_arm
    """
    try:
        with cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return jsonable_encoder(rows)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc


@router.get("/answers")
def list_answers(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    sort: Annotated[
        Literal["exp3_focus_score", "total_tokens", "latency_ms", "estimated_cost_usd"],
        Query(description="Whitelist sort column"),
    ] = "exp3_focus_score",
    order: SortOrder = SortOrder.desc,
    run_id: Annotated[str | None, Query(description="Filter by run_id")] = None,
    context_arm: Annotated[str | None, Query()] = None,
    parse_ok: Annotated[bool | None, Query()] = None,
    patient_id: Annotated[str | None, Query()] = None,
    include_smoke: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    if sort not in ANSWER_SORT_COLUMNS:
        raise HTTPException(status_code=400, detail="invalid_sort_column")
    order_sql = "ASC" if order == SortOrder.asc else "DESC"
    # NULLS LAST for score sorts feels natural for "worst first" in desc
    nulls = "NULLS LAST" if order == SortOrder.desc else "NULLS FIRST"

    conditions: list[str] = ["TRUE"]
    params: list[Any] = []

    if not include_smoke:
        conditions.append("(context_arm IS NOT NULL AND context_arm <> '')")

    if run_id is not None:
        conditions.append("run_id = %s")
        params.append(run_id)

    if context_arm is not None:
        conditions.append("context_arm = %s")
        params.append(context_arm)

    if parse_ok is not None:
        conditions.append("parse_ok = %s")
        params.append(parse_ok)

    if patient_id is not None:
        conditions.append("patient_id = %s")
        params.append(patient_id)

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * page_size

    count_sql = f"""
        SELECT count(*)::bigint AS total
        FROM experiment_model_answers
        WHERE {where_clause}
    """
    # sort / order_sql / nulls are whitelisted; offset/limit are bound as parameters.
    data_sql = f"""
        SELECT
            run_id,
            task_index,
            task_id,
            patient_id,
            snapshot_date,
            context_arm,
            exp3_focus_score,
            total_tokens,
            latency_ms,
            estimated_cost_usd,
            parse_ok,
            finish_reason,
            resolved_model
        FROM experiment_model_answers
        WHERE {where_clause}
        ORDER BY {sort} {order_sql} {nulls}, run_id, task_index
        OFFSET %s LIMIT %s
    """
    try:
        with cursor() as cur:
            cur.execute(count_sql, params)
            total_row = cur.fetchone()
            total = int(total_row["total"]) if total_row else 0
            cur.execute(data_sql, [*params, offset, page_size])
            rows = cur.fetchall()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": jsonable_encoder(rows),
        }
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc


@router.get("/answers/detail")
def answer_detail(
    run_id: Annotated[str, Query()],
    task_index: Annotated[int, Query(ge=0)],
) -> dict[str, Any]:
    sql = """
        SELECT
            run_id,
            task_index,
            task_id,
            patient_id,
            snapshot_date,
            context_arm,
            resolved_model,
            requested_model,
            provider,
            finish_reason,
            parse_ok,
            latency_ms,
            total_tokens,
            input_tokens,
            output_tokens,
            reasoning_tokens,
            estimated_cost_usd,
            exp3_focus_score,
            future_issue_recall,
            history_relevance_recall,
            grounded_evidence_rate,
            hallucination_rate,
            raw_text,
            parsed_json,
            score_json,
            usage_json
        FROM experiment_model_answers
        WHERE run_id = %s AND task_index = %s
    """
    try:
        with cursor() as cur:
            cur.execute(sql, (run_id, task_index))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="answer_not_found")
        return jsonable_encoder(row)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc
    except ProgrammingError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "query_error", "message": str(exc)},
        ) from exc


@router.get("/poor-tasks")
def poor_tasks(
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            run_id,
            task_index,
            task_id,
            patient_id,
            context_arm,
            exp3_focus_score,
            future_issue_recall,
            grounded_evidence_rate,
            hallucination_rate,
            total_tokens,
            latency_ms,
            parse_ok,
            finish_reason
        FROM experiment_model_answers
        WHERE exp3_focus_score IS NOT NULL
        ORDER BY exp3_focus_score ASC NULLS LAST
        LIMIT %s
    """
    try:
        with cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
        return jsonable_encoder(rows)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc


@router.get("/tasks/{task_id}/by-arm")
def task_by_arm(task_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            run_id,
            task_index,
            context_arm,
            exp3_focus_score,
            total_tokens,
            latency_ms,
            parsed_json
        FROM experiment_model_answers
        WHERE task_id = %s
        ORDER BY context_arm, run_id
    """
    try:
        with cursor() as cur:
            cur.execute(sql, (task_id,))
            rows = cur.fetchall()
        return jsonable_encoder(rows)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": str(exc)},
        ) from exc
    except ProgrammingError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "query_error", "message": str(exc)},
        ) from exc
