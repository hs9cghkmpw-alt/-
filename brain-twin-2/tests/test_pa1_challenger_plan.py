from __future__ import annotations

from pathlib import Path

from brain_twin_eval.candidate_catalog import load_catalog
from brain_twin_eval.challenger_plan import build_challenger_plan


def test_committed_challenger_plan_is_deterministic_and_fail_closed() -> None:
    root = Path(__file__).parents[1]
    candidates = load_catalog(root / "evaluation_profiles" / "challenger_catalog_v1.json")
    first = build_challenger_plan(candidates, project_root=root)
    second = build_challenger_plan(candidates, project_root=root)
    assert first == second

    ids = [run.candidate_id for run in first]
    assert "qwen3-embedding-0.6b" not in ids
    assert ids.count("nomic-embed-text-v2-moe") == 2
    assert ids.count("gte-multilingual-base") == 1

    blocked = {run.candidate_id for run in first if not run.runnable}
    assert blocked == {"nomic-embed-text-v2-moe", "gte-multilingual-base"}
    ready = {run.candidate_id for run in first if run.runnable}
    assert ready == {
        "bge-m3",
        "multilingual-e5-base",
        "multilingual-e5-large-instruct",
        "multilingual-minilm-control",
    }


def test_plan_preserves_only_reviewed_dimension_options() -> None:
    root = Path(__file__).parents[1]
    candidates = load_catalog(root / "evaluation_profiles" / "challenger_catalog_v1.json")
    runs = build_challenger_plan(candidates, project_root=root)
    dimensions = {}
    for run in runs:
        dimensions.setdefault(run.candidate_id, []).append(run.dimension)
    assert dimensions["bge-m3"] == [1024]
    assert dimensions["multilingual-e5-base"] == [768]
    assert dimensions["multilingual-e5-large-instruct"] == [1024]
    assert dimensions["nomic-embed-text-v2-moe"] == [768, 256]
    assert dimensions["gte-multilingual-base"] == [768]
    assert dimensions["multilingual-minilm-control"] == [384]
