from __future__ import annotations

from brain_twin_eval.acceptance import AcceptancePolicyError, retrieval_config_sha256


def test_retrieval_config_rejects_mutable_nested_base_model_revision() -> None:
    manifest = {
        "provider_label": "rerank",
        "model_name": "org/reranker",
        "model_revision": "a" * 40,
        "instruction_id": "rerank-v1",
        "instruction_text_sha256": "b" * 64,
        "dimension": 1024,
        "normalized": True,
        "document_template_version": "1",
        "backend_label": "evaluation_rerank",
        "backend_params": {"base_model_revision": "main"},
    }
    try:
        retrieval_config_sha256(manifest)
    except AcceptancePolicyError as exc:
        assert "base_model_revision" in str(exc)
    else:
        raise AssertionError("expected AcceptancePolicyError")
