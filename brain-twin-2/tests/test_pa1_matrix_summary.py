from __future__ import annotations

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
    dataset_sha: str = "abc",
) -> dict:
    return {
        "manifest": {
            "experiment_id": experiment_id,
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
        "judgement_visibility": "open",
        "split": "dev",
        "overall": {
            "recall_at": {"1": 0.4, "3": 0.7, "5": recall5, "10": 1.0},
            "mrr_at_10": mrr,
            "ndcg_at_10": ndcg,
            "must_hit_at_5": must_hit,
            "false_positive_at_5": fp5,
        },
        "latency": {"warm": {"p95_seconds": warm_p95}},
    }


def test_entry_extracts_dense_contract() -> None:
    entry = entry_from_payload(_payload(experiment_id="en-1024"), report_path="x.json")
    assert entry.candidate_id == "en-1024"
    assert entry.kind == "dense"
    assert entry.dimension == 1024
    assert entry.base_candidate_id is None


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


def test_summary_is_deterministic_independent_of_input_order() -> None:
    a = ("a.json", _payload(experiment_id="a", ndcg=0.7))
    b = ("b.json", _payload(experiment_id="b", ndcg=0.8))
    first = summarize_payloads([a, b])
    second = summarize_payloads([b, a])
    assert first == second
