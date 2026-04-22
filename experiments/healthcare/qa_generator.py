"""Ground-truth QA pair generator for Synthea-based healthcare experiments.

Generates two sets of benchmark tasks by joining the raw Synthea CSV files.
No LLM calls are needed — the CSV data IS the ground truth.

Experiment 1 — Temporal Decay QA pairs:
    For each sampled patient, create questions about their most recent active
    condition or their medication history at a specific point in time.
    Ground truth is derived by sorting and filtering conditions.csv / medications.csv.

Experiment 2 — Multi-hop Reasoning Queries:
    Mine clinically readable condition/medication overlap tasks from the
    dataset itself, then derive deterministic patient-cohort and provider-
    attribution answer sets. Ground truth is a pure Python join over
    conditions + medications + encounters.

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
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EXP1A_CALENDAR_SWEEP_DATES = [
    "2008-06-30",
    "2012-06-30",
    "2016-06-30",
    "2020-06-30",
]

_EXP1A_RECURRING_CONDITION_TERMS = {
    "viral sinusitis",
    "acute viral pharyngitis",
    "acute bronchitis",
    "otitis media",
    "streptococcal sore throat",
    "sprain of ankle",
    "sprain of wrist",
    "sinusitis",
    "acute bacterial sinusitis",
    "concussion",
    "laceration",
    "fracture",
}

# Curated family-level concepts for the rebuilt Experiment 2 benchmark.
# The benchmark no longer depends on a tiny hard-coded set of exact pairs.
# Instead, it uses readable clinical families, discovers which overlaps are
# actually present in the dataset, filters them for benchmarkability, and then
# emits both patient-cohort and provider-attribution tasks from the same mined
# overlap graph.
_DEFAULT_CONDITION_FAMILIES = [
    {"label": "hypertension", "display_name": "Hypertension", "match_terms": ["hypertension"]},
    {
        "label": "type_2_diabetes",
        "display_name": "Type 2 diabetes mellitus",
        "match_terms": ["type 2 diabetes", "diabetes mellitus", "diabetes"],
    },
    {
        "label": "prediabetes",
        "display_name": "Prediabetes",
        "match_terms": ["prediabetes"],
    },
    {"label": "coronary_heart_disease", "display_name": "Coronary Heart Disease", "match_terms": ["coronary heart disease"]},
    {"label": "asthma", "display_name": "Asthma", "match_terms": ["asthma", "childhood asthma"]},
    {"label": "atrial_fibrillation", "display_name": "Atrial fibrillation", "match_terms": ["atrial fibrillation"]},
    {"label": "chronic_kidney_disease", "display_name": "Chronic kidney disease", "match_terms": ["chronic kidney disease", "renal disease", "microalbuminuria"]},
    {"label": "copd", "display_name": "Chronic obstructive pulmonary disease", "match_terms": ["chronic obstructive pulmonary disease", "chronic obstructive bronchitis", "pulmonary emphysema"]},
    {"label": "obesity", "display_name": "Obesity", "match_terms": ["obesity"]},
    {"label": "stroke", "display_name": "Stroke", "match_terms": ["stroke"]},
    {"label": "osteoporosis", "display_name": "Osteoporosis", "match_terms": ["osteoporosis"]},
    {
        "label": "alzheimers_disease",
        "display_name": "Alzheimer's disease",
        "match_terms": ["alzheimer"],
    },
]

_DEFAULT_MEDICATION_FAMILIES = [
    {
        "label": "metformin",
        "display_name": "Metformin",
        "match_terms": ["metformin"],
        "allowed_condition_families": {"type_2_diabetes", "prediabetes", "chronic_kidney_disease", "obesity"},
    },
    {
        "label": "insulin",
        "display_name": "Insulin",
        "match_terms": ["insulin"],
        "allowed_condition_families": {"type_2_diabetes", "chronic_kidney_disease", "hypertension"},
    },
    {
        "label": "liraglutide",
        "display_name": "Liraglutide",
        "match_terms": ["liraglutide"],
        "allowed_condition_families": {"type_2_diabetes", "prediabetes", "chronic_kidney_disease", "obesity"},
    },
    {
        "label": "atorvastatin",
        "display_name": "Atorvastatin",
        "match_terms": ["atorvastatin"],
        "allowed_condition_families": {"coronary_heart_disease", "stroke", "type_2_diabetes", "chronic_kidney_disease"},
    },
    {
        "label": "simvastatin",
        "display_name": "Simvastatin",
        "match_terms": ["simvastatin"],
        "allowed_condition_families": {"coronary_heart_disease", "stroke", "type_2_diabetes", "chronic_kidney_disease"},
    },
    {
        "label": "albuterol",
        "display_name": "Albuterol",
        "match_terms": ["albuterol"],
        "allowed_condition_families": {"asthma", "copd"},
    },
    {
        "label": "fluticasone_salmeterol",
        "display_name": "Fluticasone/Salmeterol",
        "match_terms": ["salmeterol", "fluticasone"],
        "allowed_condition_families": {"asthma", "copd"},
    },
    {
        "label": "amlodipine",
        "display_name": "Amlodipine",
        "match_terms": ["amlodipine"],
        "allowed_condition_families": {"hypertension", "coronary_heart_disease", "chronic_kidney_disease"},
    },
    {
        "label": "captopril",
        "display_name": "Captopril",
        "match_terms": ["captopril"],
        "allowed_condition_families": {"hypertension", "coronary_heart_disease", "chronic_kidney_disease"},
    },
    {
        "label": "nitroglycerin",
        "display_name": "Nitroglycerin",
        "match_terms": ["nitroglycerin"],
        "allowed_condition_families": {"coronary_heart_disease"},
    },
    {
        "label": "clopidogrel",
        "display_name": "Clopidogrel",
        "match_terms": ["clopidogrel"],
        "allowed_condition_families": {"coronary_heart_disease", "stroke"},
    },
    {
        "label": "warfarin",
        "display_name": "Warfarin",
        "match_terms": ["warfarin"],
        "allowed_condition_families": {"atrial_fibrillation"},
    },
    {
        "label": "lisinopril",
        "display_name": "Lisinopril",
        "match_terms": ["lisinopril"],
        "allowed_condition_families": {"hypertension", "chronic_kidney_disease"},
    },
    {
        "label": "losartan",
        "display_name": "Losartan",
        "match_terms": ["losartan"],
        "allowed_condition_families": {"hypertension", "chronic_kidney_disease"},
    },
    {
        "label": "furosemide",
        "display_name": "Furosemide",
        "match_terms": ["furosemide"],
        "allowed_condition_families": {"hypertension", "chronic_kidney_disease", "coronary_heart_disease"},
    },
    {
        "label": "alendronic_acid",
        "display_name": "Alendronic acid",
        "match_terms": ["alendronic acid", "fosamax"],
        "allowed_condition_families": {"osteoporosis"},
    },
    {
        "label": "galantamine",
        "display_name": "Galantamine",
        "match_terms": ["galantamine", "razadyne"],
        "allowed_condition_families": {"alzheimers_disease"},
    },
    {
        "label": "donepezil",
        "display_name": "Donepezil",
        "match_terms": ["donepezil", "aricept", "namzaric"],
        "allowed_condition_families": {"alzheimers_disease"},
    },
]

# Observation rules used to mine clinically richer Exp 2 tasks.
# Each rule is intentionally simple and deterministic:
#   - one normalized observation description
#   - one numeric comparison against the patient's latest value
#   - optional condition-family compatibility to avoid clinically silly pairs
#
# These are not meant to represent perfect real-world guideline logic.
# They are benchmark task templates for multihop retrieval over structured
# longitudinal data that already exists in the corrected Synthea export.
_DEFAULT_OBSERVATION_RULES = [
    {
        "label": "hba1c_poor_control",
        "description": "Hemoglobin A1c/Hemoglobin.total in Blood",
        "match_terms": ["hemoglobin a1c", "hemoglobin.total in blood"],
        "display_name": "most recent HbA1c > 9%",
        "operator": ">",
        "threshold": 9.0,
        "allowed_condition_families": {"type_2_diabetes", "prediabetes", "obesity"},
    },
    {
        "label": "glucose_high",
        "description": "Glucose",
        "match_terms": ["glucose"],
        "display_name": "most recent glucose >= 126 mg/dL",
        "operator": ">=",
        "threshold": 126.0,
        "allowed_condition_families": {"type_2_diabetes", "prediabetes", "obesity"},
    },
    {
        "label": "egfr_low",
        "description": "Estimated Glomerular Filtration Rate",
        "match_terms": ["glomerular filtration rate"],
        "display_name": "most recent eGFR < 60",
        "operator": "<",
        "threshold": 60.0,
        "allowed_condition_families": {"type_2_diabetes", "chronic_kidney_disease", "hypertension"},
    },
    {
        "label": "microalbumin_high",
        "description": "Microalbumin Creatine Ratio",
        "match_terms": ["microalbumin creatine ratio", "microalbumin"],
        "display_name": "most recent microalbumin creatinine ratio >= 30 mg/g",
        "operator": ">=",
        "threshold": 30.0,
        "allowed_condition_families": {"type_2_diabetes", "chronic_kidney_disease", "hypertension"},
    },
    {
        "label": "bmi_high",
        "description": "Body Mass Index",
        "match_terms": ["body mass index"],
        "display_name": "most recent BMI >= 30",
        "operator": ">=",
        "threshold": 30.0,
        "allowed_condition_families": {"obesity", "type_2_diabetes", "prediabetes", "hypertension"},
    },
    {
        "label": "ldl_high",
        "description": "Low Density Lipoprotein Cholesterol",
        "match_terms": ["low density lipoprotein cholesterol", "ldl cholesterol"],
        "display_name": "most recent LDL >= 130 mg/dL",
        "operator": ">=",
        "threshold": 130.0,
        "allowed_condition_families": {"coronary_heart_disease", "type_2_diabetes", "obesity"},
    },
    {
        "label": "triglycerides_high",
        "description": "Triglycerides",
        "match_terms": ["triglycerides"],
        "display_name": "most recent triglycerides >= 150 mg/dL",
        "operator": ">=",
        "threshold": 150.0,
        "allowed_condition_families": {"type_2_diabetes", "prediabetes", "obesity"},
    },
    {
        "label": "systolic_bp_high",
        "description": "Systolic Blood Pressure",
        "match_terms": ["systolic blood pressure"],
        "display_name": "most recent systolic blood pressure >= 140",
        "operator": ">=",
        "threshold": 140.0,
        "allowed_condition_families": {
            "hypertension",
            "coronary_heart_disease",
            "chronic_kidney_disease",
            "type_2_diabetes",
            "obesity",
        },
    },
    {
        "label": "diastolic_bp_high",
        "description": "Diastolic Blood Pressure",
        "match_terms": ["diastolic blood pressure"],
        "display_name": "most recent diastolic blood pressure >= 90",
        "operator": ">=",
        "threshold": 90.0,
        "allowed_condition_families": {
            "hypertension",
            "coronary_heart_disease",
            "chronic_kidney_disease",
            "type_2_diabetes",
            "obesity",
        },
    },
    {
        "label": "hdl_low",
        "description": "High Density Lipoprotein Cholesterol",
        "match_terms": ["high density lipoprotein cholesterol", "hdl cholesterol"],
        "display_name": "most recent HDL < 40 mg/dL",
        "operator": "<",
        "threshold": 40.0,
        "allowed_condition_families": {"coronary_heart_disease", "stroke", "type_2_diabetes", "obesity"},
    },
    {
        "label": "creatinine_high",
        "description": "Creatinine",
        "match_terms": ["creatinine"],
        "display_name": "most recent creatinine >= 1.3",
        "operator": ">=",
        "threshold": 1.3,
        "allowed_condition_families": {"chronic_kidney_disease", "type_2_diabetes", "hypertension"},
    },
    {
        "label": "dxa_tscore_low",
        "description": "DXA [T-score] Bone density",
        "match_terms": ["bone density"],
        "display_name": "most recent DXA T-score <= -2.5",
        "operator": "<=",
        "threshold": -2.5,
        "allowed_condition_families": {"osteoporosis"},
    },
    {
        "label": "mmse_low",
        "description": "Total score [MMSE]",
        "match_terms": ["mmse"],
        "display_name": "most recent MMSE < 24",
        "operator": "<",
        "threshold": 24.0,
        "allowed_condition_families": {"alzheimers_disease"},
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
    # Experiment 1A: isolated temporal-retrieval task families
    # ------------------------------------------------------------------

    def generate_supersession_tasks(
        self,
        patients: list[str] | set[str] | None = None,
        atc_class_map: dict[str, str] | None = None,
        *,
        max_tasks: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate same-class medication supersession tasks.

        This family tests whether retrieval can choose the medication interval
        that is valid at an external snapshot date when the same patient has
        earlier or later prescriptions in the same drug class. The gold answer
        is the same-class prescription whose interval overlaps ``as_of_date``;
        distractors are other prescriptions in that same class but different
        time intervals.

        Args:
            patients: Optional patient IDs to include. ``None`` means all
                patients in the export.
            atc_class_map: Medication substring-to-class mapping. The
                ``concept_mappings.ATC_CLASS_MAP`` module supplies the default
                from the CLI.
            max_tasks: Optional cap for fixture-size control.

        Returns:
            Exp 1A task dictionaries for the ``supersession`` family.
        """
        medications_by_patient = self._load_medications_by_patient()
        patient_filter = set(patients) if patients is not None else None
        tasks: list[dict[str, Any]] = []

        for patient_id in sorted(medications_by_patient):
            if patient_filter is not None and patient_id not in patient_filter:
                continue
            grouped = self._group_medications_by_family(
                medications_by_patient[patient_id],
                atc_class_map or {},
            )
            for concept_family, entries in grouped.items():
                if len(entries) < 2:
                    continue
                for as_of in _EXP1A_CALENDAR_SWEEP_DATES:
                    anchor = self._parse_exp1a_date(as_of)
                    active = [
                        entry for entry in entries
                        if self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], anchor)
                    ]
                    if not active:
                        continue
                    gold = max(active, key=lambda item: item["valid_from"] or "")
                    distractors = [
                        entry for entry in entries
                        if entry["source_id"] != gold["source_id"]
                        and not self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], anchor)
                    ]
                    if not distractors:
                        continue
                    tasks.append(self._build_exp1a_task(
                        task_index=len(tasks),
                        family="supersession",
                        category="temporal_supersession",
                        patient_id=patient_id,
                        query=(
                            f"Which {concept_family} medication was patient "
                            f"{patient_id[:8]} on as of {as_of}?"
                        ),
                        concept_family=concept_family,
                        as_of_date=as_of,
                        anchor_source="calendar_sweep",
                        gold=gold,
                        distractors=distractors,
                        notes=(
                            "Gold is the same-class prescription active at the "
                            "calendar snapshot; distractors are same-class "
                            "prescriptions from other intervals."
                        ),
                    ))
                    if max_tasks is not None and len(tasks) >= max_tasks:
                        return self._finalize_exp1a_tasks(tasks)
        return self._finalize_exp1a_tasks(tasks)

    def generate_regimen_change_tasks(
        self,
        patients: list[str] | set[str] | None = None,
        indication_map: dict[str, str] | None = None,
        *,
        max_tasks: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate medication-regimen tasks anchored to clinical events.

        Regimen-change tasks ask what a patient was taking for a clinical
        indication at the time of an unrelated encounter or procedure. This
        keeps the anchor outside the answer interval's own start/stop dates and
        forces retrieval to distinguish same-indication alternatives across the
        patient timeline.

        Args:
            patients: Optional patient IDs to include.
            indication_map: Medication substring-to-indication mapping.
            max_tasks: Optional cap for fixture-size control.

        Returns:
            Exp 1A task dictionaries for the ``regimen_change`` family.
        """
        medications_by_patient = self._load_medications_by_patient()
        events_by_patient = self._load_events_by_patient()
        patient_filter = set(patients) if patients is not None else None
        tasks: list[dict[str, Any]] = []

        for patient_id in sorted(medications_by_patient):
            if patient_filter is not None and patient_id not in patient_filter:
                continue
            grouped = self._group_medications_by_family(
                medications_by_patient[patient_id],
                indication_map or {},
            )
            events = sorted(events_by_patient.get(patient_id, []), key=lambda item: item["date"] or "")
            if not events:
                continue
            for indication, entries in grouped.items():
                if len(entries) < 2:
                    continue
                for event in events:
                    event_date = self._parse_exp1a_date(event.get("date"))
                    if event_date is None:
                        continue
                    active = [
                        entry for entry in entries
                        if self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], event_date)
                        and event["date"] not in {entry["valid_from"], entry["valid_to"]}
                    ]
                    if not active:
                        continue
                    gold = max(active, key=lambda item: item["valid_from"] or "")
                    distractors = [
                        entry for entry in entries
                        if entry["source_id"] != gold["source_id"]
                        and not self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], event_date)
                    ]
                    if not distractors:
                        continue
                    tasks.append(self._build_exp1a_task(
                        task_index=len(tasks),
                        family="regimen_change",
                        category="temporal_regimen_change",
                        patient_id=patient_id,
                        query=(
                            f"What was patient {patient_id[:8]} taking for "
                            f"{indication} at the time of their "
                            f"{event.get('description', 'clinical event')} on {event['date']}?"
                        ),
                        concept_family=indication,
                        as_of_date=event["date"],
                        anchor_source="clinical_event",
                        anchor_event=event,
                        gold=gold,
                        distractors=distractors,
                        notes=(
                            "Gold is the same-indication medication active at "
                            "an unrelated clinical event; distractors are other "
                            "same-indication medications from different periods."
                        ),
                    ))
                    if max_tasks is not None and len(tasks) >= max_tasks:
                        return self._finalize_exp1a_tasks(tasks)
        return self._finalize_exp1a_tasks(tasks)

    def generate_recurring_condition_tasks(
        self,
        patients: list[str] | set[str] | None = None,
        *,
        max_tasks: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate repeated-episode condition tasks.

        This family uses acute or episodic conditions that recur for the same
        patient. The gold answer is the episode active on an encounter date,
        represented as a specific occurrence rather than only the condition
        name, because same-family distractors intentionally share the same
        description.

        Args:
            patients: Optional patient IDs to include.
            max_tasks: Optional cap for fixture-size control.

        Returns:
            Exp 1A task dictionaries for the ``recurring_condition`` family.
        """
        conditions_by_patient = self._load_conditions_by_patient()
        events_by_patient = self._load_events_by_patient()
        patient_filter = set(patients) if patients is not None else None
        tasks: list[dict[str, Any]] = []

        for patient_id in sorted(conditions_by_patient):
            if patient_filter is not None and patient_id not in patient_filter:
                continue
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in conditions_by_patient[patient_id]:
                family = self._condition_episode_family(row)
                if family:
                    grouped[family].append(self._condition_to_exp1a_entry(row, family))
            events = sorted(events_by_patient.get(patient_id, []), key=lambda item: item["date"] or "")
            for family, entries in grouped.items():
                if len(entries) < 2:
                    continue
                for event in events:
                    event_date = self._parse_exp1a_date(event.get("date"))
                    if event_date is None:
                        continue
                    active = [
                        entry for entry in entries
                        if self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], event_date)
                        and event["date"] not in {entry["valid_from"], entry["valid_to"]}
                    ]
                    if not active:
                        continue
                    gold = max(active, key=lambda item: item["valid_from"] or "")
                    distractors = [
                        entry for entry in entries
                        if entry["source_id"] != gold["source_id"]
                        and not self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], event_date)
                    ]
                    if not distractors:
                        continue
                    tasks.append(self._build_exp1a_task(
                        task_index=len(tasks),
                        family="recurring_condition",
                        category="temporal_recurring_condition",
                        patient_id=patient_id,
                        query=(
                            f"Which episode of {family} was active for patient "
                            f"{patient_id[:8]} on {event['date']}?"
                        ),
                        concept_family=family,
                        as_of_date=event["date"],
                        anchor_source="clinical_event",
                        anchor_event=event,
                        gold=gold,
                        distractors=distractors,
                        notes=(
                            "Gold is the condition episode active on an "
                            "encounter/procedure date; distractors are other "
                            "episodes of the same condition."
                        ),
                    ))
                    if max_tasks is not None and len(tasks) >= max_tasks:
                        return self._finalize_exp1a_tasks(tasks)
        return self._finalize_exp1a_tasks(tasks)

    def generate_dose_escalation_tasks(
        self,
        patients: list[str] | set[str] | None = None,
        *,
        max_tasks: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate same-drug dose-selection tasks.

        Dose-escalation tasks group prescriptions by an approximate drug name
        stripped of strength tokens. The gold answer is the dose-bearing
        prescription active at a calendar snapshot; distractors are the same
        drug with different strengths or formulations elsewhere in the
        timeline.

        Args:
            patients: Optional patient IDs to include.
            max_tasks: Optional cap for fixture-size control.

        Returns:
            Exp 1A task dictionaries for the ``dose_escalation`` family.
        """
        medications_by_patient = self._load_medications_by_patient()
        patient_filter = set(patients) if patients is not None else None
        tasks: list[dict[str, Any]] = []

        for patient_id in sorted(medications_by_patient):
            if patient_filter is not None and patient_id not in patient_filter:
                continue
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in medications_by_patient[patient_id]:
                drug_key = self._dose_drug_key(row.get("DESCRIPTION") or "")
                dose = self._extract_dose_text(row.get("DESCRIPTION") or "")
                if not drug_key or not dose:
                    continue
                grouped[drug_key].append(self._medication_to_exp1a_entry(row, drug_key, answer=dose))
            for drug_key, entries in grouped.items():
                entries = self._infer_sequential_medication_intervals(entries)
                distinct_answers = {entry["answer"] for entry in entries}
                if len(entries) < 2 or len(distinct_answers) < 2:
                    continue
                for as_of in _EXP1A_CALENDAR_SWEEP_DATES:
                    anchor = self._parse_exp1a_date(as_of)
                    active = [
                        entry for entry in entries
                        if self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], anchor)
                    ]
                    if not active:
                        continue
                    gold = max(active, key=lambda item: item["valid_from"] or "")
                    distractors = [
                        entry for entry in entries
                        if entry["source_id"] != gold["source_id"]
                        and not self._interval_contains(entry["valid_from_date"], entry["valid_to_date"], anchor)
                    ]
                    if not distractors:
                        continue
                    tasks.append(self._build_exp1a_task(
                        task_index=len(tasks),
                        family="dose_escalation",
                        category="temporal_dose_escalation",
                        patient_id=patient_id,
                        query=(
                            f"What dose of {drug_key} was patient "
                            f"{patient_id[:8]} on as of {as_of}?"
                        ),
                        concept_family=drug_key,
                        as_of_date=as_of,
                        anchor_source="calendar_sweep",
                        gold=gold,
                        distractors=distractors,
                        notes=(
                            "Gold is the active same-drug dose at the snapshot; "
                            "distractors are other doses/formulations of that "
                            "drug from different intervals."
                        ),
                    ))
                    if max_tasks is not None and len(tasks) >= max_tasks:
                        return self._finalize_exp1a_tasks(tasks)
        return self._finalize_exp1a_tasks(tasks)

    def generate_retrospective_state_tasks(
        self,
        patients: list[str] | set[str] | None = None,
        *,
        max_tasks: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate year-level medication state tasks.

        Retrospective-state tasks ask whether a patient was on a specific drug
        during a historical year. The gold answer is a deterministic yes/no
        state plus the overlapping intervals for positive examples; distractors
        are the same drug's intervals outside the requested year.

        Project role:
            This generator stays in ``qa_generator.py`` even after
            ``retrospective_state`` was removed from Exp 1A. Exp 1B's
            ``counterfactual_timing`` family reuses these fixtures as-is, so the
            implementation remains valuable even though Exp 1A no longer calls
            it from its corpus builder.

        Args:
            patients: Optional patient IDs to include.
            max_tasks: Optional cap for fixture-size control.

        Returns:
            Task dictionaries whose raw family label is
            ``retrospective_state``. Exp 1A excludes them; Exp 1B loads the
            saved fixture under its ``counterfactual_timing`` use case.
        """
        medications_by_patient = self._load_medications_by_patient()
        patient_filter = set(patients) if patients is not None else None
        tasks: list[dict[str, Any]] = []

        for patient_id in sorted(medications_by_patient):
            if patient_filter is not None and patient_id not in patient_filter:
                continue
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in medications_by_patient[patient_id]:
                drug_key = self._dose_drug_key(row.get("DESCRIPTION") or "")
                if drug_key:
                    grouped[drug_key].append(self._medication_to_exp1a_entry(row, drug_key))
            for drug_key, entries in grouped.items():
                entries = self._infer_sequential_medication_intervals(entries)
                if len(entries) < 2:
                    continue
                candidate_years = self._retrospective_candidate_years(entries)
                for year in candidate_years:
                    year_start = date(year, 1, 1)
                    year_end = date(year, 12, 31)
                    overlapping = [
                        entry for entry in entries
                        if self._intervals_overlap(
                            entry["valid_from_date"],
                            entry["valid_to_date"],
                            year_start,
                            year_end,
                        )
                    ]
                    outside = [
                        entry for entry in entries
                        if entry not in overlapping
                    ]
                    if not outside:
                        continue
                    answer = "yes" if overlapping else "no"
                    gold_source = overlapping[0] if overlapping else outside[0]
                    gold = dict(gold_source)
                    gold["description"] = answer
                    gold["answer"] = answer
                    gold["overlapping_entries"] = [
                        self._strip_exp1a_runtime_fields(entry) for entry in overlapping
                    ]
                    tasks.append(self._build_exp1a_task(
                        task_index=len(tasks),
                        family="retrospective_state",
                        category="temporal_retrospective_state",
                        patient_id=patient_id,
                        query=(
                            f"Was patient {patient_id[:8]} on {drug_key} "
                            f"during {year}?"
                        ),
                        concept_family=drug_key,
                        as_of_date=f"{year}-06-30",
                        anchor_source="calendar_sweep",
                        gold=gold,
                        distractors=outside,
                        notes=(
                            "Gold is the year-level yes/no medication state; "
                            "distractors are same-drug intervals outside the "
                            "requested year."
                        ),
                    ))
                    if max_tasks is not None and len(tasks) >= max_tasks:
                        return self._finalize_exp1a_tasks(tasks)
        return self._finalize_exp1a_tasks(tasks)

    # ------------------------------------------------------------------
    # Experiment 2: Multi-hop cohort queries
    # ------------------------------------------------------------------

    def generate_cohort_qa(
        self,
        condition_families: list[dict[str, Any]] | None = None,
        medication_families: list[dict[str, Any]] | None = None,
        observation_rules: list[dict[str, Any]] | None = None,
        *,
        min_patient_overlap: int = 25,
        min_provider_count: int = 5,
        min_lift: float = 1.15,
        max_pairs: int = 20,
        max_condition_observation_pairs: int = 30,
        max_pairs_per_condition: int = 3,
        max_pairs_per_medication: int = 2,
        max_pairs_per_observation: int = 3,
    ) -> list[dict[str, Any]]:
        """Generate the rebuilt multi-hop reasoning benchmark for Experiment 2.

        Why this generator changed:
            The earlier Experiment 2 benchmark depended on only a few hand-made
            condition/medication pairs, which made the evaluation too small and
            too easy to overfit mentally. The rebuilt version keeps the task
            format deterministic, but mines many more benchmarkable overlaps
            from the dataset while keeping the final query text clinically
            readable through curated concept families.

        What this generator emits:
            The rebuilt Exp 2 benchmark now draws from multiple multihop
            task families instead of only condition/medication overlap:
              - condition + medication
              - condition + abnormal latest observation

            For each selected overlap pair, create:
              - one patient-cohort task
              - one provider-attribution task

            That keeps the answer format deterministic while making the task
            bank more clinically interesting and better aligned with the
            graph + temporal memory story we actually want to test later.

        Args:
            condition_families: Curated family specs used to discover condition
                cohorts from the raw descriptions. Defaults to
                ``_DEFAULT_CONDITION_FAMILIES``.
            medication_families: Curated family specs used to discover
                medication cohorts. Defaults to
                ``_DEFAULT_MEDICATION_FAMILIES``.
            observation_rules: Curated latest-observation rules used to mine
                condition + abnormal-observation tasks. Defaults to
                ``_DEFAULT_OBSERVATION_RULES``.
            min_patient_overlap: Minimum patient overlap required for a pair to
                become a benchmark candidate.
            min_provider_count: Minimum provider set size required for the
                provider-attribution task.
            min_lift: Minimum observed-vs-expected association strength. This
                helps filter out clinically weak pairs that occur mostly due to
                broad comorbidity prevalence rather than a meaningful
                condition/medication relationship.
            max_pairs: Maximum number of mined condition/medication pairs to
                keep before expanding them into task variants.
            max_condition_observation_pairs: Maximum number of mined
                condition/observation pairs to keep before expanding them into
                task variants.
            max_pairs_per_condition: Diversity cap so one common condition does
                not dominate the whole benchmark.
            max_pairs_per_medication: Diversity cap so one common medication
                family does not dominate the whole benchmark.
            max_pairs_per_observation: Diversity cap so one common observation
                rule does not dominate the whole benchmark.

        Returns:
            List of task dicts matching the rebuilt Experiment 2 schema.
        """
        if condition_families is None:
            condition_families = _DEFAULT_CONDITION_FAMILIES
        if medication_families is None:
            medication_families = _DEFAULT_MEDICATION_FAMILIES
        if observation_rules is None:
            observation_rules = _DEFAULT_OBSERVATION_RULES

        condition_patients = self._load_condition_patients_by_code()
        medication_patients = self._load_medication_patients_by_code()
        encounter_providers = self._load_encounter_providers_by_patient()
        latest_observations = self._load_latest_numeric_observations_by_description()

        expanded_conditions = self._expand_family_matches(
            patients_by_description=condition_patients,
            families=condition_families,
        )
        expanded_medications = self._expand_family_matches(
            patients_by_description=medication_patients,
            families=medication_families,
        )
        expanded_observations = self._expand_observation_rule_matches(
            latest_observations_by_description=latest_observations,
            observation_rules=observation_rules,
        )
        selected_pairs = self._select_exp2_pairs(
            expanded_conditions=expanded_conditions,
            expanded_medications=expanded_medications,
            encounter_providers=encounter_providers,
            min_patient_overlap=min_patient_overlap,
            min_provider_count=min_provider_count,
            min_lift=min_lift,
            max_pairs=max_pairs,
            max_pairs_per_condition=max_pairs_per_condition,
            max_pairs_per_medication=max_pairs_per_medication,
        )
        selected_condition_observation_pairs = self._select_exp2_condition_observation_pairs(
            expanded_conditions=expanded_conditions,
            expanded_observations=expanded_observations,
            encounter_providers=encounter_providers,
            min_patient_overlap=min_patient_overlap,
            min_provider_count=min_provider_count,
            min_lift=max(min_lift, 1.0),
            max_pairs=max_condition_observation_pairs,
            max_pairs_per_condition=max_pairs_per_condition,
            max_pairs_per_observation=max_pairs_per_observation,
        )

        tasks: list[dict[str, Any]] = []
        task_idx = 0
        for pair in selected_pairs:
            pair_label = f"{pair['condition_family']}_{pair['medication_family']}"

            tasks.append({
                "id": f"EXP2-M{task_idx:04d}",
                "label": f"{pair_label}_patients",
                "category": "multihop_patient_cohort",
                "task_family": "condition_medication",
                "answer_entity": "patient",
                "query": (
                    f"Which patients have {pair['condition_display_name']} "
                    f"and are prescribed {pair['medication_display_name']}?"
                ),
                "condition_family": pair["condition_family"],
                "condition_description": pair["condition_display_name"],
                "condition_match_text": pair["condition_match_text"],
                "medication_family": pair["medication_family"],
                "medication_description": pair["medication_display_name"],
                "medication_match_text": pair["medication_match_text"],
                "ground_truth_ids": sorted(pair["matched_patients"]),
                "ground_truth_patient_ids": sorted(pair["matched_patients"]),
                "ground_truth_provider_ids": sorted(pair["provider_ids"]),
                "patient_count": len(pair["matched_patients"]),
                "provider_count": len(pair["provider_ids"]),
                "association_lift": pair["lift"],
                "matched_condition_descriptions": pair["matched_condition_descriptions"],
                "matched_medication_descriptions": pair["matched_medication_descriptions"],
                "notes": (
                    "Patient-cohort task mined from real condition/medication "
                    "family overlap in the corrected dataset."
                ),
            })
            task_idx += 1

            tasks.append({
                "id": f"EXP2-M{task_idx:04d}",
                "label": f"{pair_label}_providers",
                "category": "multihop_provider_attribution",
                "task_family": "condition_medication",
                "answer_entity": "provider",
                "query": (
                    f"Which providers treated patients who have "
                    f"{pair['condition_display_name']} and are prescribed "
                    f"{pair['medication_display_name']}?"
                ),
                "condition_family": pair["condition_family"],
                "condition_description": pair["condition_display_name"],
                "condition_match_text": pair["condition_match_text"],
                "medication_family": pair["medication_family"],
                "medication_description": pair["medication_display_name"],
                "medication_match_text": pair["medication_match_text"],
                "ground_truth_ids": sorted(pair["provider_ids"]),
                "ground_truth_patient_ids": sorted(pair["matched_patients"]),
                "ground_truth_provider_ids": sorted(pair["provider_ids"]),
                "patient_count": len(pair["matched_patients"]),
                "provider_count": len(pair["provider_ids"]),
                "association_lift": pair["lift"],
                "matched_condition_descriptions": pair["matched_condition_descriptions"],
                "matched_medication_descriptions": pair["matched_medication_descriptions"],
                "notes": (
                    "Provider-attribution task mined from the same overlap pair. "
                    "Ground truth is condition ∩ medication → encounter → provider."
                ),
            })
            task_idx += 1

        for pair in selected_condition_observation_pairs:
            pair_label = f"{pair['condition_family']}_{pair['observation_label']}"

            tasks.append({
                "id": f"EXP2-M{task_idx:04d}",
                "label": f"{pair_label}_patients",
                "category": "multihop_patient_cohort",
                "task_family": "condition_observation",
                "answer_entity": "patient",
                "query": (
                    f"Which patients have {pair['condition_display_name']} "
                    f"and also have {pair['observation_display_name']}?"
                ),
                "condition_family": pair["condition_family"],
                "condition_description": pair["condition_display_name"],
                "condition_match_text": pair["condition_match_text"],
                "observation_rule": pair["observation_label"],
                "observation_description": pair["observation_description"],
                "observation_display_name": pair["observation_display_name"],
                "observation_operator": pair["observation_operator"],
                "observation_threshold": pair["observation_threshold"],
                "ground_truth_ids": sorted(pair["matched_patients"]),
                "ground_truth_patient_ids": sorted(pair["matched_patients"]),
                "ground_truth_provider_ids": sorted(pair["provider_ids"]),
                "patient_count": len(pair["matched_patients"]),
                "provider_count": len(pair["provider_ids"]),
                "association_lift": pair["lift"],
                "matched_condition_descriptions": pair["matched_condition_descriptions"],
                "matched_observation_descriptions": pair["matched_observation_descriptions"],
                "notes": (
                    "Patient-cohort task mined from condition family overlap "
                    "with a patient's latest numeric observation rule."
                ),
            })
            task_idx += 1

            tasks.append({
                "id": f"EXP2-M{task_idx:04d}",
                "label": f"{pair_label}_providers",
                "category": "multihop_provider_attribution",
                "task_family": "condition_observation",
                "answer_entity": "provider",
                "query": (
                    f"Which providers treated patients who have "
                    f"{pair['condition_display_name']} and also have "
                    f"{pair['observation_display_name']}?"
                ),
                "condition_family": pair["condition_family"],
                "condition_description": pair["condition_display_name"],
                "condition_match_text": pair["condition_match_text"],
                "observation_rule": pair["observation_label"],
                "observation_description": pair["observation_description"],
                "observation_display_name": pair["observation_display_name"],
                "observation_operator": pair["observation_operator"],
                "observation_threshold": pair["observation_threshold"],
                "ground_truth_ids": sorted(pair["provider_ids"]),
                "ground_truth_patient_ids": sorted(pair["matched_patients"]),
                "ground_truth_provider_ids": sorted(pair["provider_ids"]),
                "patient_count": len(pair["matched_patients"]),
                "provider_count": len(pair["provider_ids"]),
                "association_lift": pair["lift"],
                "matched_condition_descriptions": pair["matched_condition_descriptions"],
                "matched_observation_descriptions": pair["matched_observation_descriptions"],
                "notes": (
                    "Provider-attribution task mined from condition family "
                    "overlap with a patient's latest numeric observation rule."
                ),
            })
            task_idx += 1

        logger.info(
            "Generated %d rebuilt Exp 2 tasks from %d condition/medication pairs and %d condition/observation pairs.",
            len(tasks),
            len(selected_pairs),
            len(selected_condition_observation_pairs),
        )
        return tasks

    def _expand_family_matches(
        self,
        *,
        patients_by_description: dict[str, set[str]],
        families: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Expand curated concept families into dataset-supported cohorts.

        The input tables are keyed by raw Synthea description strings, which
        are often more specific than we want the benchmark question text to be.
        This helper maps those raw descriptions into higher-level readable
        families like ``Hypertension`` or ``Metformin`` using substring
        matching, while still preserving which concrete source descriptions were
        matched for later debugging.
        """
        expanded: list[dict[str, Any]] = []
        for family in families:
            matched_patients: set[str] = set()
            matched_descriptions: list[dict[str, Any]] = []
            for description, patient_ids in patients_by_description.items():
                description_lower = description.lower()
                if any(term in description_lower for term in family["match_terms"]):
                    matched_patients.update(patient_ids)
                    matched_descriptions.append({
                        "description": description,
                        "patient_count": len(patient_ids),
                    })
            if not matched_patients:
                logger.info(
                    "Exp 2 family [%s] produced no dataset matches and will be skipped.",
                    family["label"],
                )
                continue
            matched_descriptions.sort(
                key=lambda item: (-item["patient_count"], item["description"])
            )
            expanded.append({
                "label": family["label"],
                "display_name": family["display_name"],
                "match_text": family["match_terms"][0],
                "patient_ids": matched_patients,
                "matched_descriptions": [
                    item["description"] for item in matched_descriptions[:5]
                ],
                "support_count": len(matched_patients),
            })
        expanded.sort(key=lambda item: (-item["support_count"], item["label"]))
        return expanded

    def _select_exp2_pairs(
        self,
        *,
        expanded_conditions: list[dict[str, Any]],
        expanded_medications: list[dict[str, Any]],
        encounter_providers: dict[str, set[str]],
        min_patient_overlap: int,
        min_provider_count: int,
        min_lift: float,
        max_pairs: int,
        max_pairs_per_condition: int,
        max_pairs_per_medication: int,
    ) -> list[dict[str, Any]]:
        """Select a diverse set of benchmarkable Exp 2 pairs.

        We do not want the rebuilt benchmark to be dominated by a single common
        family like hypertension. This selector therefore ranks candidate pairs
        by support, then applies simple diversity caps per condition and per
        medication family so the resulting task set covers more reasoning
        shapes.
        """
        total_patients = len({
            patient_id
            for condition in expanded_conditions
            for patient_id in condition["patient_ids"]
        } | {
            patient_id
            for medication in expanded_medications
            for patient_id in medication["patient_ids"]
        })
        candidate_pairs: list[dict[str, Any]] = []
        for condition in expanded_conditions:
            for medication in expanded_medications:
                allowed = medication.get("allowed_condition_families") or set()
                if allowed and condition["label"] not in allowed:
                    continue
                matched_patients = condition["patient_ids"] & medication["patient_ids"]
                if len(matched_patients) < min_patient_overlap:
                    continue
                expected_overlap = (
                    (condition["support_count"] * medication["support_count"]) / total_patients
                    if total_patients
                    else 0.0
                )
                lift = (
                    len(matched_patients) / expected_overlap
                    if expected_overlap > 0
                    else 0.0
                )
                if lift < min_lift:
                    continue
                provider_ids: set[str] = set()
                for patient_id in matched_patients:
                    provider_ids.update(encounter_providers.get(patient_id, set()))
                if len(provider_ids) < min_provider_count:
                    continue
                candidate_pairs.append({
                    "condition_family": condition["label"],
                    "condition_display_name": condition["display_name"],
                    "condition_match_text": condition["match_text"],
                    "matched_condition_descriptions": condition["matched_descriptions"],
                    "medication_family": medication["label"],
                    "medication_display_name": medication["display_name"],
                    "medication_match_text": medication["match_text"],
                    "matched_medication_descriptions": medication["matched_descriptions"],
                    "matched_patients": matched_patients,
                    "provider_ids": provider_ids,
                    "lift": lift,
                })

        candidate_pairs.sort(
            key=lambda item: (
                -item["lift"],
                -len(item["matched_patients"]),
                -len(item["provider_ids"]),
                item["condition_family"],
                item["medication_family"],
            )
        )

        selected: list[dict[str, Any]] = []
        condition_counts: dict[str, int] = defaultdict(int)
        medication_counts: dict[str, int] = defaultdict(int)
        for pair in candidate_pairs:
            if condition_counts[pair["condition_family"]] >= max_pairs_per_condition:
                continue
            if medication_counts[pair["medication_family"]] >= max_pairs_per_medication:
                continue
            selected.append(pair)
            condition_counts[pair["condition_family"]] += 1
            medication_counts[pair["medication_family"]] += 1
            logger.info(
                "Selected Exp 2 pair [%s + %s]: %d patients, %d providers, lift=%.2f.",
                pair["condition_family"],
                pair["medication_family"],
                len(pair["matched_patients"]),
                len(pair["provider_ids"]),
                pair["lift"],
            )
            if len(selected) >= max_pairs:
                break
        return selected

    def _select_exp2_condition_observation_pairs(
        self,
        *,
        expanded_conditions: list[dict[str, Any]],
        expanded_observations: list[dict[str, Any]],
        encounter_providers: dict[str, set[str]],
        min_patient_overlap: int,
        min_provider_count: int,
        min_lift: float,
        max_pairs: int,
        max_pairs_per_condition: int,
        max_pairs_per_observation: int,
    ) -> list[dict[str, Any]]:
        """Select benchmarkable condition + latest-observation pairs.

        Why use the patient's latest observation:
            For chronic-disease style tasks, "latest value is abnormal" is more
            defensible than "a value was ever abnormal at some point in the
            timeline." This keeps the label closer to what a clinician would
            care about during chart review or follow-up prioritization.
        """
        total_patients = len({
            patient_id
            for condition in expanded_conditions
            for patient_id in condition["patient_ids"]
        } | {
            patient_id
            for observation in expanded_observations
            for patient_id in observation["patient_ids"]
        })
        candidate_pairs: list[dict[str, Any]] = []
        for condition in expanded_conditions:
            for observation in expanded_observations:
                allowed = observation.get("allowed_condition_families") or set()
                if allowed and condition["label"] not in allowed:
                    continue
                matched_patients = condition["patient_ids"] & observation["patient_ids"]
                if len(matched_patients) < min_patient_overlap:
                    continue
                expected_overlap = (
                    (condition["support_count"] * observation["support_count"]) / total_patients
                    if total_patients
                    else 0.0
                )
                lift = (
                    len(matched_patients) / expected_overlap
                    if expected_overlap > 0
                    else 0.0
                )
                if lift < min_lift:
                    continue
                provider_ids: set[str] = set()
                for patient_id in matched_patients:
                    provider_ids.update(encounter_providers.get(patient_id, set()))
                if len(provider_ids) < min_provider_count:
                    continue
                candidate_pairs.append({
                    "condition_family": condition["label"],
                    "condition_display_name": condition["display_name"],
                    "condition_match_text": condition["match_text"],
                    "matched_condition_descriptions": condition["matched_descriptions"],
                    "observation_label": observation["label"],
                    "observation_description": observation["description"],
                    "observation_display_name": observation["display_name"],
                    "observation_operator": observation["operator"],
                    "observation_threshold": observation["threshold"],
                    "matched_observation_descriptions": observation["matched_descriptions"],
                    "matched_patients": matched_patients,
                    "provider_ids": provider_ids,
                    "lift": lift,
                })

        candidate_pairs.sort(
            key=lambda item: (
                -item["lift"],
                -len(item["matched_patients"]),
                -len(item["provider_ids"]),
                item["condition_family"],
                item["observation_label"],
            )
        )

        selected: list[dict[str, Any]] = []
        condition_counts: dict[str, int] = defaultdict(int)
        observation_counts: dict[str, int] = defaultdict(int)
        for pair in candidate_pairs:
            if condition_counts[pair["condition_family"]] >= max_pairs_per_condition:
                continue
            if observation_counts[pair["observation_label"]] >= max_pairs_per_observation:
                continue
            selected.append(pair)
            condition_counts[pair["condition_family"]] += 1
            observation_counts[pair["observation_label"]] += 1
            logger.info(
                "Selected Exp 2 condition/observation pair [%s + %s]: %d patients, %d providers, lift=%.2f.",
                pair["condition_family"],
                pair["observation_label"],
                len(pair["matched_patients"]),
                len(pair["provider_ids"]),
                pair["lift"],
            )
            if len(selected) >= max_pairs:
                break
        return selected

    def _expand_observation_rule_matches(
        self,
        *,
        latest_observations_by_description: dict[str, dict[str, dict[str, Any]]],
        observation_rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Expand observation rules into dataset-supported abnormal cohorts.

        Unlike the first pass of Exp 2, observation rules are not tied to one
        exact description string anymore. This keeps the benchmark resilient to
        minor wording drift in Synthea/FHIR exports while still producing a
        deterministic "latest abnormal observation" cohort for each rule.
        """
        expanded: list[dict[str, Any]] = []
        for rule in observation_rules:
            matched_patients: set[str] = set()
            matched_descriptions: list[dict[str, Any]] = []
            matched_rules = 0
            rule_match_terms = rule.get("match_terms") or [rule["description"]]
            for description, patients_by_id in latest_observations_by_description.items():
                description_lower = description.lower()
                if not any(term in description_lower for term in rule_match_terms):
                    continue
                abnormal_patient_ids = {
                    patient_id
                    for patient_id, observation in patients_by_id.items()
                    if self._observation_value_matches_rule(observation["numeric_value"], rule)
                }
                if not abnormal_patient_ids:
                    continue
                matched_rules += 1
                matched_patients.update(abnormal_patient_ids)
                matched_descriptions.append({
                    "description": description,
                    "patient_count": len(abnormal_patient_ids),
                })
            if not matched_patients:
                logger.info(
                    "Exp 2 observation rule [%s] produced no dataset matches and will be skipped.",
                    rule["label"],
                )
                continue
            matched_descriptions.sort(
                key=lambda item: (-item["patient_count"], item["description"])
            )
            expanded.append({
                "label": rule["label"],
                "description": rule["description"],
                "display_name": rule["display_name"],
                "operator": rule["operator"],
                "threshold": rule["threshold"],
                "allowed_condition_families": rule.get("allowed_condition_families") or set(),
                "patient_ids": matched_patients,
                "matched_descriptions": [
                    item["description"] for item in matched_descriptions[:5]
                ],
                "support_count": len(matched_patients),
                "matched_rule_descriptions": matched_rules,
            })
            logger.info(
                "Expanded Exp 2 observation rule [%s] across %d description variants with %d abnormal patients.",
                rule["label"],
                matched_rules,
                len(matched_patients),
            )
        expanded.sort(key=lambda item: (-item["support_count"], item["label"]))
        return expanded

    def _group_medications_by_family(
        self,
        medication_rows: list[dict[str, Any]],
        mapping: dict[str, str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group medication rows by a substring-derived clinical family.

        Exp 1A needs same-family distractors. The Synthea medication rows in
        the embedded export do not expose an ATC class column directly, so this
        helper applies a small deterministic term map supplied by
        ``concept_mappings.py`` and preserves the exact source description for
        scoring/debugging.
        """
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in medication_rows:
            description = row.get("DESCRIPTION") or ""
            family = self._lookup_exp1a_mapping(description, mapping)
            if not family:
                continue
            grouped[family].append(self._medication_to_exp1a_entry(row, family))
        return {
            family: self._infer_sequential_medication_intervals(entries)
            for family, entries in grouped.items()
        }

    def _infer_sequential_medication_intervals(
        self,
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Infer benchmark-valid stop dates for repeated medication rows.

        The embedded export often leaves medication ``STOP`` empty. If the same
        patient later receives another medication in the same benchmark family,
        Exp 1A treats that later start as superseding the previous open-ended
        row. This inference is deliberately local to task generation; it does
        not rewrite source data or claim clinical discontinuation.
        """
        deduped = self._dedupe_exp1a_entries(entries)
        deduped.sort(key=lambda item: (item["valid_from"] or "", item["description"], item["source_id"]))
        inferred: list[dict[str, Any]] = []
        for index, entry in enumerate(deduped):
            updated = dict(entry)
            next_start = None
            for candidate in deduped[index + 1:]:
                candidate_start = candidate.get("valid_from_date")
                if candidate_start and candidate_start != entry.get("valid_from_date"):
                    next_start = candidate_start
                    break
            if updated.get("valid_to_date") is None and next_start is not None:
                inferred_stop = next_start - timedelta(days=1)
                if updated.get("valid_from_date") and inferred_stop >= updated["valid_from_date"]:
                    updated["valid_to_date"] = inferred_stop
                    updated["valid_to"] = inferred_stop.isoformat()
            inferred.append(updated)
        return inferred

    @staticmethod
    def _dedupe_exp1a_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove exact duplicate source rows before building distractors."""
        by_id: dict[str, dict[str, Any]] = {}
        for entry in entries:
            by_id.setdefault(entry["source_id"], entry)
        return list(by_id.values())

    @staticmethod
    def _lookup_exp1a_mapping(description: str, mapping: dict[str, str]) -> str | None:
        """Return the mapped family for the longest matching description term."""
        description_lower = description.lower()
        matches = [
            (term, family)
            for term, family in mapping.items()
            if term.lower() in description_lower
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: (-len(item[0]), item[0]))
        return matches[0][1]

    def _medication_to_exp1a_entry(
        self,
        row: dict[str, Any],
        concept_family: str,
        *,
        answer: str | None = None,
    ) -> dict[str, Any]:
        """Convert one medication row into the interval shape used by Exp 1A."""
        valid_from = self._date_string(row.get("START"))
        valid_to = self._date_string(row.get("STOP"))
        description = row.get("DESCRIPTION") or ""
        return {
            "source_type": "medication",
            "source_id": row.get("Id") or self._stable_source_id(row),
            "description": description,
            "answer": answer or description,
            "code": row.get("CODE"),
            "concept_family": concept_family,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "valid_from_date": self._parse_exp1a_date(valid_from),
            "valid_to_date": self._parse_exp1a_date(valid_to),
        }

    def _condition_to_exp1a_entry(
        self,
        row: dict[str, Any],
        concept_family: str,
    ) -> dict[str, Any]:
        """Convert one condition row into a specific episode answer."""
        valid_from = self._date_string(row.get("START"))
        valid_to = self._date_string(row.get("STOP"))
        description = row.get("DESCRIPTION") or ""
        episode_answer = f"{description} episode starting {valid_from}"
        return {
            "source_type": "condition",
            "source_id": row.get("Id") or self._stable_source_id(row),
            "description": description,
            "answer": episode_answer,
            "code": row.get("CODE"),
            "concept_family": concept_family,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "valid_from_date": self._parse_exp1a_date(valid_from),
            "valid_to_date": self._parse_exp1a_date(valid_to),
        }

    @staticmethod
    def _stable_source_id(row: dict[str, Any]) -> str:
        """Build a deterministic row ID when the export row has no explicit ID."""
        parts = [
            str(row.get("record_type") or ""),
            str(row.get("PATIENT") or ""),
            str(row.get("START") or row.get("DATE") or ""),
            str(row.get("STOP") or ""),
            str(row.get("CODE") or ""),
            str(row.get("DESCRIPTION") or ""),
            str(row.get("ENCOUNTER") or ""),
        ]
        return "|".join(parts)

    def _condition_episode_family(self, row: dict[str, Any]) -> str | None:
        """Return a normalized recurring-condition family or ``None``.

        Chronic conditions are intentionally excluded here because the family
        is about repeated acute episodes. Chronic longitudinal state is handled
        by the medication-oriented supersession/regimen tasks.
        """
        description = (row.get("DESCRIPTION") or "").lower()
        if not description:
            return None
        if not row.get("STOP"):
            return None
        for term in _EXP1A_RECURRING_CONDITION_TERMS:
            if term in description:
                return term
        return None

    @staticmethod
    def _dose_drug_key(description: str) -> str | None:
        """Approximate a stable drug key by removing strength/form tokens."""
        cleaned = description.lower()
        cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
        cleaned = re.sub(r"\b\d+(\.\d+)?\s*(mg|ml|mcg|unt|actuat|hr|day|%)\b", " ", cleaned)
        cleaned = re.sub(r"\b\d+(\.\d+)?/\d+(\.\d+)?\b", " ", cleaned)
        cleaned = re.sub(r"\b(oral|tablet|injection|injectable|solution|suspension|extended|release|metered|dose|inhaler|prefilled|syringe|pack|day|topical|cream|chewable)\b", " ", cleaned)
        cleaned = re.sub(r"[^a-z]+", " ", cleaned).strip()
        tokens = [token for token in cleaned.split() if len(token) > 2]
        if not tokens:
            return None
        return " ".join(tokens[:4])

    @staticmethod
    def _extract_dose_text(description: str) -> str | None:
        """Extract the dose/formulation text that the dose task should answer."""
        matches = re.findall(
            r"\b\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?\s*(?:MG|ML|MCG|UNT|ACTUAT|HR|DAY|%)"
            r"(?:/\s*(?:ML|ACTUAT|HR|DAY))?\b",
            description,
            flags=re.IGNORECASE,
        )
        if not matches:
            return None
        return " / ".join(dict.fromkeys(match.strip() for match in matches))

    def _retrospective_candidate_years(self, entries: list[dict[str, Any]]) -> list[int]:
        """Pick deterministic positive and negative years for year-state tasks."""
        years: set[int] = set()
        for entry in entries:
            start = entry.get("valid_from_date")
            stop = entry.get("valid_to_date")
            if start is None:
                continue
            years.add(start.year)
            if stop is not None:
                years.add(stop.year)
                if stop.year > start.year:
                    years.add((start.year + stop.year) // 2)
            else:
                for snapshot in _EXP1A_CALENDAR_SWEEP_DATES:
                    snapshot_date = self._parse_exp1a_date(snapshot)
                    if snapshot_date and snapshot_date.year >= start.year:
                        years.add(snapshot_date.year)
        for snapshot in _EXP1A_CALENDAR_SWEEP_DATES:
            snapshot_date = self._parse_exp1a_date(snapshot)
            if snapshot_date:
                years.add(snapshot_date.year)
        return sorted(year for year in years if 1900 <= year <= 2026)

    def _build_exp1a_task(
        self,
        *,
        task_index: int,
        family: str,
        category: str,
        patient_id: str,
        query: str,
        concept_family: str,
        as_of_date: str,
        anchor_source: str,
        gold: dict[str, Any],
        distractors: list[dict[str, Any]],
        notes: str,
        anchor_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the shared task schema for all Exp 1A task families."""
        as_of = self._parse_exp1a_date(as_of_date)
        gold_public = self._strip_exp1a_runtime_fields(gold)
        distractor_public = [
            self._strip_exp1a_runtime_fields(item)
            for item in distractors
        ]
        return {
            "id": f"EXP1A-{family.upper().replace('_', '-')}-{task_index:05d}",
            "patient_id": patient_id,
            "category": category,
            "family": family,
            "query": query,
            "answer": gold.get("answer") or gold.get("description"),
            "ground_truth": gold.get("answer") or gold.get("description"),
            "as_of_date": as_of_date,
            "anchor_source": anchor_source,
            "anchor_event": anchor_event,
            "concept_family": concept_family,
            "gold": gold_public,
            "distractors": distractor_public,
            "candidate_count": 1 + len(distractor_public),
            "gold_interval_contains_as_of": self._interval_contains(
                gold.get("valid_from_date"),
                gold.get("valid_to_date"),
                as_of,
            ),
            "gold_anchor_is_boundary": as_of_date in {
                gold.get("valid_from"),
                gold.get("valid_to"),
            },
            "notes": notes,
        }

    @staticmethod
    def _strip_exp1a_runtime_fields(entry: dict[str, Any]) -> dict[str, Any]:
        """Remove Python date objects before writing task fixtures."""
        return {
            key: value
            for key, value in entry.items()
            if key not in {"valid_from_date", "valid_to_date"}
        }

    def _finalize_exp1a_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply deterministic sorting and sanity assertions to Exp 1A tasks."""
        tasks.sort(key=lambda item: (item["family"], item["patient_id"], item["as_of_date"], item["id"]))
        for index, task in enumerate(tasks):
            task["id"] = f"EXP1A-{task['family'].upper().replace('_', '-')}-{index:05d}"
            if not task.get("distractors"):
                raise ValueError(f"Exp 1A task has no distractors: {task['id']}")
        boundary_safe = [
            task for task in tasks
            if task["family"] in {"supersession", "regimen_change"}
            and not task.get("gold_anchor_is_boundary")
        ]
        target_family_count = sum(
            1 for task in tasks
            if task["family"] in {"supersession", "regimen_change"}
        )
        if target_family_count and len(boundary_safe) / target_family_count < 0.40:
            raise ValueError(
                "Exp 1A supersession/regimen tasks do not meet the 40% "
                "non-boundary anchor requirement from DESIGN.md."
            )
        return tasks

    @staticmethod
    def _date_string(value: Any) -> str | None:
        """Normalize an export date/datetime value to YYYY-MM-DD text."""
        if value in (None, ""):
            return None
        return str(value)[:10]

    @staticmethod
    def _parse_exp1a_date(value: Any) -> date | None:
        """Parse a YYYY-MM-DD value while tolerating missing export fields."""
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    @staticmethod
    def _interval_contains(
        valid_from: date | None,
        valid_to: date | None,
        anchor: date | None,
    ) -> bool:
        """Return whether a closed/open-ended interval contains an anchor."""
        if valid_from is None or anchor is None:
            return False
        return valid_from <= anchor and (valid_to is None or valid_to >= anchor)

    @staticmethod
    def _intervals_overlap(
        left_start: date | None,
        left_end: date | None,
        right_start: date,
        right_end: date,
    ) -> bool:
        """Return whether two closed intervals overlap."""
        if left_start is None:
            return False
        effective_left_end = left_end or date(9999, 12, 31)
        return left_start <= right_end and effective_left_end >= right_start

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
        events_by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        latest_numeric_observations_by_desc: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        scanned_rows = 0
        chunk_paths = sorted(self._dir.glob("chunk-*.jsonl.gz"))

        for chunk_index, chunk_path in enumerate(chunk_paths, start=1):
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
                        event_date = row.get("START")
                        if patient_id and event_date:
                            events_by_patient[patient_id].append({
                                "date": self._date_string(event_date),
                                "description": row.get("DESCRIPTION") or row.get("CLASS") or "encounter",
                                "type": "encounter",
                                "class": row.get("CLASS"),
                                "source_id": row.get("Id") or self._stable_source_id(row),
                            })
                        if patient_id and provider_id:
                            encounter_providers_by_patient[patient_id].add(provider_id)
                    elif record_type == "procedure":
                        patient_id = row.get("PATIENT") or ""
                        event_date = row.get("DATE")
                        if patient_id and event_date:
                            events_by_patient[patient_id].append({
                                "date": self._date_string(event_date),
                                "description": row.get("DESCRIPTION") or "procedure",
                                "type": "procedure",
                                "class": None,
                                "source_id": row.get("Id") or self._stable_source_id(row),
                            })
                    elif record_type == "observation":
                        patient_id = row.get("PATIENT") or ""
                        description = row.get("DESCRIPTION") or ""
                        date_str = row.get("DATE") or ""
                        numeric_value = self._parse_numeric_value(row.get("VALUE"))
                        if patient_id and description and numeric_value is not None:
                            current = latest_numeric_observations_by_desc[description].get(patient_id)
                            if current is None or date_str > current["DATE"]:
                                latest_numeric_observations_by_desc[description][patient_id] = {
                                    "DATE": date_str,
                                    "numeric_value": numeric_value,
                                    "UNITS": row.get("UNITS"),
                                    "TYPE": row.get("TYPE"),
                                }
            if chunk_index == 1 or chunk_index % 10 == 0 or chunk_index == len(chunk_paths):
                logger.info(
                    "Embedded-export QA scan progress: chunk %d/%d, rows=%d, conditions=%d, medications=%d, encounters=%d, observation_descriptions=%d.",
                    chunk_index,
                    len(chunk_paths),
                    scanned_rows,
                    len(condition_patients_by_desc),
                    len(medication_patients_by_desc),
                    len(encounter_providers_by_patient),
                    len(latest_numeric_observations_by_desc),
                )

        self._embedded_indexes = {
            "conditions_by_patient": dict(conditions_by_patient),
            "medications_by_patient": dict(medications_by_patient),
            "condition_patients_by_desc": dict(condition_patients_by_desc),
            "medication_patients_by_desc": dict(medication_patients_by_desc),
            "encounter_providers_by_patient": dict(encounter_providers_by_patient),
            "events_by_patient": {
                patient_id: sorted(events, key=lambda item: item["date"] or "")
                for patient_id, events in events_by_patient.items()
            },
            "latest_numeric_observations_by_desc": {
                description: dict(patient_map)
                for description, patient_map in latest_numeric_observations_by_desc.items()
            },
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

    def _load_events_by_patient(self) -> dict[str, list[dict[str, Any]]]:
        """Load encounter/procedure anchors keyed by patient.

        Exp 1A uses these anchors for clinical-event tasks so the query date is
        not copied from the answer fact itself. Encounters and procedures are
        both useful because Synthea has sparse inpatient events for many
        patients but richer procedure dates around medication reviews.
        """
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["events_by_patient"]
        events_by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._iter_records_of_type("encounter"):
            patient_id = row.get("PATIENT") or ""
            event_date = self._date_string(row.get("START"))
            if patient_id and event_date:
                events_by_patient[patient_id].append({
                    "date": event_date,
                    "description": row.get("DESCRIPTION") or row.get("CLASS") or "encounter",
                    "type": "encounter",
                    "class": row.get("CLASS"),
                    "source_id": row.get("Id") or self._stable_source_id(row),
                })
        for row in self._iter_records_of_type("procedure"):
            patient_id = row.get("PATIENT") or ""
            event_date = self._date_string(row.get("DATE"))
            if patient_id and event_date:
                events_by_patient[patient_id].append({
                    "date": event_date,
                    "description": row.get("DESCRIPTION") or "procedure",
                    "type": "procedure",
                    "class": None,
                    "source_id": row.get("Id") or self._stable_source_id(row),
                })
        return {
            patient_id: sorted(events, key=lambda item: item["date"] or "")
            for patient_id, events in events_by_patient.items()
        }

    def _load_latest_numeric_observations_by_description(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Load latest numeric observations keyed by description then patient.

        Returns:
            Mapping:
                {
                    observation_description: {
                        patient_id: {
                            "DATE": "...",
                            "numeric_value": 7.2,
                            "UNITS": "%",
                            "TYPE": "numeric",
                        }
                    }
                }
        """
        if self._is_embedded_export:
            indexes = self._ensure_embedded_indexes()
            return indexes["latest_numeric_observations_by_desc"]
        by_description: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in self._iter_records_of_type("observation"):
            patient_id = row.get("PATIENT") or ""
            description = row.get("DESCRIPTION") or ""
            date_str = row.get("DATE") or ""
            numeric_value = self._parse_numeric_value(row.get("VALUE"))
            if not patient_id or not description or numeric_value is None:
                continue
            current = by_description[description].get(patient_id)
            if current is None or date_str > current["DATE"]:
                by_description[description][patient_id] = {
                    "DATE": date_str,
                    "numeric_value": numeric_value,
                    "UNITS": row.get("UNITS"),
                    "TYPE": row.get("TYPE"),
                }
        return {description: dict(patients) for description, patients in by_description.items()}

    @staticmethod
    def _parse_numeric_value(value: Any) -> float | None:
        """Parse a numeric observation value from the export row."""
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _observation_value_matches_rule(numeric_value: float, rule: dict[str, Any]) -> bool:
        """Return True when a numeric observation satisfies a rule threshold."""
        operator = rule["operator"]
        threshold = float(rule["threshold"])
        if operator == ">":
            return numeric_value > threshold
        if operator == ">=":
            return numeric_value >= threshold
        if operator == "<":
            return numeric_value < threshold
        if operator == "<=":
            return numeric_value <= threshold
        raise ValueError(f"Unsupported observation operator: {operator}")
