from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from brain_twin_eval.organizer_candidates import OrganizerCandidateError
from brain_twin_eval.organizer_run_evidence import (
    artifact_tree_fingerprint,
    machine_evidence,
    require_clean_git_head,
    verify_artifact_manifest,
)


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "brain_twin_organizer_pin.json"


def test_artifact_fingerprint_is_content_bound_and_ignores_manifest_and_hf_cache(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"a":1}', encoding="utf-8")
    (model / "weights.bin").write_bytes(b"weights-v1")
    cache = model / ".cache" / "huggingface"
    cache.mkdir(parents=True)
    (cache / "volatile.lock").write_text("one", encoding="utf-8")

    first = artifact_tree_fingerprint(model, manifest_name=MANIFEST)
    (model / MANIFEST).write_text("manifest changes are excluded", encoding="utf-8")
    (cache / "volatile.lock").write_text("two", encoding="utf-8")
    second = artifact_tree_fingerprint(model, manifest_name=MANIFEST)
    assert second == first

    (model / "weights.bin").write_bytes(b"weights-v2")
    third = artifact_tree_fingerprint(model, manifest_name=MANIFEST)
    assert third.sha256 != first.sha256
    assert third.file_count == first.file_count


def test_artifact_manifest_verification_detects_local_model_tamper(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.bin").write_bytes(b"1234")
    fingerprint = artifact_tree_fingerprint(model, manifest_name=MANIFEST)
    manifest = {
        "schema": 2,
        "artifact_sha256": fingerprint.sha256,
        "artifact_file_count": fingerprint.file_count,
        "artifact_bytes": fingerprint.total_bytes,
    }
    assert verify_artifact_manifest(model, manifest, manifest_name=MANIFEST) == fingerprint

    (model / "weights.bin").write_bytes(b"12345")
    with pytest.raises(OrganizerCandidateError, match="artifact"):
        verify_artifact_manifest(model, manifest, manifest_name=MANIFEST)


def test_artifact_manifest_schema1_is_rejected_for_new_evidence(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.bin").write_bytes(b"1234")
    with pytest.raises(OrganizerCandidateError, match="schema 2"):
        verify_artifact_manifest(model, {"schema": 1}, manifest_name=MANIFEST)


def test_clean_git_identity_rejects_tracked_changes(tmp_path: Path) -> None:
    def clean_runner(cmd, **kwargs):
        if cmd[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="a" * 40 + "\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    assert require_clean_git_head(tmp_path, runner=clean_runner) == "a" * 40

    def dirty_runner(cmd, **kwargs):
        if cmd[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="a" * 40 + "\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=" M brain-twin-2/x.py\n", stderr="")

    with pytest.raises(OrganizerCandidateError, match="clean tracked"):
        require_clean_git_head(tmp_path, runner=dirty_runner)


def test_machine_evidence_has_nonidentifying_resource_shape() -> None:
    evidence = machine_evidence()
    assert evidence["python"]
    assert "machine" in evidence
    assert "logical_cpu_count" in evidence
    assert "total_memory_bytes" in evidence
    assert "computer_name" not in evidence
    assert "username" not in evidence


def test_open_runner_binds_git_artifact_machine_and_unique_evidence_directory() -> None:
    runner = (ROOT / "scripts" / "run_organizer_open_matrix.py").read_text(encoding="utf-8")
    assert "require_clean_git_head" in runner
    assert "verify_artifact_manifest" in runner
    assert "machine_evidence" in runner
    assert "artifact_verification_ms" in runner
    assert 'strftime("%Y%m%d-%H%M%SZ")' in runner
    assert '"formal_blind_acceptance": False' in runner
    assert '"production_activation": False' in runner


def test_windows_core_runner_uses_one_python_process_per_candidate_and_cross_checks_identity() -> None:
    script = (ROOT / "scripts" / "run_organizer_core_windows.ps1").read_text(encoding="utf-8")
    assert '@("qwen3.5-0.8b", "qwen3.5-2b")' in script
    assert '"--candidate-id", $CandidateId' in script
    assert "Each candidate is a fresh Python process" in script
    assert "dataset_sha256" in script
    assert "git_commit" in script
    assert "process_isolation = $true" in script
    assert "formal_blind_acceptance = $false" in script
    assert "production_activation = $false" in script
    assert "--tier core" not in script


def test_smoke_handoff_uses_isolated_core_runner() -> None:
    script = (ROOT / "scripts" / "smoke_organizer_qwen08_windows.ps1").read_text(encoding="utf-8")
    assert "run_organizer_core_windows.ps1" in script
    assert "artifact" in script.lower()
