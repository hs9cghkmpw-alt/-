from __future__ import annotations

import pytest

from brain_twin_eval.acceptance import retrieval_config_sha256
from brain_twin_eval.formal_config import retrieval_config_mapping
from brain_twin_eval.formal_config_code_pin import (
    dense_backend_params_with_code_pin,
    rerank_backend_params_with_code_pins,
)


def _config(backend_params, *, model_name="org/model", model_revision="a" * 40, backend="evaluation_exact_dense"):
    return retrieval_config_mapping(
        provider_label="sentence_transformers_local_eval",
        model_name=model_name,
        model_revision=model_revision,
        instruction_id="fixed",
        instruction_text="query: {query}",
        dimension=768,
        normalized=True,
        document_template_version="1",
        backend_label=backend,
        backend_params=backend_params,
    )


def test_code_dependency_revision_changes_formal_retrieval_identity() -> None:
    first = dense_backend_params_with_code_pin(
        query_template="query: {query}",
        document_template="{document}",
        code_repo_id="org/code",
        code_revision="b" * 40,
    )
    second = dense_backend_params_with_code_pin(
        query_template="query: {query}",
        document_template="{document}",
        code_repo_id="org/code",
        code_revision="c" * 40,
    )
    assert retrieval_config_sha256(_config(first)) != retrieval_config_sha256(_config(second))


def test_code_dependency_revision_is_validated_as_immutable() -> None:
    with pytest.raises(ValueError, match="40-character"):
        dense_backend_params_with_code_pin(
            query_template="{query}",
            document_template="{document}",
            code_repo_id="org/code",
            code_revision="main",
        )


def test_code_dependency_requires_pair() -> None:
    with pytest.raises(ValueError, match="code_repo_id"):
        dense_backend_params_with_code_pin(
            query_template="{query}",
            document_template="{document}",
            code_revision="b" * 40,
        )


def test_rerank_identity_binds_base_and_reranker_code_pins_independently() -> None:
    common = dict(
        base_model_name="org/base",
        base_model_revision="a" * 40,
        base_instruction_id="base-v1",
        base_query_template="Q:{query}",
        base_document_template="D:{document}",
        base_dimension=768,
        candidate_k=50,
        base_code_repo_id="org/base-code",
        base_code_revision="b" * 40,
        reranker_code_repo_id="org/rerank-code",
        reranker_code_revision="c" * 40,
    )
    first = rerank_backend_params_with_code_pins(**common)
    changed_base = rerank_backend_params_with_code_pins(
        **{**common, "base_code_revision": "d" * 40}
    )
    changed_reranker = rerank_backend_params_with_code_pins(
        **{**common, "reranker_code_revision": "e" * 40}
    )
    base_sha = retrieval_config_sha256(
        _config(
            first,
            model_name="org/reranker",
            model_revision="f" * 40,
            backend="evaluation_rerank",
        )
    )
    assert base_sha != retrieval_config_sha256(
        _config(
            changed_base,
            model_name="org/reranker",
            model_revision="f" * 40,
            backend="evaluation_rerank",
        )
    )
    assert base_sha != retrieval_config_sha256(
        _config(
            changed_reranker,
            model_name="org/reranker",
            model_revision="f" * 40,
            backend="evaluation_rerank",
        )
    )
