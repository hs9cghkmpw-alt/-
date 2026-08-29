from __future__ import annotations

from typing import Any

from .formal_config import dense_backend_params, rerank_backend_params


def implementation_dependency(repo_id: str | None, revision: str | None) -> dict[str, str] | None:
    if repo_id is None and revision is None:
        return None
    if not isinstance(repo_id, str) or not repo_id.strip():
        raise ValueError("code_repo_id must be supplied with code_revision")
    if not isinstance(revision, str):
        raise ValueError("code_revision must be supplied with code_repo_id")
    normalized = revision.lower()
    if len(normalized) != 40 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError("code_revision must be a full immutable 40-character commit SHA")
    return {"repo_id": repo_id, "model_revision": normalized}


def dense_backend_params_with_code_pin(
    *,
    query_template: str,
    document_template: str,
    code_repo_id: str | None = None,
    code_revision: str | None = None,
    evaluation_k: int | None = None,
    warm_repeats: int | None = None,
    active_memory_count: int | None = None,
) -> dict[str, Any]:
    """Build dense behavior params and bind an optional immutable implementation pin."""
    params = dense_backend_params(
        query_template=query_template,
        document_template=document_template,
        evaluation_k=evaluation_k,
        warm_repeats=warm_repeats,
        active_memory_count=active_memory_count,
    )
    dependency = implementation_dependency(code_repo_id, code_revision)
    if dependency is not None:
        params["implementation_dependency"] = dependency
    return params


def rerank_backend_params_with_code_pins(
    *,
    base_model_name: str,
    base_model_revision: str,
    base_instruction_id: str,
    base_query_template: str,
    base_document_template: str,
    base_dimension: int,
    candidate_k: int,
    base_normalized: bool = True,
    base_candidate_id: str | None = None,
    base_code_repo_id: str | None = None,
    base_code_revision: str | None = None,
    reranker_code_repo_id: str | None = None,
    reranker_code_revision: str | None = None,
    evaluation_k: int | None = None,
    warm_repeats: int | None = None,
    active_memory_count: int | None = None,
) -> dict[str, Any]:
    params = rerank_backend_params(
        base_model_name=base_model_name,
        base_model_revision=base_model_revision,
        base_instruction_id=base_instruction_id,
        base_query_template=base_query_template,
        base_document_template=base_document_template,
        base_dimension=base_dimension,
        candidate_k=candidate_k,
        base_normalized=base_normalized,
        base_candidate_id=base_candidate_id,
        evaluation_k=evaluation_k,
        warm_repeats=warm_repeats,
        active_memory_count=active_memory_count,
    )
    base_dependency = implementation_dependency(base_code_repo_id, base_code_revision)
    if base_dependency is not None:
        params["base_implementation_dependency"] = base_dependency
    reranker_dependency = implementation_dependency(
        reranker_code_repo_id, reranker_code_revision
    )
    if reranker_dependency is not None:
        params["reranker_implementation_dependency"] = reranker_dependency
    return params
