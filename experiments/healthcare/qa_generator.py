"""Ground-truth QA pair generator for Synthea-based healthcare experiments.

Generates two sets of benchmark tasks by joining the raw Synthea CSV files.
No LLM calls are needed — the CSV data IS the ground truth.

Experiment 1 — Temporal Decay QA pairs:
    For each sampled patient, create questions about their most recent active
    condition or their medication history at a specific point in time.
    Ground truth is derived by sorting and filtering conditions.csv / medications.csv.

Experiment 2 — Multi-hop Cohort Queries:
    For a set of (condition_code, medication_code) pairs, derive the set of
    patients who have BOTH, and the providers who treated those patients.
    Ground truth is a pure Python join over conditions + medications + encounters.

Output format for both experiments:
    JSON file written to experiments/healthcare/tasks/{exp_id}_{timestamp}.json

Role in the project:
    Called by exp1_temporal_decay.py and exp2_multihop.py before running retrieval.
    Can also be run standalone to pre-generate and inspect task sets.
"""

from __future__ import annotations

import gzip
import json
import logging
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Interesting condition/medication pairs for Experiment 2 cohort queries.
# These are real SNOMED CT codes (conditions) and RxNorm codes (medications)
# that appear frequently in Synthea's synthetic population.
_DEFAULT_COHORT_PAIRS = [
    {
        "condition_description": "Hypertension",
        "condition_snomed": "38341003",
        "medication_description": "Lisinopril",
        "medication_rxnorm": "314076",
        "label": "hypertension_lisinopril",
    },
    {
        "condition_description": "Type 2 diabetes mellitus",
        "condition_snomed": "44054006",
        "medication_description": "Metformin",
        "medication_rxnorm": "860975",
        "label": "diabetes_metformin",
    },
    {
        "condition_description": "Coronary Heart Disease",
        "condition_snomed": "53741008",
        "medication_description": "Atorvastatin",
        "medication_rxnorm": "617310",
        "label": "chd_atorvastatin",
    },
    {
        "condition_description": "Asthma",
        "condition_snomed": "195967001",
        "medication_description": "Albuterol",
        "medication_rxnorm": "307779",
        "label": "asthma_albuterol",
    },
]


