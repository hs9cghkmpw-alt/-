from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.acquire_pa1_qwen_models import (
    PINS,
    QWEN3_EMBEDDING_REVISION,
    QWEN3_RERANKER_REVISION,
    acquire_one,
    default_model_root,
)


def test_pins_use_full_immutable_commit_shas():
    for revision in (QWEN3_EMBEDDING_REVISION, QWEN3_RERANKER_REVISION):
        assert len(revision) == 40
        int(revision, 16)


def test_default_model_root_uses_localappdata_on_windows_shape(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_model_root() == tmp_path / "BrainTwin" / "models"


def test_acquire_one_verifies_remote_sha_and_writes_nonsecret_pin_manifest(tmp_path: Path):
    pin = PINS[0]
    calls = {}

    def repo_info_fn(**kwargs):
        calls["info"] = kwargs
        return SimpleNamespace(sha=pin.revision)

    def snapshot_download_fn(**kwargs):
        calls["download"] = kwargs
        return kwargs["local_dir"]

    target = acquire_one(
        pin,
        tmp_path,
        repo_info_fn=repo_info_fn,
        snapshot_download_fn=snapshot_download_fn,
    )

    assert calls["info"] == {"repo_id": pin.repo_id, "revision": pin.revision}
    assert calls["download"]["repo_id"] == pin.repo_id
    assert calls["download"]["revision"] == pin.revision
    assert calls["download"]["local_dir"] == str(target)

    manifest = json.loads((target / "brain_twin_model_pin.json").read_text(encoding="utf-8"))
    assert manifest["repo_id"] == pin.repo_id
    assert manifest["revision"] == pin.revision
    assert manifest["runtime_policy"] == "evaluation loads with local_files_only=True"
    serialized = json.dumps(manifest)
    assert str(tmp_path) not in serialized
    assert "token" not in serialized.lower()


def test_acquire_one_refuses_revision_resolution_mismatch(tmp_path: Path):
    pin = PINS[0]

    def repo_info_fn(**kwargs):
        return SimpleNamespace(sha="0" * 40)

    def snapshot_download_fn(**kwargs):  # pragma: no cover - must not be called
        raise AssertionError("download must not run after revision mismatch")

    with pytest.raises(RuntimeError, match="unexpected SHA"):
        acquire_one(
            pin,
            tmp_path,
            repo_info_fn=repo_info_fn,
            snapshot_download_fn=snapshot_download_fn,
        )
