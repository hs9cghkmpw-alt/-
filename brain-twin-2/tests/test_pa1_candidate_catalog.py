from __future__ import annotations

import json
from pathlib import Path

from brain_twin_eval.candidate_catalog import (
    CandidateCatalogError,
    catalog_from_mapping,
    load_catalog,
    unresolved_candidates,
)


def test_catalog_accepts_pinned_and_explicitly_unresolved_candidates() -> None:
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


def test_catalog_rejects_mutable_revision() -> None:
    try:
        catalog_from_mapping(
            {
                "schema": 1,
                "candidates": [
                    {
                        "candidate_id": "bad",
                        "role": "embedding",
                        "model_name": "org/model",
                        "revision": "main",
                        "enabled": True,
                        "notes": "",
                    }
                ],
            }
        )
    except CandidateCatalogError as exc:
        assert "mutable revision" in str(exc)
    else:
        raise AssertionError("expected CandidateCatalogError")


def test_catalog_rejects_duplicate_ids() -> None:
    raw_item = {
        "candidate_id": "same",
        "role": "embedding",
        "model_name": "org/model",
        "revision": None,
        "enabled": True,
        "notes": "",
    }
    try:
        catalog_from_mapping({"schema": 1, "candidates": [raw_item, dict(raw_item)]})
    except CandidateCatalogError as exc:
        assert "duplicate candidate_id" in str(exc)
    else:
        raise AssertionError("expected CandidateCatalogError")


def test_committed_challenger_catalog_is_valid_and_qwen_is_pinned() -> None:
    path = Path(__file__).parents[1] / "evaluation_profiles" / "challenger_catalog_v1.json"
    items = load_catalog(path)
    by_id = {item.candidate_id: item for item in items}
    assert by_id["qwen3-embedding-0.6b"].runnable is True
    assert by_id["qwen3-reranker-0.6b"].runnable is True
    assert "bge-m3" in by_id
    assert unresolved_candidates(items)
