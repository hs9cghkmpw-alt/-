from __future__ import annotations

from dataclasses import replace

import pytest

from brain_twin_eval.matrix_summary import (
    MatrixSummaryError,
    choose_winner,
    entry_from_payload,
    summarize_payloads,
)


def _payload(
    *,
    experiment_id: str,
    backend: str = "evaluation_exact_dense",
    instruction: str = "en",
    dimension: int = 1024,
    ndcg: float = 0.7,
    mrr: float = 0.6,
    recall5: float = 0.8,
    must_hit: float | None = 0.9,
    fp5: float = 0.2,
    warm_p95: float | None = 0.3,
    drift: int = 0,
    reproducible: bool = True,
    selection_eligible: bool = True,
    dataset_sha: str = "abc",
    git_commit: str = "1" * 40,
    judgement_visibility: str = "open",
    split: str | None = "dev",
) -> dict:
    return {
        "manifest": {
            "experiment_id": experiment_id,
            "git_commit": git_commit,
            "model_name": "Qwen/Qwen3-Embedding-0.6B",
            "model_revision": "a" * 40,
            "instruction_id": instruction,
            "dimension": dimension,
            "backend_label": backend,
            "backend_params": (
                {"base_candidate_id": "base"}
                if backend == "evaluation_rerank"
                else {}
            ),
        },
        "dataset_version": "v2",
        "dataset_sha256": dataset_sha,
        "judgement_visibility": judgement_visibility,
        "split": split,
        "reproducible": reproducible,
        "selection_eligible": selection_eligible,
        "overall": {
            "recall_at": {"1": 0.4, "3": 0.7, "5": recall5, "10": 1.0},
            "mrr_at_10": mrr,
            "ndcg_at_10": ndcg,
            "must_hit_at_5": must_hit,
            "false_positive_at_5": fp5,
        },
        "latency": {
            "warm": {"p95_seconds": warm_p95},
            "warm_rank_drift_count": drift,
        },
    }


def test_entry_extracts_dense_contract() -> None:
    entry = entry_from_payload(_payload(experiment_id="en-1024"), report_path="x.json")
    assert entry.candidate_id == "en-1024"
    assert entry.kind == "dense"
    assert entry.dimension == 1024
    assert entry.base_candidate_id is None


@pytest.mark.parametrize("field", ["ndcg", "mrr", "recall5", "must_hit", "fp5"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.1, 1.1])
def test_matrix_rejects_invalid_quality_numbers(field, value) -> None:
    payload = _payload(experiment_id="invalid", **{field: value})
    with pytest.raises(MatrixSummaryError):
        summarize_payloads([("invalid.json", payload)])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.1])
def test_matrix_rejects_invalid_latency(value) -> None:
    with pytest.raises(MatrixSummaryError):
        entry_from_payload(_payload(experiment_id="invalid", warm_p95=value), report_path="x.json")


@pytest.mark.parametrize("field", ["ndcg", "warm_p95"])
@pytest.mark.parametrize("value", [True, "0.9", 10**400])
def test_matrix_rejects_non_numeric_or_overflowing_values(field, value) -> None:
    with pytest.raises(MatrixSummaryError):
        entry_from_payload(_payload(experiment_id="invalid", **{field: value}), report_path="x.json")


@pytest.mark.parametrize("changes", [
    {"warm_rank_drift_count": 1},
    {"reproducible": False},
    {"selection_eligible": "true"},
    {"warm_rank_drift_count": False},
    {"ndcg_at_10": float("nan")},
])
def test_direct_matrix_entry_cannot_bypass_validation(changes) -> None:
    valid = entry_from_payload(_payload(experiment_id="valid"), report_path="x.json")
    with pytest.raises(MatrixSummaryError):
        choose_winner([replace(valid, **changes)])


def test_matrix_accepts_quality_boundaries_and_optional_metrics() -> None:
    payload = _payload(experiment_id="valid", ndcg=1.0, mrr=0.0, recall5=1.0,
                       must_hit=None, fp5=0.0, warm_p95=None)
    assert entry_from_payload(payload, report_path="x.json").selection_eligible is True


def test_entry_extracts_reranker_base_candidate() -> None:
    entry = entry_from_payload(
        _payload(experiment_id="base+rerank", backend="evaluation_rerank"),
        report_path="x.json",
    )
    assert entry.kind == "reranked"
    assert entry.base_candidate_id == "base"


def test_winner_prioritizes_ndcg_before_latency() -> None:
    fast = entry_from_payload(
        _payload(experiment_id="fast", ndcg=0.70, warm_p95=0.01), report_path="fast.json"
    )
    better = entry_from_payload(
        _payload(experiment_id="better", ndcg=0.71, warm_p95=5.0), report_path="better.json"
    )
    assert choose_winner([fast, better]).candidate_id == "better"


