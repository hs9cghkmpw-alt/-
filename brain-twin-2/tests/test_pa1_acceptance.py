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
        "backend_params": {
            "candidate_k": 50,
            "evaluation_k": 10,
            "warm_repeats": 30,
            "corpus_memory_count": 360,
        },
    }


def _policy(*, warm=0.5, rss=2_000_000_000):
    return policy_from_mapping(
        {
            "policy_id": "formal-v1",
            "dataset_version": "heldout-v1",
            "dataset_sha256": "a" * 64,
            "evaluator_git_commit": "b" * 40,
            "expected_retrieval_config_sha256": retrieval_config_sha256(
                _manifest()
            ),
            "minimum_query_count": 40,
            "expected_warm_repeats": 30,
            "min_recall_at_5": 0.90,
            "min_mrr_at_10": 0.80,
            "min_ndcg_at_10": 0.80,
            "min_must_hit_at_5": 0.95,
            "max_false_positive_at_5": 0.10,
            "max_warm_p95_seconds": warm,
            "max_peak_rss_after_bytes": rss,
            "max_warm_rank_drift_count": 0,
            "critical_slice_rules": [
                {
                    "slice_tag": "semantic_only",
                    "metric": "ndcg_at_10",
                    "comparator": "min",
                    "threshold": 0.75,
                },
                {
                    "slice_tag": "hard_negative",
                    "metric": "false_positive_at_5",
                    "comparator": "max",
                    "threshold": 0.20,
                },
            ],
        }
    )


