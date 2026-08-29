from __future__ import annotations

from brain_twin_eval.acceptance import (
    AcceptancePolicyError,
    evaluate_acceptance,
    policy_from_mapping,
    policy_sha256,
    retrieval_config_sha256,
)


def _manifest():
    return {
        "git_commit": "b" * 40,
        "provider_label": "sentence_transformers_local_eval",
        "model_name": "Qwen/Qwen3-Embedding-0.6B",
        "model_revision": "c" * 40,
        "instruction_id": "brain-twin-en-v1",
        "instruction_text_sha256": "d" * 64,
        "dimension": 1024,
        "normalized": True,
        "document_template_version": "1",
        "backend_label": "evaluation_exact_dense",
        "backend_params": {"candidate_k": 50},
    }


def _policy(*, warm=0.5, rss=2_000_000_000):
    return policy_from_mapping(
        {
            "policy_id": "formal-v1",
            "dataset_version": "heldout-v1",
            "dataset_sha256": "a" * 64,
            "evaluator_git_commit": "b" * 40,
            "expected_retrieval_config_sha256": retrieval_config_sha256(_manifest()),
            "minimum_query_count": 40,
            "min_recall_at_5": 0.90,
            "min_mrr_at_10": 0.80,
            "min_ndcg_at_10": 0.80,
            "min_must_hit_at_5": 0.95,
            "max_false_positive_at_5": 0.10,
            "max_warm_p95_seconds": warm,
            "max_peak_rss_after_bytes": rss,
            "max_warm_rank_drift_count": 0,
        }
    )


def _report():
    return {
        "manifest": _manifest(),
        "dataset_version": "heldout-v1",
        "dataset_sha256": "a" * 64,
        "judgement_visibility": "held_out",
        "split": "blind",
        "query_details_redacted": True,
        "overall": {
            "query_count": 40,
            "recall_at": {"5": 0.95},
            "mrr_at_10": 0.90,
            "ndcg_at_10": 0.91,
            "must_hit_at_5": 1.0,
            "false_positive_at_5": 0.05,
        },
        "latency": {"warm": {"p95_seconds": 0.2}, "warm_rank_drift_count": 0},
        "resources": {"peak_rss_after_bytes": 1_000_000_000},
    }


def test_formal_acceptance_passes_only_when_every_gate_passes() -> None:
    decision = evaluate_acceptance(_report(), _policy(), formal=True)
    assert decision.status == "pass"
    assert decision.passed is True
    assert decision.gates
    assert all(gate.passed for gate in decision.gates)


def test_formal_acceptance_fails_quality_regression() -> None:
    report = _report()
    report["overall"]["ndcg_at_10"] = 0.79
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    assert any(gate.gate == "ndcg_at_10" and not gate.passed for gate in decision.gates)


def test_formal_acceptance_fails_open_or_unredacted_report() -> None:
    report = _report()
    report["judgement_visibility"] = "open"
    report["query_details_redacted"] = False
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    failed = {gate.gate for gate in decision.gates if not gate.passed}
    assert {"held_out_judgements", "query_details_redacted"}.issubset(failed)


def test_formal_acceptance_fails_if_model_configuration_changes_after_policy_freeze() -> None:
    report = _report()
    report["manifest"]["dimension"] = 768
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    assert any(gate.gate == "retrieval_config_sha256" and not gate.passed for gate in decision.gates)


def test_draft_policy_blocks_formal_decision_until_runtime_budgets_are_frozen() -> None:
    decision = evaluate_acceptance(_report(), _policy(warm=None, rss=None), formal=True)
    assert decision.status == "blocked"
    assert decision.gates == ()


def test_policy_hash_is_deterministic() -> None:
    assert policy_sha256(_policy()) == policy_sha256(_policy())


def test_retrieval_config_hash_is_deterministic_and_sensitive_to_backend_params() -> None:
    first = _manifest()
    second = _manifest()
    assert retrieval_config_sha256(first) == retrieval_config_sha256(second)
    second["backend_params"] = {"candidate_k": 100}
    assert retrieval_config_sha256(first) != retrieval_config_sha256(second)


def test_policy_rejects_mutable_or_short_evaluator_commit() -> None:
    raw = {
        "policy_id": "x",
        "dataset_version": "v",
        "dataset_sha256": "a" * 64,
        "evaluator_git_commit": "main",
        "expected_retrieval_config_sha256": "e" * 64,
        "minimum_query_count": 1,
        "min_recall_at_5": 0.0,
        "min_mrr_at_10": 0.0,
        "min_ndcg_at_10": 0.0,
        "min_must_hit_at_5": 0.0,
        "max_false_positive_at_5": 1.0,
        "max_warm_p95_seconds": 1.0,
        "max_peak_rss_after_bytes": 1,
    }
    try:
        policy_from_mapping(raw)
    except AcceptancePolicyError as exc:
        assert "40-character" in str(exc)
    else:
        raise AssertionError("expected AcceptancePolicyError")
