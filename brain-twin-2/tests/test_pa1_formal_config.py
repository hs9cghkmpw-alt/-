from __future__ import annotations

from brain_twin_eval.acceptance import retrieval_config_sha256
from brain_twin_eval.formal_config import (
    DENSE_BACKEND_LABEL,
    DENSE_PROVIDER_LABEL,
    RERANK_BACKEND_LABEL,
    RERANK_PROVIDER_LABEL,
    dense_backend_params,
    rerank_backend_params,
    retrieval_config_mapping,
)


def _dense_config(params):
    return retrieval_config_mapping(
        provider_label=DENSE_PROVIDER_LABEL,
        model_name="org/embed",
        model_revision="a" * 40,
        instruction_id="instruction-v1",
        instruction_text="Retrieve relevant memory: {query}",
        dimension=768,
        normalized=True,
        document_template_version="1",
        backend_label=DENSE_BACKEND_LABEL,
        backend_params=params,
    )


def test_dense_formal_config_can_be_frozen_without_blind_dataset_shape() -> None:
    behavior = dense_backend_params(
        query_template="Retrieve relevant memory: {query}",
        document_template="{document}",
    )
    runtime = dense_backend_params(
        query_template="Retrieve relevant memory: {query}",
        document_template="{document}",
        evaluation_k=10,
        warm_repeats=30,
        active_memory_count=360,
    )
    assert retrieval_config_sha256(
        _dense_config(behavior)
    ) == retrieval_config_sha256(_dense_config(runtime))


def _rerank_config(params):
    return retrieval_config_mapping(
        provider_label=RERANK_PROVIDER_LABEL,
        model_name="org/reranker",
        model_revision="b" * 40,
        instruction_id="rerank-v1",
        instruction_text="Judge memory relevance.",
        dimension=768,
        normalized=True,
        document_template_version="1",
        backend_label=RERANK_BACKEND_LABEL,
        backend_params=params,
    )


def test_reranker_frozen_config_tracks_base_document_contract_and_candidate_k() -> None:
    first = rerank_backend_params(
        base_model_name="org/embed",
        base_model_revision="a" * 40,
        base_instruction_id="embed-v1",
        base_query_template="Q:{query}",
        base_document_template="D:{document}",
        base_dimension=768,
        base_normalized=True,
        candidate_k=50,
    )
    changed_document = rerank_backend_params(
        base_model_name="org/embed",
        base_model_revision="a" * 40,
        base_instruction_id="embed-v1",
        base_query_template="Q:{query}",
        base_document_template="DOCUMENT:{document}",
        base_dimension=768,
        base_normalized=True,
        candidate_k=50,
    )
    changed_k = dict(first)
    changed_k["candidate_k"] = 100

    first_sha = retrieval_config_sha256(_rerank_config(first))
    assert first_sha != retrieval_config_sha256(
        _rerank_config(changed_document)
    )
    assert first_sha != retrieval_config_sha256(
        _rerank_config(changed_k)
    )


def test_runtime_labels_do_not_change_retrieval_identity() -> None:
    first = rerank_backend_params(
        base_model_name="org/embed",
        base_model_revision="a" * 40,
        base_instruction_id="embed-v1",
        base_query_template="{query}",
        base_document_template="{document}",
        base_dimension=768,
        candidate_k=50,
        base_candidate_id="candidate-a",
        evaluation_k=10,
        warm_repeats=30,
        active_memory_count=360,
    )
    second = dict(first)
    second["base_candidate_id"] = "candidate-renamed"
    second["warm_repeats"] = 60
    second["corpus_memory_count"] = 500
    second["evaluation_k"] = 20

    assert retrieval_config_sha256(
        _rerank_config(first)
    ) == retrieval_config_sha256(_rerank_config(second))
