from __future__ import annotations

from brain_twin_eval.critical_slice import (
    CriticalSliceError,
    evaluate_critical_slices,
    rule_spec_sha256,
    rules_from_policy_mapping,
    summary_payload,
    verify_summary,
)
from brain_twin_eval.runner import AggregateMetrics, EvaluationRun


def _aggregate(*, ndcg=0.9, fp=0.0, must_hit=1.0):
    return AggregateMetrics(
        query_count=2,
        recall_at={1: 0.5, 3: 0.8, 5: 0.9, 10: 1.0},
        mrr_at_10=0.9,
        ndcg_at_10=ndcg,
        must_hit_at_5=must_hit,
        false_positive_at_5=fp,
    )


def _run():
    return EvaluationRun(
        dataset_version="v",
        dataset_sha256="a" * 64,
        judgement_visibility="held_out",
        split="blind",
        queries=(),
        overall=_aggregate(),
        per_slice={"semantic_only": _aggregate(ndcg=0.88), "hard_negative": _aggregate(fp=0.05)},
    )


def _policy():
    return {
        "critical_slice_rules": [
            {"slice_tag": "semantic_only", "metric": "ndcg_at_10", "comparator": "min", "threshold": 0.8},
            {"slice_tag": "hard_negative", "metric": "false_positive_at_5", "comparator": "max", "threshold": 0.1},
        ]
    }


def test_critical_slice_rules_pass_without_leaking_slice_scores() -> None:
    rules = rules_from_policy_mapping(_policy())
    summary = evaluate_critical_slices(_run(), rules)
    payload = summary_payload(summary)
    assert summary.all_passed is True
    assert payload == {
        "spec_sha256": rule_spec_sha256(rules),
        "rule_count": 2,
        "all_passed": True,
    }
    assert "semantic_only" not in str(payload)
    assert "0.88" not in str(payload)
    assert verify_summary(payload, rules) is True


def test_critical_slice_failure_is_only_exposed_as_boolean() -> None:
    rules = rules_from_policy_mapping(_policy())
    run = _run()
    run = EvaluationRun(
        dataset_version=run.dataset_version,
        dataset_sha256=run.dataset_sha256,
        judgement_visibility=run.judgement_visibility,
        split=run.split,
        queries=run.queries,
        overall=run.overall,
        per_slice={"semantic_only": _aggregate(ndcg=0.4), "hard_negative": _aggregate(fp=0.05)},
    )
    payload = summary_payload(evaluate_critical_slices(run, rules))
    assert payload["all_passed"] is False
    assert "0.4" not in str(payload)


def test_missing_critical_slice_fails_closed() -> None:
    rules = rules_from_policy_mapping(_policy())
    run = _run()
    run = EvaluationRun(run.dataset_version, run.dataset_sha256, run.judgement_visibility, run.split, (), run.overall, {"semantic_only": _aggregate()})
    try:
        evaluate_critical_slices(run, rules)
    except CriticalSliceError as exc:
        assert "hard_negative" in str(exc)
    else:
        raise AssertionError("expected CriticalSliceError")


def test_rule_contract_rejects_wrong_comparator() -> None:
    try:
        rules_from_policy_mapping({"critical_slice_rules": [{"slice_tag": "x", "metric": "ndcg_at_10", "comparator": "max", "threshold": 0.5}]})
    except CriticalSliceError as exc:
        assert "comparator=min" in str(exc)
    else:
        raise AssertionError("expected CriticalSliceError")
