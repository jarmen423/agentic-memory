"""Focused unit tests for the Synthea FHIR loader's STU3 edge cases.

These tests cover the exact bundle shapes that caused the fast healthcare
import to look "correct" structurally while silently dropping two important
semantic paths:

- encounter providers were present on ``serviceProvider`` instead of
  ``participant[].individual``
- medication meaning lived on preceding ``Medication`` resources while the
  following ``MedicationRequest`` rows had blank medication fields

The production loader needs to normalize both shapes into the CSV-like rows
that the healthcare ingestion pipeline expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.healthcare.fhir_loader import SyntheaFHIRLoader


pytestmark = [pytest.mark.unit]


def _loader() -> SyntheaFHIRLoader:
    """Return a loader instance for calling internal bundle parsers in tests."""
    return SyntheaFHIRLoader(Path("unused-fixture-path"))


def test_parse_bundle_uses_service_provider_and_medication_side_channel():
    """Recover provider and medication fields from the STU3 bundle shape.

    The real 1M STU3 export stores encounter provider information on
    ``serviceProvider`` and often pairs a standalone ``Medication`` resource
    with a later ``MedicationRequest`` whose own medication fields are blank.
    """

    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "patient-1",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "enc-1",
                    "period": {
                        "start": "2011-11-21T20:56:12-05:00",
                        "end": "2011-11-21T21:56:12-05:00",
                    },
                    "serviceProvider": {"reference": "urn:uuid:provider-1"},
                    "type": [
                        {
                            "coding": [{"code": "170258001"}],
                            "text": "Outpatient Encounter",
                        }
                    ],
                    "class": {"code": "outpatient"},
                }
            },
            {
                "resource": {
                    "resourceType": "Medication",
                    "code": {
                        "coding": [
                            {
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                "code": "198405",
                                "display": "Ibuprofen 100 MG Oral Tablet",
                            }
                        ],
                        "text": "Ibuprofen 100 MG Oral Tablet",
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "authoredOn": "2013-12-23",
                    "context": {"reference": "urn:uuid:enc-1"},
                    "medicationReference": {"reference": ""},
                    "status": "stopped",
                    "subject": {"reference": "urn:uuid:patient-1"},
                }
            },
        ],
    }

    rows = _loader()._parse_bundle(bundle)

    encounter_row = next(row for row in rows if row["record_type"] == "encounter")
    medication_row = next(row for row in rows if row["record_type"] == "medication")

    assert encounter_row["PROVIDER"] == "provider-1"
    assert encounter_row["DESCRIPTION"] == "Outpatient Encounter"
    assert medication_row["CODE"] == "198405"
    assert medication_row["DESCRIPTION"] == "Ibuprofen 100 MG Oral Tablet"
    assert medication_row["ENCOUNTER"] == "enc-1"


def test_parse_bundle_reuses_latest_medication_for_multiple_requests():
    """Keep using the latest bundle medication until a newer one appears.

    The STU3 export can emit one ``Medication`` resource followed by multiple
    ``MedicationRequest`` resources. Later the bundle may switch to a new
    medication resource and reuse that one for subsequent requests.
    """

    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "patient-1"}},
            {"resource": {"resourceType": "Encounter", "id": "enc-1", "class": {"code": "outpatient"}}},
            {
                "resource": {
                    "resourceType": "Medication",
                    "code": {
                        "coding": [
                            {
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                "code": "111",
                                "display": "Medication One",
                            }
                        ]
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "authoredOn": "2013-12-23",
                    "context": {"reference": "urn:uuid:enc-1"},
                    "status": "stopped",
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "authoredOn": "2013-12-24",
                    "context": {"reference": "urn:uuid:enc-1"},
                    "status": "stopped",
                }
            },
            {
                "resource": {
                    "resourceType": "Medication",
                    "code": {
                        "coding": [
                            {
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                "code": "222",
                                "display": "Medication Two",
                            }
                        ]
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "authoredOn": "2013-12-25",
                    "context": {"reference": "urn:uuid:enc-1"},
                    "status": "stopped",
                }
            },
        ],
    }

    rows = _loader()._parse_bundle(bundle)
    medication_rows = [row for row in rows if row["record_type"] == "medication"]

    assert [row["CODE"] for row in medication_rows] == ["111", "111", "222"]
    assert [row["DESCRIPTION"] for row in medication_rows] == [
        "Medication One",
        "Medication One",
        "Medication Two",
    ]
