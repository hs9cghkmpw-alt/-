from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_twin_eval.dataset import (
    DatasetValidationError,
    dataset_from_mapping,
    dataset_sha256,
    load_dataset,
)
from brain_twin_eval.manifest import ManifestValidationError, build_manifest, manifest_json
from brain_twin_eval.metrics import (
    ann_recall_at_k,
    compute_query_metrics,
    ndcg_at_k,
    reciprocal_rank_at_k,
)
from brain_twin_eval.report import report_json, report_markdown
from brain_twin_eval.runner import RankedResult, evaluate_rankings, evaluate_retriever

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "japanese_retrieval_v1.json"


def _raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _dataset():
    return load_dataset(FIXTURE)


def _manifest(dataset):
    return build_manifest(
        dataset=dataset,
        experiment_id="test-exp",
        git_commit="a" * 40,
        provider_label="fixture",
        model_name="fixture-model",
        model_revision="rev-1",
        instruction_id="none",
        instruction_text="",
        dimension=4,
        normalized=True,
        document_template_version="1",
        backend_label="precomputed",
        backend_params={"k": 10},
        random_seed=42,
        timestamp_utc="2026-08-27T00:00:00+00:00",
    )


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


def test_valid_fixture_loads_and_covers_all_required_slices():
    dataset = _dataset()
    assert len(dataset.memories) == 36
    assert len(dataset.queries) == 24
    assert len(dataset.queries_for_split("dev")) == 15
    assert len(dataset.queries_for_split("blind")) == 9


def test_dataset_hash_is_deterministic():
    assert dataset_sha256(_dataset()) == dataset_sha256(_dataset())


def test_duplicate_memory_id_rejected():
    raw = _raw()
    raw["memories"][1]["memory_id"] = raw["memories"][0]["memory_id"]
    with pytest.raises(DatasetValidationError, match="duplicate memory_id"):
        dataset_from_mapping(raw)


def test_duplicate_query_id_rejected():
    raw = _raw()
    raw["queries"][1]["query_id"] = raw["queries"][0]["query_id"]
    with pytest.raises(DatasetValidationError, match="duplicate query_id"):
        dataset_from_mapping(raw)


def test_broken_relevance_reference_rejected():
    raw = _raw()
    raw["queries"][0]["relevance"]["missing-memory"] = 3
    with pytest.raises(DatasetValidationError, match="unknown memory"):
        dataset_from_mapping(raw)


def test_invalid_grade_rejected():
    raw = _raw()
    raw["queries"][0]["relevance"]["mem-001"] = 4
    with pytest.raises(DatasetValidationError, match="0..3"):
        dataset_from_mapping(raw)


def test_empty_query_rejected():
    raw = _raw()
    raw["queries"][0]["text"] = " "
    with pytest.raises(DatasetValidationError, match="must be a non-empty string"):
        dataset_from_mapping(raw)


def test_must_hit_must_be_positive_relevance():
    raw = _raw()
    raw["queries"][0]["relevance"]["mem-001"] = 0
    with pytest.raises(DatasetValidationError, match="must have positive relevance"):
        dataset_from_mapping(raw)


def test_missing_required_slice_rejected():
    raw = _raw()
    for query in raw["queries"]:
        query["slice_tags"] = [tag for tag in query["slice_tags"] if tag != "long_memory"]
    with pytest.raises(DatasetValidationError, match="long_memory"):
        dataset_from_mapping(raw)


def test_mrr_known_answer():
    query = _dataset().queries[0]
    assert reciprocal_rank_at_k(query, ["mem-022", "mem-001"], 10) == 0.5


def test_ndcg_known_answer_perfect_is_one():
    query = _dataset().queries[0]
    assert ndcg_at_k(query, ["mem-001", "mem-003"], 10) == pytest.approx(1.0)


def test_query_metric_known_answer_and_must_hit():
    query = _dataset().queries[0]
    metrics = compute_query_metrics(query, ["mem-001", "mem-022", "mem-003"])
    assert metrics.recall_at[1] == pytest.approx(0.5)
    assert metrics.recall_at[3] == pytest.approx(1.0)
    assert metrics.mrr_at_10 == 1.0
    assert metrics.must_hit_at_5 == 1.0
    assert metrics.false_positive_at_5 == 0.0


def test_hard_negative_false_positive_behavior():
    query = next(q for q in _dataset().queries if q.query_id == "q-024")
    metrics = compute_query_metrics(query, ["mem-022", "mem-023"])
    assert metrics.recall_at[5] == 0.0
    assert metrics.mrr_at_10 == 0.0
    assert metrics.ndcg_at_10 == 0.0
    assert metrics.must_hit_at_5 is None
    assert metrics.false_positive_at_5 == 1.0


