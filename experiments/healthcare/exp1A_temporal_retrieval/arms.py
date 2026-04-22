"""Retrieval arms for Exp 1A's temporal-ranking benchmark.

Exp 1A is intentionally narrower than the full product. These arms are small,
inspectable retrieval policies that all answer the same task schema so Phase 5
can compare them cell-by-cell. The benchmark needs both:

- trivial local baselines that operate only on the task's gold+distractor set
- bridge-backed policies that exercise the temporal graph with different
  filtering rules

This module keeps both surfaces behind one candidate model and one abstract
``retrieve`` interface so the later sweep runner does not need special cases.
"""

from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from experiments.healthcare.exp1A_temporal_retrieval.concept_mappings import (
    ATC_CLASS_MAP,
    INDICATION_MAP,
)

try:
    from agentic_memory.temporal.bridge import TemporalBridge
except Exception:  # noqa: BLE001
    TemporalBridge = Any  # type: ignore[misc,assignment]


REPO_ROOT = Path(__file__).resolve().parents[3]
MEDICATION_PREDICATES = {"PRESCRIBED"}
CONDITION_PREDICATES = {"DIAGNOSED_WITH", "HAS_CONDITION"}


@dataclass(frozen=True)
class Candidate:
    """Normalized ranking candidate returned by any Exp 1A arm.

    Attributes:
        description: Human-readable object description from the task fixture or
            bridge row.
        answer: The exact answer string this candidate should be scored on.
            This can differ from ``description`` for dose and recurring
            condition tasks.
        valid_from: Inclusive interval start in ISO date format.
        valid_to: Inclusive interval end in ISO date format, or ``None`` for
            open-ended intervals.
        score: Ranking score emitted by the arm. For local baselines this is a
            deterministic heuristic score; for bridge-backed arms it is the
            retrieved row's score/rank proxy.
        concept_family: Same-family label used by Exp 1A tasks.
        source_id: Stable row identifier when one is available.
        predicate: Temporal predicate that produced the candidate.
        source_type: ``medication`` or ``condition`` for task-native rows.
        raw: Original source payload kept for debugging and Phase 5 result
            export.
    """

    description: str
    answer: str
    valid_from: str | None
    valid_to: str | None
    score: float
    concept_family: str | None
    source_id: str | None = None
    predicate: str | None = None
    source_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


