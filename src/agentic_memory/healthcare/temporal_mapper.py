"""Temporal mapper — converts Synthea CSV rows to SpacetimeDB claim dicts.

Synthea stores clinical events with structured date fields (START, STOP, DATE).
This module converts those date strings to the microsecond timestamps that
TemporalBridge.ingest_claim() / ingest_relation() expect, and assembles the
full kwargs dict for each clinical record type.

Supported mappings:
  - conditions.csv   → DIAGNOSED_WITH claim (valid_from=START, valid_to=STOP)
  - medications.csv  → PRESCRIBED claim (valid_from=START, valid_to=STOP)
  - observations.csv → OBSERVED claim (point-in-time, no valid_to)
  - procedures.csv   → UNDERWENT claim (point-in-time, no valid_to)

All output dicts are ready to be unpacked as **kwargs into
TemporalBridge.ingest_claim().

Role in the project:
  Used exclusively by HealthcareIngestionPipeline._shadow_write_clinical_claim()
  to feed temporal data into SpacetimeDB for Experiment 1 (temporal decay
  retrieval benchmarks). Neo4j writes happen separately via GraphWriter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def date_to_micros(date_str: str | None) -> int | None:
    """Convert a Synthea date string to UTC midnight microseconds.

    Synthea dates use ISO format: "YYYY-MM-DD" (no time component).
    We interpret them as UTC midnight for consistent temporal ordering.

    Args:
        date_str: Date string in "YYYY-MM-DD" format, or None.

    Returns:
        Integer microseconds since Unix epoch (UTC midnight), or None if
        date_str is None or empty.

    Examples:
        >>> date_to_micros("2015-03-12")
        1426118400000000
        >>> date_to_micros(None)
        None
    """
    if not date_str:
        return None
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def condition_to_claim(row: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Map a conditions.csv row to a TemporalBridge.ingest_claim() kwargs dict.

    Conditions have an explicit validity window (START date = diagnosis onset,
    STOP date = resolution). A missing STOP means the condition is still active.

    This is the core temporal event for Experiment 1: the START/STOP window on
    a condition is exactly what the SpacetimeDB temporal decay layer models.

    Args:
        row: A dict representing one conditions.csv row. Required keys:
            PATIENT, ENCOUNTER, CODE, DESCRIPTION, START.
            Optional key: STOP (empty string if condition is ongoing).
        project_id: The project namespace for SpacetimeDB isolation.

    Returns:
        Dict of kwargs ready for TemporalBridge.ingest_claim(**result).
    """
    source_id = f"{row['PATIENT']}:{row['ENCOUNTER']}:{row['CODE']}:{row['START']}"
    return {
        "project_id": project_id,
        "subject_kind": "patient",
        "subject_name": row["PATIENT"],
        "predicate": "DIAGNOSED_WITH",
        "object_kind": "diagnosis",
        "object_name": row["DESCRIPTION"],
        "valid_from_us": date_to_micros(row["START"]),
        "valid_to_us": date_to_micros(row.get("STOP") or None),
        "confidence": 1.0,
        "evidence": {
            "sourceKind": "synthea_condition",
            "sourceId": source_id,
            "capturedAtUs": date_to_micros(row["START"]),
            "rawExcerpt": f"{row['DESCRIPTION']} (code: {row['CODE']})",
        },
    }


def medication_to_claim(row: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Map a medications.csv row to a TemporalBridge.ingest_claim() kwargs dict.

    Medications carry a START (first dispense) and optional STOP (last dispense
    or discontinuation). Ongoing prescriptions have an empty STOP field.

    Args:
        row: A dict representing one medications.csv row. Required keys:
            PATIENT, ENCOUNTER, CODE, DESCRIPTION, START.
            Optional key: STOP.
        project_id: The project namespace for SpacetimeDB isolation.

    Returns:
        Dict of kwargs ready for TemporalBridge.ingest_claim(**result).
    """
    source_id = f"{row['PATIENT']}:{row['ENCOUNTER']}:{row['CODE']}:{row['START']}"
    return {
        "project_id": project_id,
        "subject_kind": "patient",
        "subject_name": row["PATIENT"],
        "predicate": "PRESCRIBED",
        "object_kind": "medication",
        "object_name": row["DESCRIPTION"],
        "valid_from_us": date_to_micros(row["START"]),
        "valid_to_us": date_to_micros(row.get("STOP") or None),
        "confidence": 1.0,
        "evidence": {
            "sourceKind": "synthea_medication",
            "sourceId": source_id,
            "capturedAtUs": date_to_micros(row["START"]),
            "rawExcerpt": f"{row['DESCRIPTION']} (code: {row['CODE']})",
        },
    }


def observation_to_claim(row: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Map an observations.csv row to a TemporalBridge.ingest_claim() kwargs dict.

    Observations are point-in-time events (a single DATE, no stop). They capture
    lab results and vital signs. The object_name encodes both the test name and
    value so the temporal graph holds the measurement content.

    Args:
        row: A dict representing one observations.csv row. Required keys:
            PATIENT, ENCOUNTER, CODE, DESCRIPTION, DATE, VALUE, UNITS.
        project_id: The project namespace for SpacetimeDB isolation.

    Returns:
        Dict of kwargs ready for TemporalBridge.ingest_claim(**result).
    """
    # Encode value into the object name so the claim is self-contained
    value_str = f"{row.get('VALUE', '')} {row.get('UNITS', '')}".strip()
    object_name = f"{row['DESCRIPTION']}: {value_str}" if value_str else row["DESCRIPTION"]
    source_id = f"{row['PATIENT']}:{row['ENCOUNTER']}:{row['CODE']}:{row['DATE']}"

    return {
        "project_id": project_id,
        "subject_kind": "patient",
        "subject_name": row["PATIENT"],
        "predicate": "OBSERVED",
        "object_kind": "observation",
        "object_name": object_name,
        "valid_from_us": date_to_micros(row["DATE"]),
        "valid_to_us": None,  # Point-in-time — no validity end
        "confidence": 1.0,
        "evidence": {
            "sourceKind": "synthea_observation",
            "sourceId": source_id,
            "capturedAtUs": date_to_micros(row["DATE"]),
            "rawExcerpt": f"{row['DESCRIPTION']} = {value_str}",
        },
    }


def procedure_to_claim(row: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Map a procedures.csv row to a TemporalBridge.ingest_claim() kwargs dict.

    Procedures are point-in-time events (DATE only, no duration in Synthea CSV).

    Args:
        row: A dict representing one procedures.csv row. Required keys:
            PATIENT, ENCOUNTER, CODE, DESCRIPTION, DATE.
        project_id: The project namespace for SpacetimeDB isolation.

    Returns:
        Dict of kwargs ready for TemporalBridge.ingest_claim(**result).
    """
    source_id = f"{row['PATIENT']}:{row['ENCOUNTER']}:{row['CODE']}:{row['DATE']}"
    return {
        "project_id": project_id,
        "subject_kind": "patient",
        "subject_name": row["PATIENT"],
        "predicate": "UNDERWENT",
        "object_kind": "procedure",
        "object_name": row["DESCRIPTION"],
        "valid_from_us": date_to_micros(row["DATE"]),
        "valid_to_us": None,
        "confidence": 1.0,
        "evidence": {
            "sourceKind": "synthea_procedure",
            "sourceId": source_id,
            "capturedAtUs": date_to_micros(row["DATE"]),
            "rawExcerpt": f"{row['DESCRIPTION']} (code: {row['CODE']})",
        },
    }