def test_ann_recall_against_exact_known_answer():
    exact = [f"m{i}" for i in range(10)]
    ann = ["m0", "m2", "m4", "x", "y"]
    assert ann_recall_at_k(exact, ann, 5) == pytest.approx(3 / 5)


def test_evaluate_rankings_aggregates_slices_and_split():
    dataset = _dataset()
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="blind")
    assert run.overall.query_count == 9
    assert set(item.split for item in run.queries) == {"blind"}
    assert "hard_negative" in run.per_slice
    assert run.per_slice["hard_negative"].query_count == 1


def test_evaluate_rankings_is_deterministic():
    dataset = _dataset()
    rankings = _perfect_rankings(dataset)
    first = evaluate_rankings(dataset, rankings, split="dev")
    second = evaluate_rankings(dataset, rankings, split="dev")
    assert first == second


def test_missing_ranking_rejected():
    dataset = _dataset()
    rankings = _perfect_rankings(dataset)
    del rankings["q-001"]
    with pytest.raises(ValueError, match="missing rankings"):
        evaluate_rankings(dataset, rankings, split="dev")


def test_duplicate_ranked_ids_rejected():
    dataset = _dataset()
    rankings = _perfect_rankings(dataset)
    rankings["q-001"] = ["mem-001", "mem-001"]
    with pytest.raises(ValueError, match="duplicate ranked"):
        evaluate_rankings(dataset, rankings, split="dev")


def test_unknown_ranked_id_rejected():
    dataset = _dataset()
    rankings = _perfect_rankings(dataset)
    rankings["q-001"] = ["unknown"]
    with pytest.raises(ValueError, match="unknown memory"):
        evaluate_rankings(dataset, rankings, split="dev")


def test_inactive_ranked_id_rejected():
    dataset = _dataset()
    rankings = _perfect_rankings(dataset)
    rankings["q-001"] = ["mem-036"]
    with pytest.raises(ValueError, match="inactive memory"):
        evaluate_rankings(dataset, rankings, split="dev")


class _FixtureRetriever:
    def __init__(self, memory_id: str):
        self.memory_id = memory_id

    def search(self, query: str, k: int):
        return [RankedResult(self.memory_id, 1.0)]


def test_retriever_adapter_contract_records_latency():
    dataset = _dataset()
    run = evaluate_retriever(
        dataset,
        _FixtureRetriever("mem-001"),
        split="dev",
        k=10,
    )
    assert run.overall.query_count == 15
    assert all(item.latency_seconds is not None for item in run.queries)


def test_manifest_required_fields_and_instruction_hash():
    dataset = _dataset()
    manifest = _manifest(dataset)
    assert manifest.dataset_version == dataset.version
    assert manifest.dataset_sha256 == dataset_sha256(dataset)
    assert len(manifest.instruction_text_sha256) == 64
    assert '"instruction_text":' not in manifest_json(manifest)


@pytest.mark.parametrize(
    "backend_params",
    [
        {"api_key": "not-even-real"},
        {"nested": {"access-token": "x"}},
        {"header": "Bearer abc"},
        {"value": "sk-example"},
    ],
)
def test_manifest_rejects_secret_like_values(backend_params):
    dataset = _dataset()
    with pytest.raises(ManifestValidationError, match="secret-like"):
        build_manifest(
            dataset=dataset,
            experiment_id="test-exp",
            git_commit="a" * 40,
            provider_label="fixture",
            model_name="fixture-model",
            model_revision="rev-1",
            instruction_id="none",
            instruction_text="",
            dimension=4,
            normalized=True,
            document_template_version="1",
            backend_label="precomputed",
            backend_params=backend_params,
            random_seed=42,
            timestamp_utc="2026-08-27T00:00:00+00:00",
        )


def test_report_structure_is_deterministic():
    dataset = _dataset()
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="dev")
    manifest = _manifest(dataset)
    assert report_json(run, manifest) == report_json(run, manifest)
    markdown = report_markdown(run, manifest)
    assert "# Japanese Retrieval Evaluation Report" in markdown
    assert "## Per slice" in markdown


def test_fixture_is_privacy_safe_synthetic_and_never_points_at_vault():
    raw_text = FIXTURE.read_text(encoding="utf-8")
    assert "Vault" not in str(FIXTURE)
    assert "C:\\Users\\" not in raw_text
    assert "/home/" not in raw_text
    assert "実顧客ではない" in raw_text


def test_inactive_memory_is_present_only_as_fixture_state_not_must_hit():
    dataset = _dataset()
    inactive = {memory.memory_id for memory in dataset.memories if not memory.active}
    assert inactive == {"mem-036"}
    assert all(not (inactive & set(query.must_hit_ids)) for query in dataset.queries)