class BaseArm(ABC):
    """Shared interface for every Exp 1A retrieval policy."""

    arm_name: str = "base"

    def __init__(
        self,
        *,
        project_id: str = "synthea-scale-mid-fhirfix",
        bridge: TemporalBridge | None = None,
        rng: random.Random | None = None,
    ) -> None:
        """Store shared runtime dependencies for one arm instance.

        Args:
            project_id: Temporal graph namespace for bridge-backed arms.
            bridge: Optional injected ``TemporalBridge``. Local-only arms do
                not require it.
            rng: Optional random number generator so smoke scripts can control
                sampling while preserving the "random floor" behavior.
        """
        self.project_id = project_id
        self.bridge = bridge
        self.rng = rng or random.Random()

    @abstractmethod
    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Return the ranked candidates for one Exp 1A task."""

    def _task_candidates(self, task: dict[str, Any]) -> list[Candidate]:
        """Normalize task-native gold+distractor rows into ``Candidate`` objects."""
        rows = [task["gold"], *task.get("distractors", [])]
        return [self._task_row_to_candidate(task, row) for row in rows]

    def _task_row_to_candidate(
        self,
        task: dict[str, Any],
        row: dict[str, Any],
    ) -> Candidate:
        """Convert one task fixture row into the shared candidate model."""
        return Candidate(
            description=row.get("description") or "",
            answer=row.get("answer") or row.get("description") or "",
            valid_from=row.get("valid_from"),
            valid_to=row.get("valid_to"),
            score=0.0,
            concept_family=row.get("concept_family") or task.get("concept_family"),
            source_id=row.get("source_id"),
            predicate=self._task_predicate(task),
            source_type=row.get("source_type"),
            raw=dict(row),
        )

    def _task_predicate(self, task: dict[str, Any]) -> str:
        """Return the expected temporal predicate for a task family."""
        if task.get("family") == "recurring_condition":
            return "DIAGNOSED_WITH"
        return "PRESCRIBED"

    def _bridge_candidates(
        self,
        task: dict[str, Any],
        *,
        k: int,
        half_life: float,
        max_hops: int,
        filter_family: bool,
        require_overlap: bool,
    ) -> list[Candidate]:
        """Run ``TemporalBridge.retrieve`` and normalize the returned rows.

        Args:
            task: One Exp 1A task.
            k: Requested output size.
            half_life: Temporal half-life in hours.
            max_hops: Retrieval neighborhood depth. ``1`` approximates the
                patient-scoped arms; ``2`` approximates the broader soft-decay
                path used by the product.
            filter_family: Whether to drop out-of-family rows.
            require_overlap: Whether to drop rows whose interval does not
                overlap the task's ``as_of_date``.

        Returns:
            Ranked and de-duplicated candidates in the shared candidate model.
        """
        if self.bridge is None:
            self.bridge = TemporalBridge.from_env()
        if not self.bridge.is_available():
            raise RuntimeError(f"Temporal bridge unavailable: {self.bridge.disabled_reason}")

        response = self.bridge.retrieve(
            project_id=self.project_id,
            seed_entities=[{"kind": "patient", "name": task["patient_id"]}],
            as_of_us=_date_to_micros(task["as_of_date"]),
            half_life_hours=half_life,
            # The bridge truncates before Python-side family/overlap filters.
            # Exp 1A therefore needs a much wider raw window than the final
            # top-K so the soft-decay arms do not accidentally drop all usable
            # candidates on noisy patient neighborhoods.
            max_edges=max(k * 50, 250),
            max_hops=max_hops,
        )

        seen: set[tuple[str, str | None, str | None]] = set()
        candidates: list[Candidate] = []
        for index, row in enumerate(response.get("results", []), start=1):
            if row.get("predicate") not in self._allowed_predicates(task):
                continue
            candidate = self._bridge_row_to_candidate(task, row, rank=index)
            if candidate is None:
                continue
            if filter_family and not self._candidate_matches_task_family(task, candidate):
                continue
            if require_overlap and not _interval_overlaps(candidate.valid_from, candidate.valid_to, task["as_of_date"]):
                continue
            identity = (candidate.answer, candidate.valid_from, candidate.valid_to)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(candidate)
            if len(candidates) >= k:
                break
        return candidates

    def _bridge_row_to_candidate(
        self,
        task: dict[str, Any],
        row: dict[str, Any],
        *,
        rank: int,
    ) -> Candidate | None:
        """Map one bridge retrieval row into the Exp 1A candidate model."""
        object_payload = row.get("object") or {}
        description = object_payload.get("name") or ""
        if not description:
            return None
        valid_from = _micros_to_date_text(row.get("validFromUs"))
        valid_to = _micros_to_date_text(row.get("validToUs"))
        answer = _candidate_answer_for_task(task, description, valid_from)
        concept_family = _candidate_family_for_task(task, description)
        raw_score = row.get("score")
        score = float(raw_score) if raw_score is not None else (1.0 / rank)
        return Candidate(
            description=description,
            answer=answer,
            valid_from=valid_from,
            valid_to=valid_to,
            score=score,
            concept_family=concept_family,
            source_id=str(row.get("edgeId") or ""),
            predicate=row.get("predicate"),
            source_type="bridge",
            raw=dict(row),
        )

    def _allowed_predicates(self, task: dict[str, Any]) -> set[str]:
        """Return the predicate set that a task family should read from."""
        if task.get("family") == "recurring_condition":
            return CONDITION_PREDICATES
        return MEDICATION_PREDICATES

    def _candidate_matches_task_family(
        self,
        task: dict[str, Any],
        candidate: Candidate,
    ) -> bool:
        """Return whether a candidate belongs to the task's same-family pool."""
        return candidate.concept_family == task.get("concept_family")


class RandomInFamilyArm(BaseArm):
    """Arm 1 from DESIGN.md: random floor over same-family task candidates."""

    arm_name = "random_in_family"

    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Shuffle the task's same-family candidates and return the top-K."""
        del half_life
        candidates = self._task_candidates(task)
        shuffled = list(candidates)
        self.rng.shuffle(shuffled)
        return shuffled[:k]


