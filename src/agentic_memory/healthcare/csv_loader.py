"""Synthea CSV loader — reads and normalises all 7 core Synthea tables.

Synthea's CSV export (tested against synthea_2017_02_27) produces one file per
clinical domain, each with a header row and UTF-8 content. This module wraps
csv.DictReader with light normalisation (strip whitespace from all values,
convert empty strings to None) and exposes one method per table.

Load order matters — conditions, medications, observations, and procedures all
carry a PATIENT foreign key that references patients.csv.  Callers should load
patients first and pass the resulting lookup dict to the pipeline if needed.

No third-party dependencies (no pandas, no polars). Pure stdlib CSV + dicts.

Role in the project:
  Used exclusively by scripts/ingest_synthea.py and experiments/healthcare/
  qa_generator.py. The pipeline itself (healthcare/pipeline.py) receives
  pre-parsed row dicts, so it is independent of this loader.
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any, Generator, Iterator

logger = logging.getLogger(__name__)

# Canonical file names for the Synthea 2017 CSV export.
# FHIR bundles (synthea_1m_fhir_3_0_May_24) use a different layout and are
# NOT handled here — this module targets the structured CSV format only.
_SYNTHEA_CSV_FILES = {
    "patients": "patients.csv",
    "encounters": "encounters.csv",
    "conditions": "conditions.csv",
    "medications": "medications.csv",
    "observations": "observations.csv",
    "procedures": "procedures.csv",
    "allergies": "allergies.csv",
}


class SyntheaCSVLoader:
    """Reads Synthea CSV tables from a directory and yields normalised row dicts.

    Each table method returns a generator of dicts (one per CSV row). Values are
    stripped of surrounding whitespace; empty-string values are converted to None
    so callers can use ``row.get("STOP") or None`` safely.

    Args:
        data_dir: Path to the directory containing the Synthea CSV files.
            May be a string or Path object.
        max_patients: If set, only rows for the first N unique patient IDs
            encountered (across all tables) are yielded. Useful for dev runs.
            None means no limit.

    Example:
        loader = SyntheaCSVLoader("/data/synthea/")
        for row in loader.conditions():
            print(row["DESCRIPTION"], row["START"])
    """

    def __init__(
        self,
        data_dir: str | Path,
        max_patients: int | None = None,
    ) -> None:
        """Initialise the loader.

        Args:
            data_dir: Directory containing Synthea CSV files.
            max_patients: Cap on unique patients to process. None = unlimited.
        """
        self._dir = Path(data_dir)
        self._max_patients = max_patients
        # Populated lazily when patients() is called first
        self._allowed_patient_ids: set[str] | None = None

    # ------------------------------------------------------------------
    # Public table methods
    # ------------------------------------------------------------------

    def patients(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from patients.csv.

        Side effect: if max_patients is set, this call populates the internal
        allowed patient ID set. Always call patients() before other tables when
        using max_patients so the ID filter is ready.

        Yields:
            Dict per patient row. Key columns: Id, BIRTHDATE, DEATHDATE,
            GENDER, RACE, ETHNICITY.
        """
        seen: set[str] = set()
        for row in self._iter_csv("patients"):
            patient_id = row.get("Id") or row.get("id") or ""
            if self._max_patients is not None:
                if len(seen) >= self._max_patients and patient_id not in seen:
                    continue
            seen.add(patient_id)
            yield row

        # After iterating all patients, fix the allowed set for filtering
        if self._max_patients is not None:
            self._allowed_patient_ids = seen
            logger.info("Patient filter active: %d patients loaded.", len(seen))

    def encounters(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from encounters.csv.

        Yields:
            Dict per encounter. Key columns: Id, START, STOP, PATIENT,
            PROVIDER, DESCRIPTION, REASONDESCRIPTION.
        """
        yield from self._iter_filtered("encounters", patient_col="PATIENT")

    def conditions(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from conditions.csv.

        Yields:
            Dict per condition. Key columns: START, STOP, PATIENT,
            ENCOUNTER, CODE, DESCRIPTION.
        """
        yield from self._iter_filtered("conditions", patient_col="PATIENT")

    def medications(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from medications.csv.

        Yields:
            Dict per medication. Key columns: START, STOP, PATIENT,
            ENCOUNTER, CODE, DESCRIPTION, DISPENSES, TOTALCOST.
        """
        yield from self._iter_filtered("medications", patient_col="PATIENT")

    def observations(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from observations.csv.

        Yields:
            Dict per observation. Key columns: DATE, PATIENT, ENCOUNTER,
            CODE, DESCRIPTION, VALUE, UNITS, TYPE.
        """
        yield from self._iter_filtered("observations", patient_col="PATIENT")

    def procedures(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from procedures.csv.

        Yields:
            Dict per procedure. Key columns: DATE, PATIENT, ENCOUNTER,
            CODE, DESCRIPTION, COST.
        """
        yield from self._iter_filtered("procedures", patient_col="PATIENT")

    def allergies(self) -> Generator[dict[str, Any], None, None]:
        """Yield normalised rows from allergies.csv (optional table).

        Yields:
            Dict per allergy, or nothing if the file is absent.
        """
        if not self._csv_path("allergies").exists():
            logger.debug("allergies.csv not found — skipping.")
            return
        yield from self._iter_filtered("allergies", patient_col="PATIENT")

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def load_patient_lookup(self) -> dict[str, dict[str, Any]]:
        """Load all patients into a {patient_id: row} dict.

        Useful for building a quick lookup when constructing embed text that
        needs demographic context. Also initialises the patient filter set when
        max_patients is set.

        Returns:
            Dict mapping patient UUID → normalised row dict.
        """
        lookup: dict[str, dict[str, Any]] = {}
        for row in self.patients():
            pid = row.get("Id") or row.get("id") or ""
            if pid:
                lookup[pid] = row
        logger.info("Patient lookup built: %d patients.", len(lookup))
        return lookup

    def available_tables(self) -> list[str]:
        """Return the names of CSV tables that exist in data_dir.

        Returns:
            List of table names (e.g. ["patients", "encounters", ...]).
        """
        return [
            name
            for name, filename in _SYNTHEA_CSV_FILES.items()
            if (self._dir / filename).exists()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _csv_path(self, table: str) -> Path:
        """Resolve the file path for a given table name."""
        return self._dir / _SYNTHEA_CSV_FILES[table]

    def _iter_csv(self, table: str) -> Iterator[dict[str, Any]]:
        """Yield normalised dicts from a CSV file.

        Each row value is stripped; empty strings become None.

        Args:
            table: Table name key (must be in _SYNTHEA_CSV_FILES).

        Yields:
            Normalised row dicts.

        Raises:
            FileNotFoundError: If the CSV file does not exist.
        """
        path = self._csv_path(table)
        if not path.exists():
            raise FileNotFoundError(
                f"Synthea CSV not found: {path}. "
                f"Is --data-dir pointing to the extracted directory?"
            )

        with open(path, newline="", encoding="utf-8-sig") as fh:
            # utf-8-sig strips the BOM that some Synthea exports include
            reader = csv.DictReader(fh)
            for raw_row in reader:
                # Normalise: strip whitespace, empty strings → None
                yield {k: (v.strip() or None) for k, v in raw_row.items()}

    def _iter_filtered(
        self,
        table: str,
        patient_col: str = "PATIENT",
    ) -> Generator[dict[str, Any], None, None]:
        """Yield rows from table, optionally filtered to allowed patient IDs.

        If max_patients was set and patients() has been called first, only rows
        whose patient_col value is in _allowed_patient_ids are yielded.

        Args:
            table: Table name key.
            patient_col: Column name containing the patient UUID.

        Yields:
            Filtered, normalised row dicts.
        """
        allowed = self._allowed_patient_ids
        count = 0
        for row in self._iter_csv(table):
            pid = row.get(patient_col)
            if allowed is not None and pid not in allowed:
                continue
            yield row
            count += 1
        logger.debug("Table %s: %d rows yielded.", table, count)
