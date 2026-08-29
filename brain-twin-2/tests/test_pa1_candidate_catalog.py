from __future__ import annotations

from pathlib import Path

from brain_twin_eval.candidate_catalog import (
    CandidateCatalogError,
    blocked_candidates,
    catalog_from_mapping,
    load_catalog,
    runnable_embeddings,
    unresolved_candidates,
)


def test_schema1_catalog_remains_backward_compatible() -> None:
    items = catalog_from_mapping(
        {
            "schema": 1,
            "candidates": [
                {
                    "candidate_id": "pinned",
                    "role": "embedding",
                    "model_name": "org/model",
                    "revision": "a" * 40,
                    "enabled": True,
                    "notes": "ready",
                },
                {
                    "candidate_id": "pending",
                    "role": "embedding",
                    "model_name": "org/other",
                    "revision": None,
                    "enabled": True,
                    "notes": "must pin before run",
                },
            ],
        }
    )
    assert items[0].runnable is True
    assert items[1].runnable is False
    assert [item.candidate_id for item in unresolved_candidates(items)] == ["pending"]


def _embedding(**overrides):
    item = {
        "candidate_id": "candidate",
        "role": "embedding",
        "model_name": "org/model",
        "revision": "a" * 40,
        "enabled": True,
        "notes": "",
        "loader": "sentence_transformers_dense",
        "native_dimension": 768,
        "allowed_dimensions": [768],
        "max_sequence_length": 512,
        "query_template_file": "q.txt",
        "document_template_file": "d.txt",
        "trust_remote_code": False,
        "code_dependency": None,
        "runtime_status": "ready",
        "profile_strategy": "fixed",
    }
    item.update(overrides)
    return item


def test_catalog_rejects_mutable_revision() -> None:
    try:
        catalog_from_mapping({"schema": 2, "candidates": [_embedding(revision="main")]})
    except CandidateCatalogError as exc:
        assert "mutable revision" in str(exc)
    else:
        raise AssertionError("expected CandidateCatalogError")


def test_catalog_rejects_duplicate_ids() -> None:
    item = _embedding()
    try:
        catalog_from_mapping({"schema": 2, "candidates": [item, dict(item)]})
    except CandidateCatalogError as exc:
        assert "duplicate candidate_id" in str(exc)
    else:
        raise AssertionError("expected CandidateCatalogError")


def test_remote_code_requires_an_immutable_code_dependency() -> None:
    try:
        catalog_from_mapping(
            {
                "schema": 2,
                "candidates": [
                    _embedding(trust_remote_code=True, code_dependency=None)
                ],
            }
        )
    except CandidateCatalogError as exc:
        assert "code_dependency" in str(exc)
    else:
        raise AssertionError("expected CandidateCatalogError")


def test_remote_code_smoke_status_fails_closed_for_execution() -> None:
    item = catalog_from_mapping(
        {
            "schema": 2,
            "candidates": [
                _embedding(
                    trust_remote_code=True,
                    code_dependency={"repo_id": "org/code", "revision": "b" * 40},
                    runtime_status="requires_remote_code_smoke",
                )
            ],
        }
    )[0]
    assert item.acquirable is True
    assert item.runnable is False


def test_dimensions_cannot_exceed_native_dimension() -> None:
    try:
        catalog_from_mapping(
            {"schema": 2, "candidates": [_embedding(allowed_dimensions=[1024])]}
        )
    except CandidateCatalogError as exc:
        assert "native_dimension" in str(exc)
    else:
        raise AssertionError("expected CandidateCatalogError")


def test_committed_challenger_catalog_is_fully_pinned_and_fail_closed() -> None:
    root = Path(__file__).parents[1]
    path = root / "evaluation_profiles" / "challenger_catalog_v1.json"
    items = load_catalog(path)
    by_id = {item.candidate_id: item for item in items}

    assert unresolved_candidates(items) == ()
    assert by_id["qwen3-embedding-0.6b"].runnable is True
    assert by_id["qwen3-reranker-0.6b"].runnable is True
    assert by_id["bge-m3"].revision == "9a0624b896d81da7492a910ffa53731274b6cf3d"
    assert by_id["multilingual-e5-base"].revision == "d128750597153bb5987e10b1c3493a34e5a4502a"
    assert by_id["multilingual-e5-large-instruct"].revision == "274baa43b0e13e37fafa6428dbc7938e62e5c439"
    assert by_id["nomic-embed-text-v2-moe"].revision == "e89d1c9283c98dbd18f5003dc625394293978922"
    assert by_id["gte-multilingual-base"].revision == "9bbca17d9273fd0d03d5725c7a4b0f6b45142062"
    assert by_id["multilingual-minilm-control"].revision == "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"

    blocked = {item.candidate_id for item in blocked_candidates(items)}
    assert blocked == {"nomic-embed-text-v2-moe", "gte-multilingual-base"}
    ready_embeddings = {item.candidate_id for item in runnable_embeddings(items)}
    assert {
        "qwen3-embedding-0.6b",
        "bge-m3",
        "multilingual-e5-base",
        "multilingual-e5-large-instruct",
        "multilingual-minilm-control",
    } <= ready_embeddings

    for item in items:
        if item.query_template_file:
            assert (root / item.query_template_file).is_file()
        if item.document_template_file:
            assert (root / item.document_template_file).is_file()

    nomic_code = by_id["nomic-embed-text-v2-moe"].code_dependency
    assert nomic_code is not None
    assert nomic_code.revision == "7710840340a098cfb869c4f65e87cf2b1b70caca"
    gte_code = by_id["gte-multilingual-base"].code_dependency
    assert gte_code is not None
    assert gte_code.revision == "40ced75c3017eb27626c9d4ea981bde21a2662f4"
