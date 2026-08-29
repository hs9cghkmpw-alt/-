from __future__ import annotations

from pathlib import Path


def test_freeze_cli_can_bind_model_and_reranker_implementation_revisions() -> None:
    script = (
        Path(__file__).parents[1] / "scripts" / "freeze_pa1_retrieval_config.py"
    ).read_text(encoding="utf-8")
    assert "--model-code-repo-id" in script
    assert "--model-code-revision" in script
    assert "--reranker-code-repo-id" in script
    assert "--reranker-code-revision" in script
    assert "dense_backend_params_with_code_pin" in script
    assert "rerank_backend_params_with_code_pins" in script
    assert '"implementation_dependency_bound"' in script


def test_remote_code_smoke_cli_does_not_modify_candidate_catalog() -> None:
    script = (
        Path(__file__).parents[1] / "scripts" / "smoke_pa1_remote_code_candidate.py"
    ).read_text(encoding="utf-8")
    assert "run_remote_code_smoke" in script
    assert "candidate remains blocked" in script
    assert "formal_blind_acceptance" in script
    assert "production_activation" in script
    assert "update_file" not in script
    assert "challenger_catalog_v1.json" in script
