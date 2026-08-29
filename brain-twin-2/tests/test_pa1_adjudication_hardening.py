from __future__ import annotations

from brain_twin_eval.adjudication import AdjudicationError, judge_package_from_mapping


def test_non_hard_negative_requires_at_least_one_positive_relevance() -> None:
    try:
        judge_package_from_mapping({
            "schema": 1,
            "judge_id": "judge-a",
            "runner_sha256": "a" * 64,
            "queries": [{
                "query_id": "q-1",
                "relevance": {"mem-1": 0},
                "must_hit_ids": [],
                "hard_negative": False,
            }],
        })
    except AdjudicationError as exc:
        assert "must have positive relevance" in str(exc)
    else:
        raise AssertionError("expected AdjudicationError")
