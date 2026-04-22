"""Schema validation for Exp 1A task fixtures.

The experiment runner needs task JSON that is stable enough to score across
many retrieval arms. This module keeps the validation dependency-free: it
defines a JSON-Schema-shaped dictionary for documentation and a small Python
validator used by the generator CLI. The validator checks the fields the
runner depends on and leaves room for family-specific diagnostic metadata.
"""

from __future__ import annotations

from typing import Any

EXP1A_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "patient_id",
        "category",
        "family",
        "query",
        "answer",
        "as_of_date",
        "anchor_source",
        "concept_family",
        "gold",
        "distractors",
    ],
    "properties": {
        "id": {"type": "string"},
        "patient_id": {"type": "string"},
        "category": {"type": "string"},
        "family": {"type": "string"},
        "query": {"type": "string"},
        "answer": {"type": "string"},
        "as_of_date": {"type": "string"},
        "anchor_source": {"enum": ["calendar_sweep", "clinical_event"]},
        "concept_family": {"type": "string"},
        "gold": {"type": "object"},
        "distractors": {"type": "array", "minItems": 1},
    },
}


def validate_exp1a_task(task: dict[str, Any]) -> None:
    """Validate one Exp 1A task dict.

    Args:
        task: Task dictionary produced by ``SyntheaQAGenerator``.

    Raises:
        ValueError: If a required runner-facing field is missing or malformed.
    """
    for field in EXP1A_TASK_SCHEMA["required"]:
        if field not in task:
            raise ValueError(f"Exp 1A task {task.get('id', '<unknown>')} is missing {field!r}")
    if task["anchor_source"] not in {"calendar_sweep", "clinical_event"}:
        raise ValueError(f"Invalid anchor_source for {task['id']}: {task['anchor_source']}")
    if not isinstance(task["distractors"], list) or not task["distractors"]:
        raise ValueError(f"Exp 1A task {task['id']} must have at least one distractor")
    _validate_interval_payload(task["id"], "gold", task["gold"])
    for index, distractor in enumerate(task["distractors"]):
        _validate_interval_payload(task["id"], f"distractors[{index}]", distractor)


def _validate_interval_payload(task_id: str, label: str, payload: dict[str, Any]) -> None:
    """Validate the source interval object nested under gold/distractors."""
    for field in ["source_type", "source_id", "description", "answer", "concept_family", "valid_from"]:
        if field not in payload:
            raise ValueError(f"Exp 1A task {task_id} {label} is missing {field!r}")
