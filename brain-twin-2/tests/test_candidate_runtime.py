from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_twin_eval.candidate_runtime import (
    CandidateRuntimeError,
    DenseCandidateProfile,
    RerankerCandidateProfile,
    RerankingRetriever,
    load_local_cross_encoder,
    load_local_sentence_transformer,
    prepare_dense_candidate,
    stats_json,
)
from brain_twin_eval.dataset import dataset_from_mapping
from brain_twin_eval.runner import RankedResult


def _dataset():
    return dataset_from_mapping(
        {
            "version": "candidate-runtime-test",
            "judgement_visibility": "open",
            "memories": [
                {
                    "memory_id": "m-alpha",
                    "title": "Alpha",
                    "content": "alpha target",
                    "language_tags": ["en"],
                    "length_bucket": "short",
                    "active": True,
                },
                {
                    "memory_id": "m-beta",
                    "title": "Beta",
                    "content": "beta target",
                    "language_tags": ["en"],
                    "length_bucket": "short",
                    "active": True,
                },
                {
                    "memory_id": "m-off",
                    "title": "Inactive",
                    "content": "inactive",
                    "language_tags": ["en"],
                    "length_bucket": "short",
                    "active": False,
                },
            ],
            "queries": [
                {
                    "query_id": "q-alpha",
                    "text": "alpha",
                    "slice_tags": ["test"],
                    "relevance": {"m-alpha": 3, "m-beta": 0},
                    "must_hit_ids": ["m-alpha"],
                    "lexical_sufficient": True,
                    "adjudication_note": "test",
                    "split": "dev",
                }
            ],
        },
        require_all_slices=False,
    )


class FakeDenseModel:
    def encode(self, sentences, **kwargs):
        result = []
        for sentence in sentences:
            lowered = sentence.lower()
            if "alpha" in lowered:
                result.append([3.0, 0.0, 0.0])
            elif "beta" in lowered:
                result.append([0.0, 2.0, 0.0])
            else:
                result.append([0.0, 0.0, 1.0])
        return result


def _profile(**overrides):
    values = {
        "candidate_id": "fake-dense",
        "model_path": "X:/explicit/local/model",
        "model_name": "fake/model",
        "model_revision": "a" * 40,
        "instruction_id": "none",
        "query_template": "QUERY:{query}",
        "document_template": "{document}",
        "dimension": 2,
        "normalized": True,
        "batch_size": 4,
    }
    values.update(overrides)
    return DenseCandidateProfile(**values)


def test_dense_profile_requires_explicit_placeholders():
    with pytest.raises(ValueError, match="query_template"):
        _profile(query_template="missing")
    with pytest.raises(ValueError, match="document_template"):
        _profile(document_template="missing")


def test_prepare_dense_candidate_uses_active_memories_and_exact_ranking():
    dataset = _dataset()
    retriever, stats = prepare_dense_candidate(dataset, _profile(), model=FakeDenseModel())

    result = retriever.search("alpha", 10)
    assert [item.memory_id for item in result] == ["m-alpha", "m-beta"]
    assert stats.active_memory_count == 2
    assert stats.vector_dimension == 2
    assert stats.normalized is True
    assert stats.query_template_sha256
    assert stats.document_template_sha256


def test_dense_stats_never_persist_local_model_path_or_raw_template():
    _, stats = prepare_dense_candidate(_dataset(), _profile(), model=FakeDenseModel())
    serialized = stats_json(stats)
    assert "X:/explicit/local/model" not in serialized
    assert "QUERY:{query}" not in serialized
    assert json.loads(serialized)["model_revision"] == "a" * 40


def test_requested_dimension_cannot_exceed_native_output():
    with pytest.raises(CandidateRuntimeError, match="exceeds model output"):
        prepare_dense_candidate(_dataset(), _profile(dimension=4), model=FakeDenseModel())


def test_local_dense_loader_rejects_missing_path_before_import(tmp_path: Path):
    profile = _profile(model_path=str(tmp_path / "missing"))
    with pytest.raises(CandidateRuntimeError, match="automatic download is disabled"):
        load_local_sentence_transformer(profile)


class FakeBase:
    def search(self, query, k):
        return (
            RankedResult("m-alpha", 0.9),
            RankedResult("m-beta", 0.8),
        )[:k]


class FakeScorer:
    def score(self, query, documents):
        assert len(documents) == 2
        return (0.1, 0.9)


def test_reranker_reorders_only_within_frozen_candidate_pool():
    reranker = RerankingRetriever(
        dataset=_dataset(),
        base=FakeBase(),
        scorer=FakeScorer(),
        candidate_k=2,
    )
    result = reranker.search("alpha", 2)
    assert [item.memory_id for item in result] == ["m-beta", "m-alpha"]
    assert [item.score for item in result] == [0.9, 0.1]


class BadBase:
    def search(self, query, k):
        return (RankedResult("m-off", 1.0),)


def test_reranker_rejects_inactive_or_unknown_base_candidates():
    reranker = RerankingRetriever(
        dataset=_dataset(),
        base=BadBase(),
        scorer=FakeScorer(),
        candidate_k=2,
    )
    with pytest.raises(CandidateRuntimeError, match="unknown/inactive"):
        reranker.search("alpha", 2)


def test_local_cross_encoder_loader_rejects_missing_path_before_import(tmp_path: Path):
    profile = RerankerCandidateProfile(
        candidate_id="qwen-rerank",
        model_path=str(tmp_path / "missing"),
        model_name="Qwen/Qwen3-Reranker-0.6B",
        model_revision="b" * 40,
        instruction_id="brain-twin",
        instruction_text="memory relevance",
    )
    with pytest.raises(CandidateRuntimeError, match="automatic download is disabled"):
        load_local_cross_encoder(profile)
