"""Embed text builders for Synthea clinical record types.

Synthea's CSV export contains no free-text clinical notes — all fields are
structured (ICD codes, drug names, numeric lab values). To produce meaningful
dense vector embeddings we construct a short prose summary for each record type
that captures the semantically important fields.

The generated strings are designed to:
  1. Be short enough to fit in a single embedding call (under ~300 tokens).
  2. Capture the most semantically discriminating fields (condition name,
     medication name, lab description + value) rather than raw codes.
  3. Be enriched by entity-context prepending (build_embed_text from
     entity_extraction.py) before the actual embedding call.

All functions return plain strings. The caller (HealthcareIngestionPipeline)
passes the result through build_embed_text(text, entities) before embedding.

Role in the project:
  These builders are called inside HealthcareIngestionPipeline._ingest_*
  methods. They are the Synthea-specific counterpart to what clinical note
  text would provide if we were using real MIMIC-III data.
"""

from __future__ import annotations

from typing import Any


def build_encounter_embed_text(row: dict[str, Any]) -> str:
    """Build embed text for an encounters.csv row.

    Captures: encounter date, reason, description, and provider UUID prefix.
    Provider UUID is shortened to 8 chars to give a readable identifier without
    revealing the full synthetic key.

    Args:
        row: encounters.csv row dict. Used keys: START, DESCRIPTION,
            REASONDESCRIPTION, PROVIDER.

    Returns:
        Prose string suitable for embedding.

    Example:
        "Encounter on 2015-03-12. Reason: Hypertension. "
        "Description: Encounter for check up. Provider: a3f2b1c0."
    """
    provider_short = (row.get("PROVIDER") or "unknown")[:8]
    reason = row.get("REASONDESCRIPTION") or row.get("REASONCODE") or "not specified"
    description = row.get("DESCRIPTION") or "encounter"
    date = (row.get("START") or "")[:10]  # Keep YYYY-MM-DD only

    return (
        f"Encounter on {date}. "
        f"Reason: {reason}. "
        f"Description: {description}. "
        f"Provider: {provider_short}."
    )


def build_condition_embed_text(row: dict[str, Any]) -> str:
    """Build embed text for a conditions.csv row.

    Captures: condition name, SNOMED code, onset date, and resolution date.
    "ongoing" is used when STOP is empty so the embedding reflects current
    vs past conditions.

    Args:
        row: conditions.csv row dict. Used keys: DESCRIPTION, CODE, START, STOP.

    Returns:
        Prose string suitable for embedding.

    Example:
        "Condition: Hypertension (code: 44054006). "
        "Active from 2010-05-01 to ongoing."
    """
    stop = (row.get("STOP") or "").strip()
    stop_str = stop[:10] if stop else "ongoing"
    start = (row.get("START") or "")[:10]

    return (
        f"Condition: {row.get('DESCRIPTION', 'unknown')} "
        f"(code: {row.get('CODE', '')})."
        f" Active from {start} to {stop_str}."
    )


def build_observation_embed_text(row: dict[str, Any]) -> str:
    """Build embed text for an observations.csv row.

    Captures: observation date, test/measurement description, value, and units.
    Covers both numeric lab results (VALUE=7.2, UNITS=mmol/L) and categorical
    findings (VALUE=Yes, UNITS empty).

    Args:
        row: observations.csv row dict. Used keys: DATE, DESCRIPTION,
            VALUE, UNITS, TYPE.

    Returns:
        Prose string suitable for embedding.

    Example:
        "Observation on 2015-03-12: Hemoglobin A1c/Hemoglobin.total = 6.3 %."
    """
    value = str(row.get("VALUE") or "").strip()
    units = (row.get("UNITS") or "").strip()
    value_str = f"{value} {units}".strip() if value else "not recorded"
    date = (row.get("DATE") or "")[:10]

    return (
        f"Observation on {date}: "
        f"{row.get('DESCRIPTION', 'unknown')} = {value_str}."
    )


def build_medication_embed_text(row: dict[str, Any]) -> str:
    """Build embed text for a medications.csv row.

    Captures: drug name, RxNorm code, prescription start/stop, and dispense count.
    "ongoing" is used when STOP is empty so the embedding can distinguish
    current from discontinued medications.

    Args:
        row: medications.csv row dict. Used keys: DESCRIPTION, CODE,
            START, STOP, DISPENSES.

    Returns:
        Prose string suitable for embedding.

    Example:
        "Medication: Lisinopril 10 MG Oral Tablet (code: 314076). "
        "Prescribed 2010-05-01, stopped ongoing. 12 dispenses."
    """
    stop = (row.get("STOP") or "").strip()
    stop_str = stop[:10] if stop else "ongoing"
    start = (row.get("START") or "")[:10]
    dispenses = row.get("DISPENSES") or "unknown"

    return (
        f"Medication: {row.get('DESCRIPTION', 'unknown')} "
        f"(code: {row.get('CODE', '')})."
        f" Prescribed {start}, stopped {stop_str}."
        f" {dispenses} dispenses."
    )


def build_procedure_embed_text(row: dict[str, Any]) -> str:
    """Build embed text for a procedures.csv row.

    Captures: procedure name, SNOMED code, and date performed.

    Args:
        row: procedures.csv row dict. Used keys: DESCRIPTION, CODE, DATE.

    Returns:
        Prose string suitable for embedding.

    Example:
        "Procedure: Measurement of body weight (code: 27113001) on 2015-03-12."
    """
    date = (row.get("DATE") or "")[:10]

    return (
        f"Procedure: {row.get('DESCRIPTION', 'unknown')} "
        f"(code: {row.get('CODE', '')}) on {date}."
    )


def build_patient_embed_text(row: dict[str, Any]) -> str:
    """Build embed text for a patients.csv row.

    Captures: demographic summary. No PHI — first/last name are omitted.
    Only age-range, gender, race, and ethnicity are used.

    Args:
        row: patients.csv row dict. Used keys: BIRTHDATE, DEATHDATE,
            GENDER, RACE, ETHNICITY.

    Returns:
        Prose string suitable for embedding.

    Example:
        "Patient: male, white, not hispanic or latino. Born 1955."
    """
    birth_year = (row.get("BIRTHDATE") or "")[:4]
    death = row.get("DEATHDATE") or ""
    death_str = f" Deceased {death[:4]}." if death.strip() else ""
    gender = (row.get("GENDER") or "unknown").lower()
    race = (row.get("RACE") or "unknown").lower()
    ethnicity = (row.get("ETHNICITY") or "unknown").lower()

    return (
        f"Patient: {gender}, {race}, {ethnicity}."
        f" Born {birth_year}.{death_str}"
    )
