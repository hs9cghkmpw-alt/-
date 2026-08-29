from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .acceptance import retrieval_config_sha256


DENSE_PROVIDER_LABEL = "sentence_transformers_local_eval"
DENSE_BACKEND_LABEL = "evaluation_exact_dense"
RERANK_PROVIDER_LABEL = "sentence_transformers_cross_encoder_local_eval"
RERANK_BACKEND_LABEL = "evaluation_rerank"


def text_sha256(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def dense_backend_params(
    *,
    query_template: str,
    document_template: str,
    evaluation_k: int | None = None,
    warm_repeats: int | None = None,
    active_memory_count: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "query_template_sha256": text_sha256(query_template),
        "document_template_sha256": text_sha256(document_template),
    }
    if evaluation_k is not None:
        params["evaluation_k"] = _positive_int(evaluation_k, "evaluation_k")
    if warm_repeats is not None:
        params["warm_repeats"] = _nonnegative_int(
            warm_repeats, "warm_repeats"
        )
    if active_memory_count is not None:
        params["corpus_memory_count"] = _positive_int(
            active_memory_count, "active_memory_count"
        )
    return params


def rerank_backend_params(
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
    evaluation_k: int | None = None,
    warm_repeats: int | None = None,
    active_memory_count: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "base_model_name": _nonempty(base_model_name, "base_model_name"),
        "base_model_revision": _nonempty(
            base_model_revision, "base_model_revision"
        ),
        "base_instruction_id": _nonempty(
            base_instruction_id, "base_instruction_id"
        ),
        "base_instruction_sha256": text_sha256(base_query_template),
        "base_document_template_sha256": text_sha256(
            base_document_template
        ),
        "base_dimension": _positive_int(base_dimension, "base_dimension"),
        "base_normalized": base_normalized,
        "candidate_k": _positive_int(candidate_k, "candidate_k"),
    }
    if not isinstance(base_normalized, bool):
        raise ValueError("base_normalized must be boolean")
    if base_candidate_id is not None:
        params["base_candidate_id"] = _nonempty(
            base_candidate_id, "base_candidate_id"
        )
    if evaluation_k is not None:
        params["evaluation_k"] = _positive_int(evaluation_k, "evaluation_k")
    if warm_repeats is not None:
        params["warm_repeats"] = _nonnegative_int(
            warm_repeats, "warm_repeats"
        )
    if active_memory_count is not None:
        params["corpus_memory_count"] = _positive_int(
            active_memory_count, "active_memory_count"
        )
    return params


def retrieval_config_mapping(
    *,
    provider_label: str,
    model_name: str,
    model_revision: str,
    instruction_id: str,
    instruction_text: str,
    dimension: int,
    normalized: bool,
    document_template_version: str,
    backend_label: str,
    backend_params: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "provider_label": provider_label,
        "model_name": model_name,
        "model_revision": model_revision,
        "instruction_id": instruction_id,
        "instruction_text_sha256": text_sha256(instruction_text),
        "dimension": dimension,
        "normalized": normalized,
        "document_template_version": document_template_version,
        "backend_label": backend_label,
        "backend_params": dict(backend_params),
    }


def config_sha256(**kwargs: Any) -> str:
    return retrieval_config_sha256(retrieval_config_mapping(**kwargs))