class AlwaysNewestArm(BaseArm):
    """Arm 2 from DESIGN.md: pick the newest interval regardless of ``as_of``."""

    arm_name = "always_newest"

    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Sort task-native candidates by newest start date first."""
        del half_life
        candidates = self._task_candidates(task)
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                _sortable_date(candidate.valid_from),
                candidate.valid_to or "9999-12-31",
                candidate.answer,
            ),
            reverse=True,
        )
        return ranked[:k]


class HardOverlapArm(BaseArm):
    """Arm 3 from DESIGN.md: same-family overlap filter with random tiebreak."""

    arm_name = "hard_overlap"

    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Return only task-native candidates whose interval overlaps ``as_of``."""
        del half_life
        overlapping = [
            candidate
            for candidate in self._task_candidates(task)
            if _interval_overlaps(candidate.valid_from, candidate.valid_to, task["as_of_date"])
        ]
        self.rng.shuffle(overlapping)
        return overlapping[:k]


class HardOverlapDecayTiebreakArm(BaseArm):
    """Arm 4 from DESIGN.md: patient-scoped bridge retrieval plus overlap gate.

    This arm approximates the "same as arm 3, but decay breaks ties" design by
    keeping retrieval patient-scoped (``max_hops=1``) while letting the bridge
    score rows before the Python-side hard-overlap filter is applied.
    """

    arm_name = "hard_overlap_decay_tiebreak"

    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Return same-family overlapping bridge candidates ranked by bridge score."""
        return self._bridge_candidates(
            task,
            k=k,
            half_life=half_life,
            max_hops=1,
            filter_family=True,
            require_overlap=True,
        )


class SoftDecayOnlyArm(BaseArm):
    """Arm 5 from DESIGN.md: raw bridge ranking with only predicate filtering.

    This is the closest match to the original temporal-retrieval mechanism. It
    allows family noise and non-overlapping intervals to survive so the later
    metrics can show whether decay alone is sufficient.
    """

    arm_name = "soft_decay_only"

    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Return bridge-ranked candidates without family or overlap filtering.

        The wider ``max_hops=2`` retrieval is the intended primary path. Some
        patient/task combinations on the current healthcare graph still starve
        out all matching predicates after ranking truncation, so this arm falls
        back to a patient-scoped bridge call only when the broader call yields
        zero usable candidates.
        """
        candidates = self._bridge_candidates(
            task,
            k=k,
            half_life=half_life,
            max_hops=2,
            filter_family=False,
            require_overlap=False,
        )
        if candidates:
            return candidates
        return self._bridge_candidates(
            task,
            k=k,
            half_life=half_life,
            max_hops=1,
            filter_family=False,
            require_overlap=False,
        )


class SoftDecayHardOverlapArm(BaseArm):
    """Arm 6 from DESIGN.md: target configuration with bridge decay + overlap.

    This is the benchmark's intended production-shape arm: run the broader
    bridge retrieval, then enforce the benchmark's same-family and overlap
    contract in Python before scoring.
    """

    arm_name = "soft_decay_hard_overlap"

    def retrieve(
        self,
        task: dict[str, Any],
        k: int,
        half_life: float,
    ) -> list[Candidate]:
        """Return bridge-ranked candidates after family and overlap filtering.

        Like ``SoftDecayOnlyArm``, this arm prefers the broader ``max_hops=2``
        retrieval. It retries with ``max_hops=1`` only when the broader bridge
        call leaves no same-family overlapping candidates at all.
        """
        candidates = self._bridge_candidates(
            task,
            k=k,
            half_life=half_life,
            max_hops=2,
            filter_family=True,
            require_overlap=True,
        )
        if candidates:
            return candidates
        return self._bridge_candidates(
            task,
            k=k,
            half_life=half_life,
            max_hops=1,
            filter_family=True,
            require_overlap=True,
        )


