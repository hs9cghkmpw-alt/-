from __future__ import annotations

from typing import Any

from .formal_config import dense_backend_params


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
    if code_repo_id is None and code_revision is None:
        return params
    if not isinstance(code_repo_id, str) or not code_repo_id.strip():
        raise ValueError("code_repo_id must be supplied with code_revision")
    if not isinstance(code_revision, str):
        raise ValueError("code_revision must be supplied with code_repo_id")
    revision = code_revision.lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise ValueError("code_revision must be a full immutable 40-character commit SHA")
    params["implementation_dependency"] = {
        "repo_id": code_repo_id,
        "model_revision": revision,
    }
    return params