def test_drifted_candidate_is_retained_but_cannot_win() -> None:
    stable = entry_from_payload(
        _payload(experiment_id="stable", ndcg=0.70), report_path="stable.json"
    )
    drifted = entry_from_payload(
        _payload(
            experiment_id="drifted",
            ndcg=0.99,
            drift=1,
            reproducible=False,
            selection_eligible=False,
        ),
        report_path="drifted.json",
    )
    assert choose_winner([stable, drifted]).candidate_id == "stable"
    summary = summarize_payloads(
        [
            ("stable.json", _payload(experiment_id="stable", ndcg=0.70)),
            (
                "drifted.json",
                _payload(
                    experiment_id="drifted",
                    ndcg=0.99,
                    drift=1,
                    reproducible=False,
                    selection_eligible=False,
                ),
            ),
        ]
    )
    assert summary["selection_ineligible_candidates"] == ["drifted"]
    assert summary["overall_open_winner"]["candidate_id"] == "stable"


def test_all_ineligible_candidates_produce_no_winner() -> None:
    payload = _payload(
        experiment_id="drifted",
        drift=1,
        reproducible=False,
        selection_eligible=False,
    )
    summary = summarize_payloads([("drifted.json", payload)])
    assert summary["selection_eligible_entry_count"] == 0
    assert summary["dense_winner"] is None
    assert summary["overall_open_winner"] is None


def test_winner_uses_must_hit_then_mrr_as_tiebreaks() -> None:
    lower = entry_from_payload(
        _payload(experiment_id="lower", ndcg=0.7, must_hit=0.8, mrr=0.9), report_path="a.json"
    )
    higher = entry_from_payload(
        _payload(experiment_id="higher", ndcg=0.7, must_hit=0.9, mrr=0.5), report_path="b.json"
    )
    assert choose_winner([lower, higher]).candidate_id == "higher"


def test_summary_keeps_dense_and_overall_winners_separate() -> None:
    dense = _payload(experiment_id="dense", ndcg=0.75)
    reranked = _payload(
        experiment_id="dense+rerank", backend="evaluation_rerank", ndcg=0.80
    )
    summary = summarize_payloads([("dense.json", dense), ("reranked.json", reranked)])
    assert summary["dense_winner"]["candidate_id"] == "dense"
    assert summary["overall_open_winner"]["candidate_id"] == "dense+rerank"
    assert summary["git_commit"] == "1" * 40
    assert summary["formal_blind_acceptance"] is False


def test_summary_rejects_mixed_dataset_identity() -> None:
    try:
        summarize_payloads(
            [
                ("a.json", _payload(experiment_id="a", dataset_sha="abc")),
                ("b.json", _payload(experiment_id="b", dataset_sha="def")),
            ]
        )
    except MatrixSummaryError as exc:
        assert "same dataset" in str(exc)
    else:
        raise AssertionError("expected MatrixSummaryError")


def test_summary_rejects_mixed_git_commit() -> None:
    try:
        summarize_payloads(
            [
                ("a.json", _payload(experiment_id="a", git_commit="1" * 40)),
                ("b.json", _payload(experiment_id="b", git_commit="2" * 40)),
            ]
        )
    except MatrixSummaryError as exc:
        assert "Git commit" in str(exc)
    else:
        raise AssertionError("expected MatrixSummaryError")


def test_summary_rejects_duplicate_candidate_ids() -> None:
    try:
        summarize_payloads(
            [
                ("a.json", _payload(experiment_id="same")),
                ("b.json", _payload(experiment_id="same")),
            ]
        )
    except MatrixSummaryError as exc:
        assert "duplicate candidate IDs" in str(exc)
    else:
        raise AssertionError("expected MatrixSummaryError")


def test_summary_is_deterministic_independent_of_input_order() -> None:
    a = ("a.json", _payload(experiment_id="a", ndcg=0.7))
    b = ("b.json", _payload(experiment_id="b", ndcg=0.8))
    first = summarize_payloads([a, b])
    second = summarize_payloads([b, a])
    assert first == second

@pytest.mark.parametrize(
    ("judgement_visibility", "split"),
    [
        ("held_out", "blind"),
        ("held_out", "dev"),
        ("held_out", None),
        ("open", "blind"),
        ("open", None),
    ],
)
def test_open_matrix_rejects_non_open_development_evidence(
    judgement_visibility: str,
    split: str | None,
) -> None:
    payload = _payload(
        experiment_id="wrong-evidence-scope",
        judgement_visibility=judgement_visibility,
        split=split,
    )
    with pytest.raises(MatrixSummaryError, match="open-development matrix requires"):
        summarize_payloads([("wrong.json", payload)])

