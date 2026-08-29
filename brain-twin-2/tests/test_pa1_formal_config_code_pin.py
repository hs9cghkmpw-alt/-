from __future__ import annotations

import pytest

from brain_twin_eval.acceptance import retrieval_config_sha256
from brain_twin_eval.formal_config import retrieval_config_mapping
from brain_twin_eval.formal_config_code_pin import dense_backend_params_with_code_pin


def _config(backend_params):
    return retrieval_config_mapping(
        provider_label="sentence_transformers_local_eval",
        model_name="org/model",
        model_revision="a" * 40,
        instruction_id="fixed",
        instruction_text="query: {query}",
        dimension=768,
        normalized=True,
        document_template_version="1",
        backend_label="evaluation_exact_dense",
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