def build_phase4_arms(
    *,
    project_id: str = "synthea-scale-mid-fhirfix",
    bridge: TemporalBridge | None = None,
    seed: int = 42,
) -> list[BaseArm]:
    """Create one instance of every Exp 1A Phase 4 arm.

    Args:
        project_id: Temporal graph namespace for bridge-backed arms.
        bridge: Optional shared bridge instance.
        seed: Base seed for deterministic smoke sampling while leaving each arm
            with its own RNG stream.

    Returns:
        The six Phase 4 arm instances in design-table order.
    """
    return [
        RandomInFamilyArm(project_id=project_id, bridge=bridge, rng=random.Random(seed + 1)),
        AlwaysNewestArm(project_id=project_id, bridge=bridge, rng=random.Random(seed + 2)),
        HardOverlapArm(project_id=project_id, bridge=bridge, rng=random.Random(seed + 3)),
        HardOverlapDecayTiebreakArm(project_id=project_id, bridge=bridge, rng=random.Random(seed + 4)),
        SoftDecayOnlyArm(project_id=project_id, bridge=bridge, rng=random.Random(seed + 5)),
        SoftDecayHardOverlapArm(project_id=project_id, bridge=bridge, rng=random.Random(seed + 6)),
    ]


def _candidate_family_for_task(task: dict[str, Any], description: str) -> str | None:
    """Resolve the candidate's family label using the active task family rules."""
    family = task.get("family")
    if family == "supersession":
        return _lookup_mapping(description, ATC_CLASS_MAP)
    if family == "regimen_change":
        return _lookup_mapping(description, INDICATION_MAP)
    if family == "recurring_condition":
        description_lower = description.lower()
        target = str(task.get("concept_family") or "").lower()
        return task.get("concept_family") if target and target in description_lower else None
    if family == "dose_escalation":
        return _dose_drug_key(description)
    return None


def _candidate_answer_for_task(
    task: dict[str, Any],
    description: str,
    valid_from: str | None,
) -> str:
    """Map one description row into the exact answer shape scored by Exp 1A."""
    family = task.get("family")
    if family == "recurring_condition":
        return f"{description} episode starting {valid_from}"
    if family == "dose_escalation":
        return _extract_dose_text(description) or description
    return description


def _lookup_mapping(description: str, mapping: dict[str, str]) -> str | None:
    """Return the longest matching substring-family mapping."""
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


def _dose_drug_key(description: str) -> str | None:
    """Approximate the stable dose family used by Exp 1A's generator."""
    cleaned = description.lower()
    cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
    cleaned = re.sub(r"\b\d+(\.\d+)?\s*(mg|ml|mcg|unt|actuat|hr|day|%)\b", " ", cleaned)
    cleaned = re.sub(r"\b\d+(\.\d+)?/\d+(\.\d+)?\b", " ", cleaned)
    cleaned = re.sub(
        r"\b(oral|tablet|injection|injectable|solution|suspension|extended|release|metered|dose|inhaler|prefilled|syringe|pack|day|topical|cream|chewable)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"[^a-z]+", " ", cleaned).strip()
    tokens = [token for token in cleaned.split() if len(token) > 2]
    if not tokens:
        return None
    return " ".join(tokens[:4])


def _extract_dose_text(description: str) -> str | None:
    """Extract the dose/formulation text the dose-escalation tasks answer on."""
    matches = re.findall(
        r"\b\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?\s*(?:MG|ML|MCG|UNT|ACTUAT|HR|DAY|%)"
        r"(?:/\s*(?:ML|ACTUAT|HR|DAY))?\b",
        description,
        flags=re.IGNORECASE,
    )
    if not matches:
        return None
    unique = dict.fromkeys(match.strip() for match in matches)
    return " / ".join(unique)


def _interval_overlaps(
    valid_from: str | None,
    valid_to: str | None,
    as_of: str,
) -> bool:
    """Return whether an interval contains the given anchor date."""
    if not valid_from:
        return False
    anchor = _parse_date(as_of)
    start = _parse_date(valid_from)
    end = _parse_date(valid_to) if valid_to else None
    if anchor is None or start is None:
        return False
    return start <= anchor and (end is None or anchor <= end)


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO date string into a ``date`` object."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _sortable_date(value: str | None) -> str:
    """Return a sortable date string that pushes ``None`` to the bottom."""
    return value or "0001-01-01"


def _date_to_micros(value: str) -> int:
    """Convert an ISO date into microseconds since epoch at UTC midnight."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp() * 1_000_000)


def _micros_to_date_text(value: Any) -> str | None:
    """Convert a bridge microsecond timestamp to an ISO date string."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1_000_000, tz=timezone.utc).date().isoformat()
