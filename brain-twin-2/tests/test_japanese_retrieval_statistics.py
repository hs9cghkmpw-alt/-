from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from brain_twin_eval.dataset import load_dataset
from brain_twin_eval.runner import evaluate_rankings
from brain_twin_eval.statistics import bootstrap_mean_ci, metric_ci95, paired_metric_delta

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "japanese_retrieval_v1.json"


def _dataset():
    return load_dataset(FIXTURE)


def _perfect_rankings(dataset):
    rankings = {}
    for query in dataset.queries:
        positives = [
            memory_id
            for memory_id, grade in sorted(
                query.relevance.items(), key=lambda item: (-item[1], item[0])
            )
            if grade > 0
        ]
        negatives = [
            memory.memory_id
            for memory in dataset.memories
            if memory.memory_id not in positives and memory.active
        ]
        rankings[query.query_id] = (positives + negatives)[:10]
    return rankings


def test_bootstrap_mean_ci_is_deterministic_and_contains_observed_mean():
    first = bootstrap_mean_ci([0.0, 0.5, 1.0, 1.0], iterations=500, seed=123)
    second = bootstrap_mean_ci([0.0, 0.5, 1.0, 1.0], iterations=500, seed=123)
    assert first == second
    assert first.low <= 0.625 <= first.high


def test_metric_ci95_is_available_for_standard_run_metrics():
    dataset = _dataset()
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="dev")
    ci = metric_ci95(run, "ndcg_at_10", iterations=200, seed=4)
    assert ci is not None
    assert 0.0 <= ci.low <= ci.high <= 1.0


def test_paired_metric_delta_is_candidate_minus_baseline_and_deterministic():
    dataset = _dataset()
    baseline_rankings = _perfect_rankings(dataset)
    candidate_rankings = {qid: list(ids) for qid, ids in baseline_rankings.items()}
    candidate_rankings["q-001"] = list(reversed(candidate_rankings["q-001"][:10]))

    baseline = evaluate_rankings(dataset, baseline_rankings, split="dev")
    candidate = evaluate_rankings(dataset, candidate_rankings, split="dev")
    first = paired_metric_delta(
        baseline, candidate, "mrr_at_10", iterations=500, seed=9
    )
    second = paired_metric_delta(
        baseline, candidate, "mrr_at_10", iterations=500, seed=9
    )
    assert first == second
    assert first.query_count == 15
    assert first.mean_delta <= 0.0
    assert first.ci95.low <= first.mean_delta <= first.ci95.high


def test_paired_metric_delta_rejects_unavailable_metric():
    dataset = _dataset()
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="dev")
    with pytest.raises(ValueError, match="unsupported metric"):
        paired_metric_delta(run, run, "not_a_metric", iterations=10)


def test_paired_metric_delta_rejects_selection_ineligible_run():
    dataset = _dataset()
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="dev")
    ineligible = replace(run, reproducible=False, selection_eligible=False)
    with pytest.raises(ValueError, match="selection eligible"):
        paired_metric_delta(run, ineligible, "ndcg_at_10", iterations=10)
