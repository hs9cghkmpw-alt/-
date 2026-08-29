from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain_twin_eval.candidate_catalog import catalog_from_mapping
from scripts.acquire_pa1_candidate_models import (
    _select,
    acquire_candidate,
    candidate_directory_name,
    default_model_root,
)


def _candidate(*, remote_code: bool = False, status: str = "ready"):
    item = {
        "candidate_id": "sample",
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
        "trust_remote_code": remote_code,
        "code_dependency": (
            {"repo_id": "org/custom-code", "revision": "b" * 40}
            if remote_code
            else None
        ),
        "runtime_status": status,
        "profile_strategy": "fixed",
    }
    return catalog_from_mapping({"schema": 2, "candidates": [item]})[0]


def test_default_model_root_uses_localappdata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_model_root() == tmp_path / "BrainTwin" / "models"


def test_candidate_directory_is_stable_and_revision_specific() -> None:
    candidate = _candidate()
    assert candidate_directory_name(candidate) == "sample_aaaaaaaa"


def test_acquire_standard_candidate_verifies_sha_and_writes_manifest(tmp_path: Path) -> None:
    candidate = _candidate()
    calls: list[dict] = []

    def repo_info_fn(**kwargs):
        calls.append({"info": kwargs})
        return SimpleNamespace(sha=candidate.revision)

    def snapshot_download_fn(**kwargs):
        calls.append({"download": kwargs})
        return kwargs["local_dir"]

    target = acquire_candidate(
        candidate,
        tmp_path,
        repo_info_fn=repo_info_fn,
        snapshot_download_fn=snapshot_download_fn,
    )
    manifest = json.loads((target / "brain_twin_model_pin.json").read_text(encoding="utf-8"))
    assert manifest["candidate_id"] == "sample"
    assert manifest["revision"] == "a" * 40
    assert manifest["code_dependency"] is None
    assert manifest["runtime_policy"] == "evaluation loads with local_files_only=True"
    assert calls[0]["info"] == {"repo_id": "org/model", "revision": "a" * 40}


def test_remote_code_acquisition_pins_and_populates_code_cache_but_remains_blocked(tmp_path: Path) -> None:
    candidate = _candidate(remote_code=True, status="requires_remote_code_smoke")
    calls: list[dict] = []
    cache_dir = tmp_path / "hf-cache-code"

    def repo_info_fn(**kwargs):
        calls.append({"info": kwargs})
        revision = "a" * 40 if kwargs["repo_id"] == "org/model" else "b" * 40
        return SimpleNamespace(sha=revision)

    def snapshot_download_fn(**kwargs):
        calls.append({"download": kwargs})
        if "local_dir" in kwargs:
            return kwargs["local_dir"]
        cache_dir.mkdir(parents=True, exist_ok=True)
        return str(cache_dir)

    target = acquire_candidate(
        candidate,
        tmp_path,
        repo_info_fn=repo_info_fn,
        snapshot_download_fn=snapshot_download_fn,
    )
    manifest = json.loads((target / "brain_twin_model_pin.json").read_text(encoding="utf-8"))
    assert candidate.acquirable is True
    assert candidate.runnable is False
    assert manifest["runtime_status"] == "requires_remote_code_smoke"
    assert manifest["code_dependency"] == {
        "repo_id": "org/custom-code",
        "revision": "b" * 40,
        "cache_policy": "huggingface-cache-for-local-files-only-resolution",
    }
    code_download = [
        call["download"] for call in calls if "download" in call and "local_dir" not in call["download"]
    ]
    assert code_download == [{"repo_id": "org/custom-code", "revision": "b" * 40}]


def test_revision_mismatch_stops_before_download(tmp_path: Path) -> None:
    candidate = _candidate()

    def repo_info_fn(**kwargs):
        return SimpleNamespace(sha="0" * 40)

    def snapshot_download_fn(**kwargs):  # pragma: no cover
        raise AssertionError("download must not run")

    with pytest.raises(RuntimeError, match="unexpected SHA"):
        acquire_candidate(
            candidate,
            tmp_path,
            repo_info_fn=repo_info_fn,
            snapshot_download_fn=snapshot_download_fn,
        )


def test_select_rejects_unknown_and_unacquirable_candidates() -> None:
    candidate = _candidate()
    with pytest.raises(ValueError, match="unknown candidate"):
        _select((candidate,), ["missing"])
