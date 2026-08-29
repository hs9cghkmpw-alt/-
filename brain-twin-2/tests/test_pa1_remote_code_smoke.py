from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from brain_twin_eval.candidate_catalog import catalog_from_mapping
from brain_twin_eval.remote_code_smoke import (
    RemoteCodeSmokeError,
    expected_model_dir,
    run_remote_code_smoke,
    validate_pin_manifest,
)


def _candidate():
    return catalog_from_mapping(
        {
            "schema": 2,
            "candidates": [
                {
                    "candidate_id": "remote-model",
                    "role": "embedding",
                    "model_name": "org/model",
                    "revision": "a" * 40,
                    "enabled": True,
                    "notes": "",
                    "loader": "sentence_transformers_dense",
                    "native_dimension": 3,
                    "allowed_dimensions": [3],
                    "max_sequence_length": 512,
                    "query_template_file": "q.txt",
                    "document_template_file": "d.txt",
                    "trust_remote_code": True,
                    "code_dependency": {
                        "repo_id": "org/code",
                        "revision": "b" * 40,
                    },
                    "runtime_status": "requires_remote_code_smoke",
                    "profile_strategy": "fixed",
                }
            ],
        }
    )[0]


def _write_pin(candidate, root: Path) -> Path:
    model_dir = expected_model_dir(candidate, root)
    model_dir.mkdir(parents=True)
    (model_dir / "brain_twin_model_pin.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "candidate_id": candidate.candidate_id,
                "role": "embedding",
                "repo_id": candidate.model_name,
                "revision": candidate.revision,
                "runtime_status": candidate.runtime_status,
                "trust_remote_code": True,
                "code_dependency": {
                    "repo_id": candidate.code_dependency.repo_id,
                    "revision": candidate.code_dependency.revision,
                    "cache_policy": "huggingface-cache-for-local-files-only-resolution",
                },
            }
        ),
        encoding="utf-8",
    )
    return model_dir


def test_pin_manifest_must_match_both_model_and_code_revisions(tmp_path: Path) -> None:
    candidate = _candidate()
    model_dir = _write_pin(candidate, tmp_path)
    manifest = validate_pin_manifest(candidate, model_dir)
    assert manifest["revision"] == "a" * 40
    assert manifest["code_dependency"]["revision"] == "b" * 40

    manifest["code_dependency"]["revision"] = "c" * 40
    (model_dir / "brain_twin_model_pin.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RemoteCodeSmokeError, match="code_dependency.revision"):
        validate_pin_manifest(candidate, model_dir)


class FakeModel:
    def encode(self, sentences, **kwargs):
        assert sentences == ["札幌で以前話していた予定を思い出したい"]
        assert kwargs["batch_size"] == 1
        assert kwargs["normalize_embeddings"] is True
        return [[1.0, 0.0, 0.0]]


def test_smoke_is_offline_pinned_and_never_promotes_catalog_status(tmp_path: Path, monkeypatch) -> None:
    candidate = _candidate()
    model_dir = _write_pin(candidate, tmp_path)
    seen = {}
    monkeypatch.setenv("HF_HUB_OFFLINE", "previous")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    def factory(path: Path, code_revision: str):
        seen["path"] = path
        seen["code_revision"] = code_revision
        seen["hf_offline"] = os.environ["HF_HUB_OFFLINE"]
        seen["transformers_offline"] = os.environ["TRANSFORMERS_OFFLINE"]
        return FakeModel()

    result = run_remote_code_smoke(candidate, model_root=tmp_path, model_factory=factory)
    assert seen == {
        "path": model_dir,
        "code_revision": "b" * 40,
        "hf_offline": "1",
        "transformers_offline": "1",
    }
    assert result.observed_dimension == 3
    assert result.local_files_only is True
    assert result.catalog_status_after_smoke == "requires_remote_code_smoke"
    assert os.environ["HF_HUB_OFFLINE"] == "previous"
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    serialized = result.to_json()
    assert str(model_dir) not in serialized


def test_smoke_rejects_wrong_dimension(tmp_path: Path) -> None:
    candidate = _candidate()
    _write_pin(candidate, tmp_path)

    class WrongDimension:
        def encode(self, sentences, **kwargs):
            return [[1.0, 0.0]]

    with pytest.raises(RemoteCodeSmokeError, match="dimension mismatch"):
        run_remote_code_smoke(
            candidate,
            model_root=tmp_path,
            model_factory=lambda _path, _revision: WrongDimension(),
        )


def test_smoke_rejects_non_normalized_output(tmp_path: Path) -> None:
    candidate = _candidate()
    _write_pin(candidate, tmp_path)

    class BadNorm:
        def encode(self, sentences, **kwargs):
            return [[2.0, 0.0, 0.0]]

    with pytest.raises(RemoteCodeSmokeError, match="normalized embedding contract failed"):
        run_remote_code_smoke(
            candidate,
            model_root=tmp_path,
            model_factory=lambda _path, _revision: BadNorm(),
        )
