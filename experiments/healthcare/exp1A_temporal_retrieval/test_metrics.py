"""Toy-input metric tests for Exp 1A.

These tests intentionally avoid the live temporal bridge and any real fixture
files. Phase 3's gate is about metric semantics, so each case uses tiny
hand-built candidates whose intervals and family labels are easy to inspect.
"""

from __future__ import annotations

import pytest

from experiments.healthcare.eval_runner import (
    _candidates_match,
    in_family_mrr,
    interval_precision_at_k,
    same_family_retention,
    temporal_error_days,
    time_sliced_hits_at_1,
)


def _candidate(
    *,
    answer: str,
    family: str,
    valid_from: str,
    valid_to: str | None,
    source_id: str,
) -> dict[str, str | None]:
    """Build a compact candidate dict that matches Exp 1A metric inputs."""
    return {
        "answer": answer,
        "description": answer,
        "concept_family": family,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_id": source_id,
    }


def _family_of(candidate: dict[str, str | None]) -> str | None:
    """Extract the concept family label for same-family metrics."""
    return candidate.get("concept_family")


def test_perfect_top_1_in_family_overlap_scores_as_hit() -> None:
    """Perfect retrieval should look perfect on ranking-oriented metrics."""
    gold = _candidate(
        answer="Metformin 500 MG",
        family="metformin",
        valid_from="2020-01-01",
        valid_to="2020-12-31",
        source_id="gold",
    )
    retrieved = [
        gold,
        _candidate(
            answer="Metformin 1000 MG",
            family="metformin",
            valid_from="2019-01-01",
            valid_to="2019-12-31",
            source_id="older",
        ),
        _candidate(
            answer="Lisinopril 10 MG",
            family="lisinopril",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="noise",
        ),
    ]

    assert time_sliced_hits_at_1(retrieved, gold, "2020-06-01") == 1.0
    assert in_family_mrr(retrieved, gold, _family_of) == 1.0
    assert interval_precision_at_k(retrieved, "2020-06-01", 3) == pytest.approx(2 / 3, abs=1e-4)


def test_wrong_family_top_1_is_not_a_hit() -> None:
    """Wrong-family and gold-absent cases should contribute zero, not be excluded."""
    gold = _candidate(
        answer="Metformin 500 MG",
        family="metformin",
        valid_from="2020-01-01",
        valid_to="2020-12-31",
        source_id="gold",
    )
    retrieved = [
        _candidate(
            answer="Lisinopril 10 MG",
            family="lisinopril",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="noise",
        ),
        gold,
    ]

    assert time_sliced_hits_at_1(retrieved, gold, "2020-06-01") == 0.0
    assert in_family_mrr(retrieved, gold, _family_of) == 1.0

    absent_gold = [
        _candidate(
            answer="Lisinopril 10 MG",
            family="lisinopril",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="noise-1",
        ),
        _candidate(
            answer="Warfarin 5 MG",
            family="warfarin",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="noise-2",
        ),
    ]

    assert time_sliced_hits_at_1(absent_gold, gold, "2020-06-01") == 0.0
    assert in_family_mrr(absent_gold, gold, _family_of) == 0.0


def test_temporal_error_days_reports_close_miss_distance() -> None:
    """Close misses should preserve both magnitude and temporal direction."""
    earlier_pick = _candidate(
        answer="Metformin 500 MG",
        family="metformin",
        valid_from="2020-01-01",
        valid_to="2020-01-01",
        source_id="earlier",
    )
    later_pick = _candidate(
        answer="Metformin 500 MG",
        family="metformin",
        valid_from="2020-01-15",
        valid_to="2020-01-15",
        source_id="later",
    )

    assert temporal_error_days(earlier_pick, "2020-01-08") == pytest.approx(-7.0)
    assert temporal_error_days(later_pick, "2020-01-08") == pytest.approx(7.0)


def test_same_family_retention_counts_family_mix_in_top_k() -> None:
    """Retention should expose family mix and penalize thin-result arms."""
    retrieved = [
        _candidate(
            answer="Metformin 500 MG",
            family="metformin",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="a",
        ),
        _candidate(
            answer="Metformin 1000 MG",
            family="metformin",
            valid_from="2019-01-01",
            valid_to="2019-12-31",
            source_id="b",
        ),
        _candidate(
            answer="Lisinopril 10 MG",
            family="lisinopril",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="c",
        ),
        _candidate(
            answer="Metformin ER",
            family="metformin",
            valid_from="2018-01-01",
            valid_to="2018-12-31",
            source_id="d",
        ),
        _candidate(
            answer="Warfarin 5 MG",
            family="warfarin",
            valid_from="2020-01-01",
            valid_to="2020-12-31",
            source_id="e",
        ),
    ]

    assert same_family_retention(retrieved, "metformin", _family_of, k=5) == pytest.approx(0.6)
    assert interval_precision_at_k(retrieved, "2020-06-01", 5) == pytest.approx(0.6)

    thin_results = retrieved[:2]
    assert same_family_retention(thin_results, "metformin", _family_of, k=5) == pytest.approx(0.4)


def test_candidate_identity_ignores_valid_to_reporting_differences() -> None:
    """Bridge rows with open-ended `valid_to` must still match the closed fixture fact."""
    candidate = _candidate(
        answer="Clopidogrel 75 MG Oral Tablet",
        family="antiplatelet",
        valid_from="1997-05-19",
        valid_to=None,
        source_id="bridge-edge-id",
    )
    gold = _candidate(
        answer="Clopidogrel 75 MG Oral Tablet",
        family="antiplatelet",
        valid_from="1997-05-19",
        valid_to="2017-04-02",
        source_id="fixture-composite-id",
    )

    assert _candidates_match(candidate, gold) is True


def test_candidate_identity_requires_matching_valid_from() -> None:
    """Different start dates must remain distinct facts even when the answer text matches."""
    candidate = _candidate(
        answer="Clopidogrel 75 MG Oral Tablet",
        family="antiplatelet",
        valid_from="1998-05-19",
        valid_to=None,
        source_id="bridge-edge-id",
    )
    gold = _candidate(
        answer="Clopidogrel 75 MG Oral Tablet",
        family="antiplatelet",
        valid_from="1997-05-19",
        valid_to="2017-04-02",
        source_id="fixture-composite-id",
    )

    assert _candidates_match(candidate, gold) is False


def test_candidate_identity_normalizes_whitespace_and_casing() -> None:
    """Formatting differences like `MG` vs `mg` or extra spaces must not break matches."""
    candidate = _candidate(
        answer="  Clopidogrel   75   mg oral   tablet ",
        family="antiplatelet",
        valid_from="1997-05-19",
        valid_to=None,
        source_id="bridge-edge-id",
    )
    gold = _candidate(
        answer="Clopidogrel 75 MG Oral Tablet",
        family="antiplatelet",
        valid_from="1997-05-19",
        valid_to="2017-04-02",
        source_id="fixture-composite-id",
    )

    assert _candidates_match(candidate, gold) is True
