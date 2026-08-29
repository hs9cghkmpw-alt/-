from __future__ import annotations

from pathlib import Path

import pytest

from brain_twin_eval.organizer_candidates import OrganizerCandidateError, load_organizer_candidate_catalog
from brain_twin_eval.organizer_matrix import (
    load_organizer_model_matrix,
    organizer_candidate_directory_name,
)


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "evaluation_profiles" / "organizer_candidate_catalog_v1.json"
MATRIX = ROOT / "evaluation_profiles" / "organizer_model_matrix_v1.json"


def test_committed_organizer_matrix_keeps_small_qwen_models_in_core() -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    matrix = load_organizer_model_matrix(MATRIX, candidates)
    assert matrix.core == ("qwen3.5-0.8b", "qwen3.5-2b")
    assert matrix.extended == ("qwen3.5-4b", "qwen3-4b-instruct-2507")
    assert set(matrix.blocked) == {"phi-4-mini-instruct", "gemma-3-4b-it"}
    assert matrix.candidate_ids("all") == matrix.core + matrix.extended


def test_organizer_matrix_classifies_every_catalog_candidate_exactly_once() -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    matrix = load_organizer_model_matrix(MATRIX, candidates)
    combined = matrix.core + matrix.extended + matrix.blocked
    assert len(combined) == len(set(combined)) == len(candidates)
    assert set(combined) == {candidate.candidate_id for candidate in candidates}


def test_organizer_matrix_rejects_blocked_candidate_in_core(tmp_path: Path) -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    broken = tmp_path / "matrix.json"
    broken.write_text(
        '{"schema":1,"core":["phi-4-mini-instruct"],'
        '"extended":["qwen3.5-0.8b","qwen3.5-2b","qwen3.5-4b","qwen3-4b-instruct-2507"],'
        '"blocked":["gemma-3-4b-it"]}',
        encoding="utf-8",
    )
    with pytest.raises(OrganizerCandidateError, match="blocked candidate"):
        load_organizer_model_matrix(broken, candidates)


def test_candidate_directory_is_revision_specific() -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    candidate = next(item for item in candidates if item.candidate_id == "qwen3.5-0.8b")
    name = organizer_candidate_directory_name(candidate)
    assert name == f"organizer_qwen3.5-0.8b_{candidate.revision[:8]}"