class SyntheaQAGenerator:
    """Generates ground-truth QA pairs from Synthea CSV files.

    Both generators work by joining multiple CSV tables in pure Python —
    no database, no pandas, no LLM. The CSV data provides deterministic
    ground truth that makes scoring straightforward.

    Args:
        data_dir: Directory containing Synthea CSV files.

    Example:
        gen = SyntheaQAGenerator("/data/synthea/")
        tasks = gen.generate_temporal_qa(n_patients=200)
        gen.save_tasks(tasks, "experiments/healthcare/tasks/exp1_tasks.json")
    """

    def __init__(self, data_dir: str | Path) -> None:
        """Initialise the generator.

        Args:
            data_dir: Path to Synthea data — either a .tar.gz FHIR bundle
                file, a directory of sub-tarballs, or a CSV directory.
                When FHIR format is detected, the generator uses
                SyntheaFHIRLoader to stream records; otherwise SyntheaCSVLoader.
                A corrected embedded export directory is also supported. In
                that case the generator reads the normalized row payloads from
                ``chunk-*.jsonl.gz`` directly, which is much faster than
                reparsing raw FHIR bundles during benchmark setup.
        """
        self._dir = Path(data_dir)
        self._is_embedded_export = (
            self._dir.is_dir()
            and (self._dir / "manifest.json").exists()
            and any(self._dir.glob("chunk-*.jsonl.gz"))
        )
        self._is_fhir = (
            not self._is_embedded_export
            and (
                self._dir.suffix in (".gz", ".tgz")
                or self._dir.name.endswith(".tar.gz")
                or (self._dir.is_dir() and not (self._dir / "patients.csv").exists())
            )
        )
        self._embedded_indexes: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Experiment 1: Temporal QA pairs
    # ------------------------------------------------------------------

    def generate_temporal_qa(
        self,
        n_patients: int = 200,
        as_of_date: str = "2017-01-01",
        seed: int = 42,
    ) -> list[dict[str, Any]]:
        """Generate temporal QA tasks for Experiment 1.

        For each sampled patient creates up to two question types:
          - "most_recent_condition": What is patient X's most recent active condition?
          - "active_medication": What medications was patient X taking on as_of_date?

        Args:
            n_patients: Number of patients to sample. Must be <= total patients.
            as_of_date: Reference date for point-in-time medication queries
                (YYYY-MM-DD string). Medications active on this date are the
                correct answer.
            seed: Random seed for reproducible patient sampling.

        Returns:
            List of task dicts, each matching the Experiment 1 task schema.
        """
        rng = random.Random(seed)

        # Load conditions grouped by patient
        conditions_by_patient = self._load_conditions_by_patient()
        # Load medications grouped by patient
        medications_by_patient = self._load_medications_by_patient()

        # Sample from patients that have at least one condition
        eligible_patients = [
            pid
            for pid, conds in conditions_by_patient.items()
            if len(conds) >= 2  # Need ≥2 conditions so there are "competing" answers
        ]
        n = min(n_patients, len(eligible_patients))
        sampled = rng.sample(eligible_patients, n)
        logger.info(
            "Temporal QA: %d eligible patients, %d sampled (seed=%d)",
            len(eligible_patients),
            n,
            seed,
        )

        tasks: list[dict[str, Any]] = []
        task_idx = 0

        for patient_id in sampled:
            conditions = conditions_by_patient[patient_id]

            # Task type 1: most recent active condition
            active = [c for c in conditions if not c.get("STOP")]
            if active:
                most_recent = max(active, key=lambda c: c["START"])
                competing = [
                    c["DESCRIPTION"] for c in conditions if c is not most_recent
                ][:4]
                tasks.append({
                    "id": f"EXP1-T{task_idx:04d}",
                    "patient_id": patient_id,
                    "category": "temporal_recency",
                    "query": (
                        f"What is the most recent active condition for patient {patient_id[:8]}?"
                    ),
                    "ground_truth": most_recent["DESCRIPTION"],
                    "ground_truth_date": most_recent["START"],
                    "competing_answers": competing,
                    "as_of_date": as_of_date,
                    "notes": "Most recent active (no STOP) condition by START date.",
                })
                task_idx += 1

            # Task type 2: active medications at as_of_date
            meds = medications_by_patient.get(patient_id, [])
            active_meds = [
                m for m in meds
                if m["START"] <= as_of_date
                and (not m.get("STOP") or m["STOP"] >= as_of_date)
            ]
            if active_meds:
                tasks.append({
                    "id": f"EXP1-T{task_idx:04d}",
                    "patient_id": patient_id,
                    "category": "temporal_active_medications",
                    "query": (
                        f"What medications was patient {patient_id[:8]} taking on {as_of_date}?"
                    ),
                    "ground_truth_medications": [m["DESCRIPTION"] for m in active_meds],
                    "ground_truth_count": len(active_meds),
                    "all_patient_medications": [m["DESCRIPTION"] for m in meds],
                    "as_of_date": as_of_date,
                    "notes": "Medications where START <= as_of_date and (no STOP or STOP >= as_of_date).",
                })
                task_idx += 1

        logger.info("Generated %d temporal QA tasks.", len(tasks))
        return tasks

    # ------------------------------------------------------------------
    # Experiment 2: Multi-hop cohort queries
    # ------------------------------------------------------------------

    def generate_cohort_qa(
        self,
        pairs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate multi-hop cohort query tasks for Experiment 2.

        For each (condition, medication) pair in pairs, derives:
          - The set of patient IDs who have BOTH the condition AND the medication
          - The set of provider IDs who treated those patients in any encounter

        The ground truth is computed by pure Python joins over CSV data.

        Args:
            pairs: List of cohort pair dicts, each with keys:
                condition_description, condition_snomed, medication_description,
                medication_rxnorm, label.
                Defaults to _DEFAULT_COHORT_PAIRS.

        Returns:
            List of task dicts matching the Experiment 2 cohort schema.
        """
        if pairs is None:
            pairs = _DEFAULT_COHORT_PAIRS

        # Load lookup tables once
        condition_patients = self._load_condition_patients_by_code()
        medication_patients = self._load_medication_patients_by_code()
        encounter_providers = self._load_encounter_providers_by_patient()

        tasks: list[dict[str, Any]] = []

        for idx, pair in enumerate(pairs):
            # Match on DESCRIPTION (case-insensitive substring) rather than
            # exact code because Synthea sometimes has slight code variations.
            cond_desc = pair["condition_description"].lower()
            med_desc = pair["medication_description"].lower()

            cond_patients: set[str] = set()
            for desc, pids in condition_patients.items():
                if cond_desc in desc.lower():
                    cond_patients.update(pids)

            med_patients: set[str] = set()
            for desc, pids in medication_patients.items():
                if med_desc in desc.lower():
                    med_patients.update(pids)

            # Intersection: patients with BOTH condition AND medication
            matched_patients = cond_patients & med_patients

            # Providers who treated matched patients in any encounter
            provider_ids: set[str] = set()
            for pid in matched_patients:
                providers = encounter_providers.get(pid, set())
                provider_ids.update(providers)

            logger.info(
                "Cohort [%s]: %d cond_patients, %d med_patients, "
                "%d matched, %d providers",
                pair["label"],
                len(cond_patients),
                len(med_patients),
                len(matched_patients),
                len(provider_ids),
            )

            tasks.append({
                "id": f"EXP2-C{idx:04d}",
                "label": pair["label"],
                "category": "multihop_cohort",
                "query": (
                    f"Which providers treated patients who had both "
                    f"{pair['condition_description']} AND were prescribed "
                    f"{pair['medication_description']}?"
                ),
                "condition_description": pair["condition_description"],
                "condition_snomed": pair["condition_snomed"],
                "medication_description": pair["medication_description"],
                "medication_rxnorm": pair["medication_rxnorm"],
                "ground_truth_patient_ids": sorted(matched_patients),
                "ground_truth_provider_ids": sorted(provider_ids),
                "patient_count": len(matched_patients),
                "provider_count": len(provider_ids),
                "notes": (
                    "Ground truth derived from pure Python join: "
                    "conditions ∩ medications → encounters → providers."
                ),
            })

        logger.info("Generated %d cohort QA tasks.", len(tasks))
        return tasks

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def save_tasks(tasks: list[dict[str, Any]], output_path: str | Path) -> None:
        """Write tasks to a JSON file.

        Args:
            tasks: List of task dicts to persist.
            output_path: Destination file path. Parent directories are created.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(tasks, fh, indent=2, default=str)
        logger.info("Tasks written to %s (%d tasks).", path, len(tasks))

    @staticmethod
    def load_tasks(tasks_path: str | Path) -> list[dict[str, Any]]:
        """Load tasks from a JSON file.

        Args:
            tasks_path: Path to the tasks JSON file.

        Returns:
            List of task dicts.
        """
        with open(tasks_path, encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------
    # Private CSV loading helpers (pure Python joins, no pandas)
    # ------------------------------------------------------------------

    def _iter_records_of_type(self, record_type: str):
        """Yield record rows of the given type from the most efficient source.

        For FHIR tarballs, uses iter_csv_from_tarball() which streams the
        nested csv/ directory directly — much faster than re-parsing all FHIR
        bundles for bulk joins needed by the QA generator.

        For CSV directories, reads the CSV file directly.

        Args:
            record_type: One of "condition", "medication", "encounter", etc.

        Yields:
            Row dicts with the standard CSV-compatible field names.
        """
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

        if self._is_embedded_export:
            for row in self._iter_embedded_export_rows(record_type):
                yield row
        elif self._is_fhir:
            from agentic_memory.healthcare.fhir_loader import SyntheaFHIRLoader
            loader = SyntheaFHIRLoader(self._dir)
            # Use the fast CSV-within-tarball path: each sub-tarball has
            # output_N/csv/{table}.csv — no FHIR JSON parsing needed for bulk joins
            table = record_type + "s"  # e.g. "conditions"
            source = self._dir if self._dir.is_file() else None
            if source is not None:
                # Outer tarball: stream CSV tables directly
                yield from loader.iter_csv_from_tarball(source, table)
            else:
                # Directory of sub-tarballs: stream from each
                sub_tarballs = sorted(self._dir.glob("*.tar.gz"))
                if sub_tarballs:
                    import csv as csv_module
                    import tarfile, io
                    csv_filename = f"{table}.csv"
                    for sub_path in sub_tarballs:
                        with tarfile.open(sub_path, "r:gz") as inner:
                            for member in inner.getmembers():
                                parts = Path(member.name).parts
                                if len(parts) == 3 and parts[1] == "csv" and parts[2] == csv_filename:
                                    fh = inner.extractfile(member)
                                    if fh:
                                        text = io.TextIOWrapper(fh, encoding="utf-8-sig")
                                        reader = csv_module.DictReader(text)
                                        for row in reader:
                                            yield {k: (v.strip() or None) for k, v in row.items()}
                                        break
                else:
                    # Fall back: parse FHIR bundles (slower)
                    for row in loader.iter_records():
                        if row.get("record_type") == record_type:
                            yield row
        else:
            import csv
            filename = record_type + "s.csv"  # e.g. "conditions.csv"
            path = self._dir / filename
            if not path.exists():
                logger.warning("CSV not found: %s", path)
                return
            with open(path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    yield {k: (v.strip() or None) for k, v in row.items()}

    def _iter_embedded_export_rows(self, record_type: str):
        """Yield normalized row payloads from an embedded export directory.

        The corrected healthcare export already contains the benchmark-relevant
        normalized row dict under ``item["row"]``. Reusing that payload keeps
        QA generation aligned with the exact data we imported into Neo4j and
        SpacetimeDB, while avoiding a second slow FHIR parsing pass.
        """
        for chunk_path in sorted(self._dir.glob("chunk-*.jsonl.gz")):
            with gzip.open(chunk_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    item_type = item.get("record_type")
                    row = item.get("row") or {}
                    row_type = row.get("record_type")
                    if item_type != record_type and row_type != record_type:
                        continue
                    if isinstance(row, dict):
                        yield row

    def _ensure_embedded_indexes(self) -> dict[str, Any]:
        """Scan the embedded export once and cache the join-friendly indexes.

        Why this cache exists:
            Experiment setup needs several different joins over the same
            clinical tables. Re-reading 145 compressed chunk files for each
            join would still be faster than raw FHIR parsing, but it is
            unnecessary work. This cache scans the export once and stores the
            exact patient/provider/description lookup tables the QA generator
            needs.
        """
        if self._embedded_indexes is not None:
            return self._embedded_indexes

        conditions_by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        medications_by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        condition_patients_by_desc: dict[str, set[str]] = defaultdict(set)
        medication_patients_by_desc: dict[str, set[str]] = defaultdict(set)
        encounter_providers_by_patient: dict[str, set[str]] = defaultdict(set)
        scanned_rows = 0
        chunk_paths = sorted(self._dir.glob("chunk-*.jsonl.gz"))

        for chunk_path in chunk_paths:
            with gzip.open(chunk_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    row = item.get("row") or {}
                    if not isinstance(row, dict):
                        continue
                    record_type = item.get("record_type") or row.get("record_type")
                    scanned_rows += 1

                    if record_type == "condition":
                        patient_id = row.get("PATIENT")
                        description = row.get("DESCRIPTION") or ""
                        if patient_id:
                            conditions_by_patient[patient_id].append(row)
                            if description:
                                condition_patients_by_desc[description].add(patient_id)
                    elif record_type == "medication":
                        patient_id = row.get("PATIENT")
                        description = row.get("DESCRIPTION") or ""
                        if patient_id:
                            medications_by_patient[patient_id].append(row)
                            if description:
                                medication_patients_by_desc[description].add(patient_id)
                    elif record_type == "encounter":
                        patient_id = row.get("PATIENT") or ""
                        provider_id = row.get("PROVIDER") or ""
                        if patient_id and provider_id:
                            encounter_providers_by_patient[patient_id].add(provider_id)

        self._embedded_indexes = {
            "conditions_by_patient": dict(conditions_by_patient),
            "medications_by_patient": dict(medications_by_patient),
            "condition_patients_by_desc": dict(condition_patients_by_desc),
            "medication_patients_by_desc": dict(medication_patients_by_desc),
            "encounter_providers_by_patient": dict(encounter_providers_by_patient),
        }
        logger.info(
            "Embedded-export QA indexes built from %d rows across %d chunks.",
            scanned_rows,
            len(chunk_paths),
        )
        return self._embedded_indexes

    def _load_conditions_by_patient(self) -> dict[str, list[dict[str, Any]]]:
        """Load {patient_id: [condition_rows]} from conditions data."""
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["conditions_by_patient"]
        by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._iter_records_of_type("condition"):
            pid = row.get("PATIENT")
            if pid:
                by_patient[pid].append(row)
        return dict(by_patient)

    def _load_medications_by_patient(self) -> dict[str, list[dict[str, Any]]]:
        """Load {patient_id: [medication_rows]} from medications data."""
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["medications_by_patient"]
        by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._iter_records_of_type("medication"):
            pid = row.get("PATIENT")
            if pid:
                by_patient[pid].append(row)
        return dict(by_patient)

    def _load_condition_patients_by_code(self) -> dict[str, set[str]]:
        """Load {condition_description: {patient_ids}} from conditions data."""
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["condition_patients_by_desc"]
        by_code: dict[str, set[str]] = defaultdict(set)
        for row in self._iter_records_of_type("condition"):
            desc = row.get("DESCRIPTION") or ""
            pid = row.get("PATIENT") or ""
            if desc and pid:
                by_code[desc].add(pid)
        return dict(by_code)

    def _load_medication_patients_by_code(self) -> dict[str, set[str]]:
        """Load {medication_description: {patient_ids}} from medications data."""
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["medication_patients_by_desc"]
        by_code: dict[str, set[str]] = defaultdict(set)
        for row in self._iter_records_of_type("medication"):
            desc = row.get("DESCRIPTION") or ""
            pid = row.get("PATIENT") or ""
            if desc and pid:
                by_code[desc].add(pid)
        return dict(by_code)

    def _load_encounter_providers_by_patient(self) -> dict[str, set[str]]:
        """Load {patient_id: {provider_ids}} from encounters data."""
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["encounter_providers_by_patient"]
        by_patient: dict[str, set[str]] = defaultdict(set)
        for row in self._iter_records_of_type("encounter"):
            pid = row.get("PATIENT") or ""
            prov = row.get("PROVIDER") or ""
            if pid and prov:
                by_patient[pid].add(prov)
        return dict(by_patient)
