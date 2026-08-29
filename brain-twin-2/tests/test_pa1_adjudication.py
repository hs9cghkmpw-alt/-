from __future__ import annotations

from brain_twin_eval.adjudication import (
    AdjudicationError,
    compare_judges,
    judge_package_from_mapping,
    summary_payload,
)


def _package(judge_id: str, *, grade: int = 3, must_hit: bool = True, hard_negative: bool = False):
    relevance = {} if hard_negative else {"mem-1": grade}
    return judge_package_from_mapping(
        {
            "schema": 1,
            "judge_id": judge_id,
            "runner_sha256": "a" * 64,
            "queries": [
                {
                    "query_id": "q-1",
                    "relevance": relevance,
                    "must_hit_ids": ["mem-1"] if must_hit and not hard_negative else [],
                    "hard_negative": hard_negative,
                }
            ],
        }
    )


def test_identical_independent_judgements_have_exact_agreement() -> None:
    summary = compare_judges(_package("judge-a"), _package("judge-b"))
    assert summary.query_count == 1
    assert summary.exact_agreement_count == 1
    assert summary.exact_agreement_rate == 1.0
    assert summary.disagreements == ()


def test_grade_disagreement_is_reported_for_adjudication() -> None:
    summary = compare_judges(_package("judge-a", grade=3), _package("judge-b", grade=2))
    assert summary.exact_agreement_count == 0
    assert summary.disagreements[0].relevance_differences == {"mem-1": (3, 2)}
    assert summary_payload(summary)["disagreement_count"] == 1


def test_hard_negative_disagreement_is_reported() -> None:
    summary = compare_judges(_package("judge-a"), _package("judge-b", hard_negative=True, must_hit=False))
    assert summary.disagreements[0].hard_negative_a is False
    assert summary.disagreements[0].hard_negative_b is True


def test_different_runner_commitments_are_rejected() -> None:
    left = _package("judge-a")
    right_raw = {
        "schema": 1,
        "judge_id": "judge-b",
        "runner_sha256": "b" * 64,
        "queries": [{"query_id": "q-1", "relevance": {"mem-1": 3}, "must_hit_ids": ["mem-1"], "hard_negative": False}],
    }
    right = judge_package_from_mapping(right_raw)
    try:
        compare_judges(left, right)
    except AdjudicationError as exc:
        assert "same blind runner" in str(exc)
    else:
        raise AssertionError("expected AdjudicationError")


def test_hard_negative_cannot_have_positive_relevance() -> None:
    try:
        judge_package_from_mapping(
            {
                "schema": 1,
                "judge_id": "judge-a",
                "runner_sha256": "a" * 64,
                "queries": [{"query_id": "q-1", "relevance": {"mem-1": 1}, "must_hit_ids": [], "hard_negative": True}],
            }
        )
    except AdjudicationError as exc:
        assert "hard-negative" in str(exc)
    else:
        raise AssertionError("expected AdjudicationError")
