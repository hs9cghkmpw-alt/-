from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import acquire_organizer_models as acquire  # noqa: E402
from brain_twin_eval.organizer_candidates import OrganizerCandidateError, load_organizer_candidate_catalog  # noqa: E402


CATALOG = ROOT / "evaluation_profiles" / "organizer_candidate_catalog_v1.json"
MATRIX = ROOT / "evaluation_profiles" / "organizer_model_matrix_v1.json"


def _candidate(candidate_id: str):
    return next(
        candidate
        for candidate in load_organizer_candidate_catalog(CATALOG)
        if candidate.candidate_id == candidate_id
    )


def test_default_selection_is_core_only() -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    selected = acquire._select(
        candidates=candidates,
        matrix_path=MATRIX,
        tier="core",
        explicit_ids=[],
    )
    assert [candidate.candidate_id for candidate in selected] == ["qwen3.5-0.8b", "qwen3.5-2b"]


def test_explicit_blocked_candidate_is_refused() -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    with pytest.raises(OrganizerCandidateError, match="blocked"):
        acquire._select(
            candidates=candidates,
            matrix_path=MATRIX,
            tier="core",
            explicit_ids=["phi-4-mini-instruct"],
        )


def test_acquisition_verifies_exact_sha_and_writes_local_only_manifest(tmp_path: Path) -> None:
    candidate = _candidate("qwen3.5-0.8b")
    calls: list[dict[str, object]] = []

    def repo_info_fn(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(sha=candidate.revision)

    def snapshot_download_fn(**kwargs):
        target = Path(str(kwargs["local_dir"]))
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}", encoding="utf-8")
        return str(target)

    target = acquire.acquire_organizer_candidate(
        candidate,
        tmp_path,
        catalog_sha256="a" * 64,
        repo_info_fn=repo_info_fn,
        snapshot_download_fn=snapshot_download_fn,
    )
    manifest = json.loads((target / "brain_twin_organizer_pin.json").read_text(encoding="utf-8"))
    assert calls == [{"repo_id": candidate.model_name, "revision": candidate.revision}]
    assert manifest["candidate_id"] == candidate.candidate_id
    assert manifest["revision"] == candidate.revision
    assert manifest["runtime_policy"] == "evaluation-loads-local-files-only"
    assert manifest["trust_remote_code"] is False


def test_acquisition_stops_on_remote_revision_mismatch(tmp_path: Path) -> None:
    candidate = _candidate("qwen3.5-0.8b")
    with pytest.raises(OrganizerCandidateError, match="unexpected SHA"):
        acquire.acquire_organizer_candidate(
            candidate,
            tmp_path,
            catalog_sha256="a" * 64,
            repo_info_fn=lambda **_: SimpleNamespace(sha="0" * 40),
            snapshot_download_fn=lambda **_: pytest.fail("download must not start after SHA mismatch"),
        )
