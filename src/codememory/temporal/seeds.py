"""Build seed entity lists for temporal ``retrieve`` from search rows or queries.

Consumers (e.g. unified search) pass vector-hit rows containing ``entities`` /
``entity_types`` / ``score``; ``collect_seed_entities`` aggregates and ranks
deterministic seeds. ``extract_query_seed_entities`` adds LLM-extracted seeds
from the raw user question. Time-window parsing helpers support ``as_of`` query
parameters and conversation evidence ids.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from codememory.core.entity_extraction import EntityExtractionService


def collect_seed_entities(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Aggregate entity mentions from retrieval rows into ranked seed dicts.

    Args:
        rows: Each row may include ``entities``, ``entity_types``, and ``score``.
        limit: Maximum number of seeds to return after ranking.

    Returns:
        List of ``{"name", "kind", "score"}`` dicts sorted by descending score.
    """
    aggregates: dict[tuple[str, str], dict[str, Any]] = {}

    for row_index, row in enumerate(rows):
        entities = row.get("entities") or []
        entity_types = row.get("entity_types") or []
        row_score = float(row.get("score", 1.0) or 1.0)

        for entity_index, entity_name in enumerate(entities):
            if not entity_name:
                continue
            entity_type = (
                entity_types[entity_index]
                if entity_index < len(entity_types) and entity_types[entity_index]
                else "unknown"
            )
            key = (entity_name.strip().lower(), entity_type)
            weight = row_score / (entity_index + 1)
            current = aggregates.get(key)
            if current is None:
                aggregates[key] = {
                    "name": entity_name,
                    "kind": entity_type,
                    "score": weight,
                    "first_index": row_index,
                }
                continue
            current["score"] += weight
            current["first_index"] = min(current["first_index"], row_index)

    ranked = sorted(
        aggregates.values(),
        key=lambda item: (-float(item["score"]), int(item["first_index"]), str(item["name"]).lower()),
    )
    return [
        {"name": item["name"], "kind": item["kind"], "score": item["score"]}
        for item in ranked[:limit]
    ]


def extract_query_seed_entities(
    query: str,
    extractor: EntityExtractionService,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Extract up to ``limit`` unique entities from the literal user query.

    Args:
        query: Natural-language question or keywords.
        extractor: Configured ``EntityExtractionService`` (same stack as pipelines).
        limit: Cap on distinct (name, type) pairs returned.

    Returns:
        Seed dicts with unit weight scores for ordering compatibility.
    """
    seen: set[tuple[str, str]] = set()
    ranked: list[dict[str, Any]] = []

    for entity in extractor.extract(query):
        name = entity.get("name")
        kind = entity.get("type", "unknown")
        if not name:
            continue
        key = (name.strip().lower(), kind)
        if key in seen:
            continue
        seen.add(key)
        ranked.append({"name": name, "kind": kind, "score": 1.0})
        if len(ranked) >= limit:
            break

    return ranked


def parse_as_of_to_micros(as_of: str | None) -> int | None:
    """Parse an ISO-8601 ``as_of`` string into UTC microseconds since epoch.

    Args:
        as_of: ISO timestamp or None.

    Returns:
        Integer microseconds, or None when input is empty or invalid.
    """
    if not as_of:
        return None
    try:
        normalized = as_of.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000)
    except ValueError:
        return None


def parse_conversation_source_id(source_id: str) -> tuple[str, int]:
    """Split ``session_id:turn_index`` evidence ids used in conversation shadow writes.

    Args:
        source_id: String with the last ``:`` separating integer turn index.

    Returns:
        Tuple of ``(session_id, turn_index)``.

    Raises:
        ValueError: If the turn index is not a valid integer (propagated from ``int``).
    """
    session_id, raw_turn_index = source_id.rsplit(":", 1)
    return session_id, int(raw_turn_index)
