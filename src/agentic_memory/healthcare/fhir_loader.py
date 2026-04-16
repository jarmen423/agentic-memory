"""Synthea FHIR bundle loader — streams nested tarballs without full extraction.

Both Synthea datasets downloaded from https://synthea.mitre.org/downloads are
FHIR bundles, NOT CSV:
  - synthea_2017_02_27.tar.gz  → synthea_1m_fhir_1_8/  (FHIR DSTU2 / v1.8)
  - synthea_1m_fhir_3_0_May_24.tar.gz → (FHIR R3 / STU3)

Both use nested tarballs: outer.tar.gz → output_N.tar.gz → fhir/*.json
Each patient JSON is a FHIR Bundle with all their clinical resources in one file.

This loader:
  - Opens both the outer and inner tarballs as streaming handles (no disk extraction)
  - Parses each patient Bundle JSON
  - Yields row dicts in the same format as SyntheaCSVLoader would produce from CSV,
    so the HealthcareIngestionPipeline requires zero changes

FHIR resource → pipeline row mapping:
  Patient           → {record_type: "patient",     Id, BIRTHDATE, GENDER, RACE, ETHNICITY, ...}
  Encounter         → {record_type: "encounter",   Id, START, STOP, PATIENT, PROVIDER, ...}
  Condition         → {record_type: "condition",   START, STOP, PATIENT, ENCOUNTER, CODE, DESCRIPTION}
  MedicationRequest → {record_type: "medication",  START, STOP, PATIENT, ENCOUNTER, CODE, DESCRIPTION, DISPENSES}
  Observation       → {record_type: "observation", DATE, PATIENT, ENCOUNTER, CODE, DESCRIPTION, VALUE, UNITS, TYPE}
  Procedure         → {record_type: "procedure",   DATE, PATIENT, ENCOUNTER, CODE, DESCRIPTION}

Role in the project:
  Drop-in replacement for SyntheaCSVLoader. scripts/ingest_synthea.py uses
  whichever loader is appropriate for the data format present in --data-dir.
  When a .tar.gz file is passed to --data-dir (or --tarball), this loader is used.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile
from pathlib import Path
from typing import Any, Generator, Iterator

logger = logging.getLogger(__name__)

# FHIR resource types we care about (all others in the Bundle are skipped)
_WANTED_RESOURCE_TYPES = frozenset(
    {"Patient", "Encounter", "Condition", "MedicationRequest", "Observation", "Procedure"}
)

# Extension URLs used by Synthea for US Core race/ethnicity
_RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"

# Alternative extension URL format used in older Synthea DSTU2 bundles
_RACE_URL_ALT = "http://hl7.org/fhir/StructureDefinition/us-core-race"
_ETHNICITY_URL_ALT = "http://hl7.org/fhir/StructureDefinition/us-core-ethnicity"


class SyntheaFHIRLoader:
    """Streams Synthea FHIR bundles from nested tarballs without full extraction.

    Supports both outer-tarball mode (points at the .tar.gz file directly) and
    directory mode (points at a directory of already-extracted JSON files).

    Args:
        source: Either a path to the outer .tar.gz file, or a directory
            containing FHIR JSON files (or sub-tarballs).
        max_patients: Cap on unique patients to process. None = unlimited.

    Example:
        loader = SyntheaFHIRLoader("synthea_1m_fhir_3_0_May_24.tar.gz")
        for row in loader.iter_records():
            print(row["record_type"], row.get("DESCRIPTION"))
    """

    def __init__(
        self,
        source: str | Path,
        max_patients: int | None = None,
    ) -> None:
        """Initialise the loader.

        Args:
            source: Path to the outer .tar.gz file, or a directory.
            max_patients: Maximum unique patients to process. None = unlimited.
        """
        self._source = Path(source)
        self._max_patients = max_patients
        self._processed_patients: set[str] = set()

    # ------------------------------------------------------------------
    # Public interface (mirrors SyntheaCSVLoader API)
    # ------------------------------------------------------------------

    def iter_records(self) -> Generator[dict[str, Any], None, None]:
        """Yield all clinical record dicts from all patient bundles.

        Yields rows in encounter → condition → medication → observation →
        procedure order within each patient bundle. Each row has record_type
        set so HealthcareIngestionPipeline.ingest() can dispatch correctly.

        Yields:
            Row dicts with record_type + FHIR-mapped fields.
        """
        for bundle in self._iter_bundles():
            yield from self._parse_bundle(bundle)
            if self._max_patients and len(self._processed_patients) >= self._max_patients:
                logger.info("max_patients=%d reached, stopping.", self._max_patients)
                return

    def load_patient_lookup(self) -> dict[str, dict[str, Any]]:
        """Build a {patient_id: row} lookup dict from all Patient resources.

        Processes all bundles and returns just the Patient rows. Also
        populates the patient filter set when max_patients is set.

        Returns:
            Dict mapping patient UUID → normalised row dict.
        """
        lookup: dict[str, dict[str, Any]] = {}
        for bundle in self._iter_bundles():
            patient_row = self._extract_patient(bundle)
            if patient_row:
                pid = patient_row.get("Id") or ""
                if pid:
                    lookup[pid] = patient_row
                    self._processed_patients.add(pid)
            if self._max_patients and len(lookup) >= self._max_patients:
                break
        logger.info("Patient lookup built: %d patients.", len(lookup))
        return lookup

    # ------------------------------------------------------------------
    # Bundle iteration — handles nested tarballs transparently
    # ------------------------------------------------------------------

    def _iter_bundles(self) -> Iterator[dict[str, Any]]:
        """Yield parsed FHIR Bundle dicts from the source.

        Handles three cases:
          1. source is a .tar.gz with nested sub-.tar.gz files inside
          2. source is a directory of .json files
          3. source is a directory of .tar.gz files (already extracted outer)
        """
        src = self._source
        if src.is_dir():
            yield from self._iter_bundles_from_dir(src)
        elif src.suffix in (".gz", ".tgz") or src.name.endswith(".tar.gz"):
            yield from self._iter_bundles_from_outer_tarball(src)
        else:
            raise ValueError(
                f"Unsupported source: {src}. "
                "Pass a .tar.gz file or a directory of .json files."
            )

    def _iter_bundles_from_outer_tarball(
        self, tarball_path: Path
    ) -> Iterator[dict[str, Any]]:
        """Stream bundles from the outer .tar.gz (Synthea download format).

        The outer tarball contains sub-.tar.gz files (output_N_*.tar.gz).
        Each sub-tarball contains a fhir/ directory with one JSON per patient.
        This method handles both levels of nesting.

        Streaming semantics:
            We iterate ``for member in outer:`` rather than calling
            ``outer.getmembers()``. ``getmembers()`` forces a full scan of the
            outer tar index before the first record can be yielded. On a
            multi-GB Synthea tarball served from a slow-random-read filesystem
            (Colab + Google Drive is the motivating case), that single call
            adds minutes of latency before ingest can start. Direct iteration
            hands us the first sub-tarball as soon as its header has streamed
            through, and ``extractfile()`` on the just-yielded member is the
            tarfile module's supported streaming access pattern.

            The tradeoff is loss of lexicographic sub-tarball ordering. Synthea
            packs sub-tarballs in a deterministic order already (``output_1``,
            ``output_2``, …), so this is effectively unchanged in practice.
            Downstream ingest does not assume a particular sub-tarball order.

        Args:
            tarball_path: Path to the outer .tar.gz file.

        Yields:
            Parsed FHIR Bundle dicts.
        """
        logger.info("Opening outer tarball (streaming): %s", tarball_path)
        sub_tarball_count = 0
        with tarfile.open(tarball_path, "r|gz") as outer:
            # "r|gz" is the explicit streaming mode: forward-only reads, no
            # seeks, no full index scan. Must use ``for m in outer`` rather
            # than ``getmembers()`` / ``getnames()`` with this mode.
            for sub_member in outer:
                if not sub_member.name.endswith(".tar.gz"):
                    continue
                sub_tarball_count += 1
                logger.info("Processing sub-tarball #%d: %s", sub_tarball_count, sub_member.name)
                sub_fh = outer.extractfile(sub_member)
                if sub_fh is None:
                    continue
                yield from self._iter_bundles_from_inner_tarball(
                    fileobj=sub_fh, label=sub_member.name
                )
                if self._max_patients and len(self._processed_patients) >= self._max_patients:
                    logger.info(
                        "max_patients=%d reached after %d sub-tarballs; stopping outer stream.",
                        self._max_patients,
                        sub_tarball_count,
                    )
                    return
        logger.info("Outer tarball exhausted after %d sub-tarballs.", sub_tarball_count)

    def _iter_bundles_from_inner_tarball(
        self, fileobj: io.BufferedIOBase, label: str
    ) -> Iterator[dict[str, Any]]:
        """Stream patient JSON bundles from one sub-tarball.

        Sub-tarball structure (confirmed from real Synthea downloads):
            output_N/
              fhir/    ← patient FHIR bundles (one JSON per patient)
              csv/     ← CSV exports (patients.csv, encounters.csv, etc.)
              CCDA/    ← CDA documents
              html/    ← human-readable summaries
              text/    ← plain text summaries

        We only read from the fhir/ subdirectory to avoid accidentally
        parsing HTML or CCDA files that also end in .json.

        Args:
            fileobj: File-like object for the inner .tar.gz.
            label: Human-readable label for log messages.

        Yields:
            Parsed FHIR Bundle dicts.
        """
        count = 0
        # "r|gz" matches the outer-tarball streaming semantics: forward-only,
        # no index scan. See ``_iter_bundles_from_outer_tarball`` for why this
        # matters on Colab/Drive. ``extractfile()`` is valid on the member
        # just yielded by the iterator.
        with tarfile.open(fileobj=fileobj, mode="r|gz") as inner:
            for member in inner:
                # Only process files inside the fhir/ subdirectory
                # Path pattern: output_N/fhir/PatientName.json
                path_parts = Path(member.name).parts
                if len(path_parts) < 3:
                    continue
                # parts[1] must be "fhir" (not csv/, CCDA/, html/, text/)
                if path_parts[1] != "fhir":
                    continue
                if not member.name.endswith(".json"):
                    continue

                json_fh = inner.extractfile(member)
                if json_fh is None:
                    continue

                try:
                    bundle = json.loads(json_fh.read().decode("utf-8"))
                    if bundle.get("resourceType") == "Bundle":
                        yield bundle
                        count += 1
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning("Failed to parse %s: %s", member.name, exc)

                # Honour max_patients early to avoid reading the whole sub-tar
                # when we already have enough bundles. _parse_bundle() is what
                # actually increments ``_processed_patients``, so we check that
                # set here rather than ``count``.
                if self._max_patients and len(self._processed_patients) >= self._max_patients:
                    logger.info(
                        "  %s: max_patients=%d reached, stopping inner stream (%d bundles read).",
                        label, self._max_patients, count,
                    )
                    return

        logger.info("  %s: %d patient bundles read.", label, count)

    def iter_csv_from_tarball(
        self, outer_tarball: Path, table: str
    ) -> Iterator[dict[str, Any]]:
        """Stream rows from a specific CSV table nested inside the tarballs.

        Each sub-tarball contains output_N/csv/{table}.csv. This method
        streams all rows from all sub-tarballs for the given table without
        full extraction — useful for the QA generator which needs bulk CSV
        joins rather than per-patient FHIR parsing.

        Args:
            outer_tarball: Path to the outer .tar.gz file.
            table: CSV table name without extension (e.g. "conditions",
                "medications", "encounters").

        Yields:
            Row dicts with stripped values (empty string → None).
        """
        import csv as csv_module

        csv_filename = f"{table}.csv"
        logger.info("Streaming %s from nested tarballs...", csv_filename)
        total = 0

        # Streaming mode ("r|gz") for the same Drive/Colab latency reasons as
        # ``_iter_bundles_from_outer_tarball``.
        with tarfile.open(outer_tarball, "r|gz") as outer:
            for sub_member in outer:
                if not sub_member.name.endswith(".tar.gz"):
                    continue
                sub_fh = outer.extractfile(sub_member)
                if sub_fh is None:
                    continue
                with tarfile.open(fileobj=sub_fh, mode="r|gz") as inner:
                    for member in inner:
                        # Match output_N/csv/{table}.csv
                        parts = Path(member.name).parts
                        if len(parts) == 3 and parts[1] == "csv" and parts[2] == csv_filename:
                            csv_fh = inner.extractfile(member)
                            if csv_fh is None:
                                continue
                            text = io.TextIOWrapper(csv_fh, encoding="utf-8-sig")
                            reader = csv_module.DictReader(text)
                            for row in reader:
                                yield {k: (v.strip() or None) for k, v in row.items()}
                                total += 1
                            # Python's tarfile streaming mode skips any unread
                            # bytes of the current member when advancing to the
                            # next one, so breaking out of the inner loop is
                            # safe even though we have not read the remaining
                            # inner members. This preserves the original
                            # "one csv file per sub-tar" efficiency.
                            break

        logger.info("  %s: %d rows total across all sub-tarballs.", csv_filename, total)

    def _iter_bundles_from_dir(self, directory: Path) -> Iterator[dict[str, Any]]:
        """Stream patient JSON bundles from a directory of .json files.

        Also handles directories that contain .tar.gz sub-files (half-extracted).

        Args:
            directory: Directory to scan.

        Yields:
            Parsed FHIR Bundle dicts.
        """
        json_files = sorted(directory.rglob("*.json"))
        sub_tarballs = sorted(directory.glob("*.tar.gz"))

        if json_files:
            for path in json_files:
                if path.name.startswith("hospital") or path.name.startswith("practitioner"):
                    continue
                try:
                    bundle = json.loads(path.read_text(encoding="utf-8"))
                    if bundle.get("resourceType") == "Bundle":
                        yield bundle
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning("Failed to parse %s: %s", path, exc)

        elif sub_tarballs:
            for sub_path in sub_tarballs:
                with open(sub_path, "rb") as fh:
                    yield from self._iter_bundles_from_inner_tarball(fh, sub_path.name)

    # ------------------------------------------------------------------
    # Bundle parsing — FHIR → row dicts
    # ------------------------------------------------------------------

    def _parse_bundle(self, bundle: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse a FHIR Bundle and return all clinical row dicts.

        Extracts the patient ID first, then processes all other resources
        in encounter → condition → medication → observation → procedure order.

        Args:
            bundle: Parsed FHIR Bundle dict.

        Returns:
            List of row dicts ready for HealthcareIngestionPipeline.ingest().
        """
        entries = bundle.get("entry", [])
        resources_by_type: dict[str, list[dict[str, Any]]] = {}

        for entry in entries:
            resource = entry.get("resource", {})
            rtype = resource.get("resourceType", "")
            if rtype in _WANTED_RESOURCE_TYPES:
                resources_by_type.setdefault(rtype, []).append(resource)

        # Get patient ID first (needed as FK for all other rows)
        patients = resources_by_type.get("Patient", [])
        if not patients:
            return []
        patient_resource = patients[0]
        patient_id = patient_resource.get("id", "")

        if not patient_id:
            return []

        # Apply max_patients filter
        if self._max_patients is not None:
            if (
                patient_id not in self._processed_patients
                and len(self._processed_patients) >= self._max_patients
            ):
                return []
        self._processed_patients.add(patient_id)

        rows: list[dict[str, Any]] = []

        # Build an encounter-id → encounter row dict for FK resolution
        encounter_map: dict[str, dict[str, Any]] = {}

        # --- Encounters ---
        for enc in resources_by_type.get("Encounter", []):
            row = self._parse_encounter(enc, patient_id)
            if row:
                rows.append(row)
                enc_id = enc.get("id", "")
                if enc_id:
                    encounter_map[enc_id] = row

        # --- Conditions ---
        for cond in resources_by_type.get("Condition", []):
            row = self._parse_condition(cond, patient_id, encounter_map)
            if row:
                rows.append(row)

        # --- Medications (MedicationRequest in FHIR R3) ---
        for med in resources_by_type.get("MedicationRequest", []):
            row = self._parse_medication(med, patient_id, encounter_map)
            if row:
                rows.append(row)

        # --- Observations ---
        for obs in resources_by_type.get("Observation", []):
            row = self._parse_observation(obs, patient_id, encounter_map)
            if row:
                rows.append(row)

        # --- Procedures ---
        for proc in resources_by_type.get("Procedure", []):
            row = self._parse_procedure(proc, patient_id, encounter_map)
            if row:
                rows.append(row)

        return rows

    # ------------------------------------------------------------------
    # Per-resource parsers — return row dicts matching CSV column names
    # ------------------------------------------------------------------

    def _parse_encounter(
        self, resource: dict[str, Any], patient_id: str
    ) -> dict[str, Any] | None:
        """Parse a FHIR Encounter resource to a CSV-compatible row dict.

        Args:
            resource: FHIR Encounter resource dict.
            patient_id: Patient UUID (already resolved).

        Returns:
            Row dict or None if resource is invalid.
        """
        enc_id = resource.get("id", "")
        if not enc_id:
            return None

        period = resource.get("period", {})
        start = _fhir_date(period.get("start"))
        stop = _fhir_date(period.get("end"))

        # Provider: first participant's individual reference
        provider_id = ""
        participants = resource.get("participant", [])
        if participants:
            ref = participants[0].get("individual", {}).get("reference", "")
            provider_id = _extract_uuid(ref)

        # Reason: first reasonCode display text
        reason_code = ""
        reason_desc = ""
        reason_codes = resource.get("reasonCode", [])
        if reason_codes:
            codings = reason_codes[0].get("coding", [])
            if codings:
                reason_code = codings[0].get("code", "")
                reason_desc = codings[0].get("display", "")

        # Description: encounter type display
        description = ""
        types = resource.get("type", [])
        if types:
            codings = types[0].get("coding", [])
            if codings:
                description = codings[0].get("display", "")

        return {
            "record_type": "encounter",
            "Id": enc_id,
            "START": start,
            "STOP": stop,
            "PATIENT": patient_id,
            "PROVIDER": provider_id or None,
            "DESCRIPTION": description or None,
            "REASONCODE": reason_code or None,
            "REASONDESCRIPTION": reason_desc or None,
            "CLASS": _fhir_class(resource),
        }

    def _parse_condition(
        self,
        resource: dict[str, Any],
        patient_id: str,
        encounter_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Parse a FHIR Condition resource.

        Args:
            resource: FHIR Condition resource dict.
            patient_id: Patient UUID.
            encounter_map: Dict of encounter_id → encounter row.

        Returns:
            Row dict or None.
        """
        code_info = _extract_coding(resource.get("code", {}))
        if not code_info:
            return None

        onset = _fhir_date(resource.get("onsetDateTime") or resource.get("onsetPeriod", {}).get("start"))
        abatement = _fhir_date(
            resource.get("abatementDateTime") or resource.get("abatementPeriod", {}).get("end")
        )

        # Encounter reference (context in R3, encounter in R4)
        enc_ref = (
            resource.get("context", {}).get("reference", "")
            or resource.get("encounter", {}).get("reference", "")
        )
        encounter_id = _extract_uuid(enc_ref)

        return {
            "record_type": "condition",
            "START": onset,
            "STOP": abatement,
            "PATIENT": patient_id,
            "ENCOUNTER": encounter_id or None,
            "CODE": code_info["code"],
            "DESCRIPTION": code_info["display"],
        }

    def _parse_medication(
        self,
        resource: dict[str, Any],
        patient_id: str,
        encounter_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Parse a FHIR MedicationRequest resource.

        FHIR R3 MedicationRequest has no explicit stop date. We set STOP to
        None for active requests and use dispenseRequest.validityPeriod.end
        when present (older bundles may include it).

        Args:
            resource: FHIR MedicationRequest resource dict.
            patient_id: Patient UUID.
            encounter_map: Encounter FK lookup.

        Returns:
            Row dict or None.
        """
        code_info = _extract_coding(resource.get("medicationCodeableConcept", {}))
        if not code_info:
            return None

        start = _fhir_date(resource.get("authoredOn"))
        # Try to find a stop date from dispenseRequest validity period
        dispense = resource.get("dispenseRequest", {})
        validity = dispense.get("validityPeriod", {})
        stop = _fhir_date(validity.get("end")) if validity else None

        # Dispense count
        dispenses = dispense.get("numberOfRepeatsAllowed") or dispense.get("quantity", {}).get("value")

        enc_ref = (
            resource.get("context", {}).get("reference", "")
            or resource.get("encounter", {}).get("reference", "")
        )
        encounter_id = _extract_uuid(enc_ref)

        return {
            "record_type": "medication",
            "START": start,
            "STOP": stop,
            "PATIENT": patient_id,
            "ENCOUNTER": encounter_id or None,
            "CODE": code_info["code"],
            "DESCRIPTION": code_info["display"],
            "DISPENSES": str(dispenses) if dispenses else None,
            "TOTALCOST": None,  # Not available in FHIR R3 MedicationRequest
        }

    def _parse_observation(
        self,
        resource: dict[str, Any],
        patient_id: str,
        encounter_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Parse a FHIR Observation resource.

        Args:
            resource: FHIR Observation resource dict.
            patient_id: Patient UUID.
            encounter_map: Encounter FK lookup.

        Returns:
            Row dict or None.
        """
        code_info = _extract_coding(resource.get("code", {}))
        if not code_info:
            return None

        date = _fhir_date(
            resource.get("effectiveDateTime")
            or resource.get("effectivePeriod", {}).get("start")
        )

        # Value: numeric (valueQuantity) or string (valueString/valueCodeableConcept)
        value = ""
        units = ""
        obs_type = "numeric"
        if "valueQuantity" in resource:
            vq = resource["valueQuantity"]
            value = str(vq.get("value", ""))
            units = vq.get("unit", "") or vq.get("code", "")
        elif "valueString" in resource:
            value = resource["valueString"]
            obs_type = "text"
        elif "valueCodeableConcept" in resource:
            codings = resource["valueCodeableConcept"].get("coding", [])
            value = codings[0].get("display", "") if codings else ""
            obs_type = "text"
        elif "valueBoolean" in resource:
            value = str(resource["valueBoolean"])
            obs_type = "boolean"

        enc_ref = (
            resource.get("context", {}).get("reference", "")
            or resource.get("encounter", {}).get("reference", "")
        )
        encounter_id = _extract_uuid(enc_ref)

        return {
            "record_type": "observation",
            "DATE": date,
            "PATIENT": patient_id,
            "ENCOUNTER": encounter_id or None,
            "CODE": code_info["code"],
            "DESCRIPTION": code_info["display"],
            "VALUE": value or None,
            "UNITS": units or None,
            "TYPE": obs_type,
        }

    def _parse_procedure(
        self,
        resource: dict[str, Any],
        patient_id: str,
        encounter_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Parse a FHIR Procedure resource.

        Args:
            resource: FHIR Procedure resource dict.
            patient_id: Patient UUID.
            encounter_map: Encounter FK lookup.

        Returns:
            Row dict or None.
        """
        code_info = _extract_coding(resource.get("code", {}))
        if not code_info:
            return None

        date = _fhir_date(
            resource.get("performedDateTime")
            or resource.get("performedPeriod", {}).get("start")
        )

        enc_ref = (
            resource.get("context", {}).get("reference", "")
            or resource.get("encounter", {}).get("reference", "")
        )
        encounter_id = _extract_uuid(enc_ref)

        return {
            "record_type": "procedure",
            "DATE": date,
            "PATIENT": patient_id,
            "ENCOUNTER": encounter_id or None,
            "CODE": code_info["code"],
            "DESCRIPTION": code_info["display"],
            "COST": None,
        }

    @staticmethod
    def _extract_patient(bundle: dict[str, Any]) -> dict[str, Any] | None:
        """Extract the Patient row dict from a bundle.

        Args:
            bundle: Parsed FHIR Bundle dict.

        Returns:
            Patient row dict or None.
        """
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "Patient":
                pid = resource.get("id", "")
                race, ethnicity = _extract_race_ethnicity(resource)
                birth = _fhir_date(resource.get("birthDate"))
                death = _fhir_date(resource.get("deceasedDateTime"))
                name = resource.get("name", [{}])[0]
                given = " ".join(name.get("given", []))
                family = name.get("family", "")
                return {
                    "Id": pid,
                    "FIRST": given,
                    "LAST": family,
                    "BIRTHDATE": birth,
                    "DEATHDATE": death,
                    "GENDER": resource.get("gender", "unknown"),
                    "RACE": race,
                    "ETHNICITY": ethnicity,
                }
        return None


# ------------------------------------------------------------------
# FHIR parsing utility functions
# ------------------------------------------------------------------


def _fhir_date(value: str | None) -> str | None:
    """Normalise a FHIR datetime string to YYYY-MM-DD.

    FHIR datetimes may be full ISO strings ("2010-01-01T00:00:00-05:00"),
    date-only strings ("2010-01-01"), or None. We truncate to YYYY-MM-DD
    to match the format expected by temporal_mapper.date_to_micros().

    Args:
        value: FHIR datetime string or None.

    Returns:
        "YYYY-MM-DD" string or None.
    """
    if not value:
        return None
    # Strip time component if present
    return value[:10]


def _extract_uuid(reference: str) -> str:
    """Extract a UUID from a FHIR reference string.

    FHIR references can be:
      - "urn:uuid:550e8400-e29b-41d4-a716-446655440000"
      - "Patient/550e8400-e29b-41d4-a716-446655440000"
      - "550e8400-e29b-41d4-a716-446655440000"

    Args:
        reference: FHIR reference string.

    Returns:
        UUID string, or empty string if not extractable.
    """
    if not reference:
        return ""
    if reference.startswith("urn:uuid:"):
        return reference[len("urn:uuid:"):]
    if "/" in reference:
        return reference.split("/")[-1]
    return reference


def _extract_coding(codeable_concept: dict[str, Any]) -> dict[str, str] | None:
    """Extract the primary code and display text from a FHIR CodeableConcept.

    Returns the first coding entry with a non-empty code. Prefers SNOMED,
    RxNorm, or LOINC codings over local codes, but accepts any coding system.

    Args:
        codeable_concept: FHIR CodeableConcept dict.

    Returns:
        Dict with keys "code" and "display", or None if no valid coding found.
    """
    if not codeable_concept:
        return None

    codings = codeable_concept.get("coding", [])
    if not codings:
        # Fall back to text
        text = codeable_concept.get("text")
        if text:
            return {"code": "", "display": text}
        return None

    # Prefer recognised coding systems
    preferred_systems = (
        "http://snomed.info/sct",
        "http://www.nlm.nih.gov/research/umls/rxnorm",
        "http://loinc.org",
    )
    for system in preferred_systems:
        for coding in codings:
            if coding.get("system") == system and coding.get("code"):
                return {
                    "code": coding["code"],
                    "display": coding.get("display") or coding["code"],
                }

    # Fall back to first coding with any code
    for coding in codings:
        if coding.get("code"):
            return {
                "code": coding["code"],
                "display": coding.get("display") or coding["code"],
            }

    return None


def _extract_race_ethnicity(patient: dict[str, Any]) -> tuple[str, str]:
    """Extract race and ethnicity from US Core FHIR extensions.

    Synthea adds these as extensions on the Patient resource. The URL
    varies slightly between DSTU2 and R3 versions; we check both.

    Args:
        patient: FHIR Patient resource dict.

    Returns:
        Tuple of (race_str, ethnicity_str). Both default to "unknown".
    """
    race = "unknown"
    ethnicity = "unknown"

    for ext in patient.get("extension", []):
        url = ext.get("url", "")
        if url in (_RACE_URL, _RACE_URL_ALT):
            # R3: nested extension with url "ombCategory" or "text"
            for sub in ext.get("extension", []):
                if sub.get("url") == "text":
                    race = sub.get("valueString", race)
                    break
                if sub.get("url") == "ombCategory":
                    race = sub.get("valueCoding", {}).get("display", race)
            # DSTU2: flat valueString or valueCoding
            if ext.get("valueString"):
                race = ext["valueString"]
            elif ext.get("valueCoding", {}).get("display"):
                race = ext["valueCoding"]["display"]

        elif url in (_ETHNICITY_URL, _ETHNICITY_URL_ALT):
            for sub in ext.get("extension", []):
                if sub.get("url") == "text":
                    ethnicity = sub.get("valueString", ethnicity)
                    break
                if sub.get("url") == "ombCategory":
                    ethnicity = sub.get("valueCoding", {}).get("display", ethnicity)
            if ext.get("valueString"):
                ethnicity = ext["valueString"]
            elif ext.get("valueCoding", {}).get("display"):
                ethnicity = ext["valueCoding"]["display"]

    return race, ethnicity


def _fhir_class(encounter: dict[str, Any]) -> str | None:
    """Extract encounter class display string (ambulatory, inpatient, etc).

    Args:
        encounter: FHIR Encounter resource dict.

    Returns:
        Class display string or None.
    """
    cls = encounter.get("class", {})
    if isinstance(cls, dict):
        return cls.get("display") or cls.get("code")
    return None
