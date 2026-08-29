from __future__ import annotations

from pathlib import Path

from brain_twin_eval.privacy_paths import PrivateArtifactPathError, is_within, require_outside_repository


def test_repo_containment_detects_nested_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "private" / "judgements.json"
    assert is_within(nested, repo) is True
    assert is_within(tmp_path / "external" / "judgements.json", repo) is False


def test_private_artifact_guard_rejects_any_path_under_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    path = repo / "brain-twin-2" / "heldout.json"
    try:
        require_outside_repository(path, repo, label="held-out source")
    except PrivateArtifactPathError as exc:
        assert "held-out source" in str(exc)
        assert "outside the repository" in str(exc)
    else:
        raise AssertionError("expected PrivateArtifactPathError")


def test_private_artifact_guard_accepts_external_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    external = tmp_path / "blind-private" / "source.json"
    assert require_outside_repository(external, repo, label="source") == external.resolve()
