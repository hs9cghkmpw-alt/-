from __future__ import annotations

from pathlib import Path

from brain_twin_eval.matrix_summary import summary_markdown


def _script(name: str) -> str:
    return (Path(__file__).parents[1] / "scripts" / name).read_text(encoding="utf-8")


def test_challenger_runner_has_clean_head_and_fresh_evidence_guards() -> None:
    text = _script("run_pa1_challenger_matrix.ps1")
    assert "git status --porcelain --untracked-files=no" in text
    assert "git rev-parse HEAD" in text
    assert "Output directory is not empty" in text
    assert "pa1-challenger-matrix" in text


def test_challenger_runner_only_acquires_reviewed_ready_candidates() -> None:
    text = _script("run_pa1_challenger_matrix.ps1")
    for candidate_id in (
        "bge-m3",
        "multilingual-e5-base",
        "multilingual-e5-large-instruct",
        "multilingual-minilm-control",
    ):
        assert f'"{candidate_id}"' in text
    assert "acquire_pa1_candidate_models.py" in text
    assert "remote-code candidate escaped the smoke gate" in text
    assert "nomic-embed-text-v2-moe" not in text
    assert "gte-multilingual-base" not in text


def test_challenger_runner_uses_catalog_plan_and_local_candidate_pipeline() -> None:
    text = _script("run_pa1_challenger_matrix.ps1")
    plan_index = text.index("plan_pa1_challengers.py")
    run_index = text.index("run_local_candidate_pipeline.py")
    assert plan_index < run_index
    assert "Where-Object { $_.runnable -eq $true }" in text
    assert "--query-template-file" in text
    assert "--document-template-file" in text
    assert "--split dev" in text
    assert "--git-commit $GitCommit" in text


def test_full_runner_reuses_one_runtime_and_combines_both_matrices() -> None:
    text = _script("run_pa1_full_open_matrix.ps1")
    assert "run_pa1_qwen_matrix.ps1" in text
    assert "run_pa1_challenger_matrix.ps1" in text
    assert 'SkipInstall = $true' in text
    assert "summarize_pa1_open_matrix.py" in text
    assert "combined_matrix_summary.md" in text
    assert "formal_blind_acceptance = $false" in text
    assert "production_activation = $false" in text


def test_generic_open_summary_no_longer_claims_every_matrix_is_qwen() -> None:
    summary = {
        "dataset_version": "v2",
        "dataset_sha256": "abc",
        "git_commit": "1" * 40,
        "split": "dev",
        "entry_count": 0,
        "entries": [],
        "dense_winner": None,
        "overall_open_winner": None,
    }
    rendered = summary_markdown(summary)
    assert rendered.startswith("# PA1 Open Matrix Summary")
    assert "PA1 Qwen Open Matrix Summary" not in rendered
