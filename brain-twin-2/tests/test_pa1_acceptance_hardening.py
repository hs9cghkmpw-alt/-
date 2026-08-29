from __future__ import annotations

from brain_twin_eval.acceptance import AcceptancePolicyError, evaluate_acceptance, policy_from_mapping


def _policy():
    return policy_from_mapping({
        "policy_id": "formal-v1",
        "dataset_version": "heldout-v1",
        "dataset_sha256": "a" * 64,
        "evaluator_git_commit": "b" * 40,
        "expected_retrieval_config_sha256": "c" * 64,
        "minimum_query_count": 1,
        "min_recall_at_5": 0.0,
        "min_mrr_at_10": 0.0,
        "min_ndcg_at_10": 0.0,
        "min_must_hit_at_5": 0.0,
        "max_false_positive_at_5": 1.0,
        "max_warm_p95_seconds": 1.0,
        "max_peak_rss_after_bytes": 2_000_000_000,
    })


def test_malformed_overall_is_rejected_as_typed_policy_error() -> None:
    payload = {
        "manifest": {"git_commit": "b" * 40},
        "overall": [],
        "latency": {"warm": {}, "warm_rank_drift_count": 0},
        "resources": {},
    }
    try:
        evaluate_acceptance(payload, _policy())
    except AcceptancePolicyError as exc:
        assert "report.overall" in str(exc)
    else:
        raise AssertionError("expected AcceptancePolicyError")


def test_malformed_latency_is_rejected_as_typed_policy_error() -> None:
    payload = {
        "manifest": {"git_commit": "b" * 40},
        "overall": {"query_count": 1, "recall_at": {"5": 1.0}, "mrr_at_10": 1.0, "ndcg_at_10": 1.0, "must_hit_at_5": 1.0, "false_positive_at_5": 0.0},
        "latency": [],
        "resources": {},
    }
    try:
        evaluate_acceptance(payload, _policy())
    except AcceptancePolicyError as exc:
        assert "report.latency" in str(exc)
    else:
        raise AssertionError("expected AcceptancePolicyError")