def _report():
    policy = _policy()
    return {
        "manifest": _manifest(),
        "dataset_version": "heldout-v1",
        "dataset_sha256": "a" * 64,
        "judgement_visibility": "held_out",
        "split": "blind",
        "acceptance_blind_ready": True,
        "reproducible": True,
        "selection_eligible": True,
        "query_details_redacted": True,
        "overall": {
            "query_count": 40,
            "recall_at": {"5": 0.95},
            "mrr_at_10": 0.90,
            "ndcg_at_10": 0.91,
            "must_hit_at_5": 1.0,
            "false_positive_at_5": 0.05,
        },
        "latency": {
            "warm": {"p95_seconds": 0.2, "samples": 1200},
            "warm_rank_drift_count": 0,
        },
        "resources": {"peak_rss_after_bytes": 1_000_000_000},
        "formal_attestation": {
            "policy_sha256": policy_sha256(policy),
            "retrieval_config_sha256": (
                policy.expected_retrieval_config_sha256
            ),
            "critical_slice_gates": {
                "spec_sha256": policy.critical_slice_spec_sha256,
                "rule_count": policy.critical_slice_rule_count,
                "all_passed": True,
            },
        },
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
    assert any(
        gate.gate == "ndcg_at_10" and not gate.passed
        for gate in decision.gates
    )


def test_formal_acceptance_fails_open_or_unredacted_report() -> None:
    report = _report()
    report["judgement_visibility"] = "open"
    report["acceptance_blind_ready"] = False
    report["query_details_redacted"] = False
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    failed = {gate.gate for gate in decision.gates if not gate.passed}
    assert {
        "held_out_judgements",
        "query_details_redacted",
    }.issubset(failed)


def test_formal_acceptance_fails_non_blind_held_out_report() -> None:
    report = _report()
    report["split"] = "dev"
    report["acceptance_blind_ready"] = False
    report["query_details_redacted"] = False
    decision = evaluate_acceptance(report, _policy(), formal=True)
    failed = {gate.gate for gate in decision.gates if not gate.passed}
    assert {"acceptance_blind_ready", "blind_split", "query_details_redacted"}.issubset(
        failed
    )


def test_ranking_drift_is_selection_ineligible_even_with_quality_pass() -> None:
    report = _report()
    report["latency"]["warm_rank_drift_count"] = 1
    report["reproducible"] = False
    report["selection_eligible"] = False
    decision = evaluate_acceptance(report, _policy(), formal=True)
    failed = {gate.gate for gate in decision.gates if not gate.passed}
    assert {
        "warm_rank_drift_count",
        "reproducible",
        "selection_eligible",
    }.issubset(failed)


def test_formal_acceptance_fails_if_model_configuration_changes_after_policy_freeze() -> None:
    report = _report()
    report["manifest"]["dimension"] = 768
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    assert any(
        gate.gate == "retrieval_config_sha256" and not gate.passed
        for gate in decision.gates
    )


def test_formal_acceptance_fails_if_critical_slice_gate_fails() -> None:
    report = _report()
    report["formal_attestation"]["critical_slice_gates"][
        "all_passed"
    ] = False
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    assert any(
        gate.gate == "critical_slice_gates" and not gate.passed
        for gate in decision.gates
    )


def test_formal_acceptance_fails_if_warm_sample_count_is_not_frozen_count() -> None:
    report = _report()
    report["latency"]["warm"]["samples"] = 1199
    decision = evaluate_acceptance(report, _policy(), formal=True)
    assert decision.status == "fail"
    assert any(
        gate.gate == "warm_sample_count" and not gate.passed
        for gate in decision.gates
    )


def test_draft_policy_blocks_formal_decision_until_runtime_budgets_are_frozen() -> None:
    decision = evaluate_acceptance(
        _report(), _policy(warm=None, rss=None), formal=True
    )
    assert decision.status == "blocked"
    assert decision.gates == ()


def test_policy_hash_is_deterministic() -> None:
    assert policy_sha256(_policy()) == policy_sha256(_policy())


def test_policy_cannot_allow_nonzero_ranking_drift() -> None:
    raw = {
        "policy_id": "formal-v1",
        "dataset_version": "heldout-v1",
        "dataset_sha256": "a" * 64,
        "evaluator_git_commit": "b" * 40,
        "expected_retrieval_config_sha256": "c" * 64,
        "minimum_query_count": 1,
        "expected_warm_repeats": 1,
        "min_recall_at_5": 0.0,
        "min_mrr_at_10": 0.0,
        "min_ndcg_at_10": 0.0,
        "min_must_hit_at_5": 0.0,
        "max_false_positive_at_5": 1.0,
        "max_warm_p95_seconds": 1.0,
        "max_peak_rss_after_bytes": 1,
        "max_warm_rank_drift_count": 1,
        "critical_slice_rules": [],
    }
    try:
        policy_from_mapping(raw)
    except AcceptancePolicyError as exc:
        assert "must be 0" in str(exc)
    else:
        raise AssertionError("expected AcceptancePolicyError")


def test_retrieval_config_hash_ignores_measurement_fields_but_tracks_behavior() -> None:
    first = _manifest()
    second = _manifest()
    assert retrieval_config_sha256(first) == retrieval_config_sha256(
        second
    )

    second["backend_params"] = dict(second["backend_params"])
    second["backend_params"]["warm_repeats"] = 99
    second["backend_params"]["corpus_memory_count"] = 999
    second["backend_params"]["evaluation_k"] = 20
    assert retrieval_config_sha256(first) == retrieval_config_sha256(
        second
    )

    second["backend_params"]["candidate_k"] = 100
    assert retrieval_config_sha256(first) != retrieval_config_sha256(
        second
    )


def test_critical_slice_rules_are_committed_into_policy_hash() -> None:
    first = _policy()
    raw = {
        "policy_id": "formal-v1",
        "dataset_version": "heldout-v1",
        "dataset_sha256": "a" * 64,
        "evaluator_git_commit": "b" * 40,
        "expected_retrieval_config_sha256": (
            first.expected_retrieval_config_sha256
        ),
        "minimum_query_count": 40,
        "expected_warm_repeats": 30,
        "min_recall_at_5": 0.90,
        "min_mrr_at_10": 0.80,
        "min_ndcg_at_10": 0.80,
        "min_must_hit_at_5": 0.95,
        "max_false_positive_at_5": 0.10,
        "max_warm_p95_seconds": 0.5,
        "max_peak_rss_after_bytes": 2_000_000_000,
        "critical_slice_rules": [
            {
                "slice_tag": "semantic_only",
                "metric": "ndcg_at_10",
                "comparator": "min",
                "threshold": 0.76,
            }
        ],
    }
    second = policy_from_mapping(raw)
    assert policy_sha256(first) != policy_sha256(second)


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
