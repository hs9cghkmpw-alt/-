from __future__ import annotations

from brain_twin_eval.repo_identity import (
    RepositoryIdentityError,
    verify_repository_identity,
)


def test_repository_identity_accepts_exact_clean_head() -> None:
    identity = verify_repository_identity(
        "a" * 40,
        "a" * 40,
        "",
    )
    assert identity.head_sha == "a" * 40
    assert identity.tracked_worktree_clean is True


def test_repository_identity_rejects_head_mismatch() -> None:
    try:
        verify_repository_identity("a" * 40, "b" * 40, "")
    except RepositoryIdentityError as exc:
        assert "does not match frozen evaluator" in str(exc)
    else:
        raise AssertionError("expected RepositoryIdentityError")


def test_repository_identity_rejects_tracked_worktree_changes() -> None:
    try:
        verify_repository_identity(
            "a" * 40,
            "a" * 40,
            " M brain-twin-2/brain_twin_eval/acceptance.py\n",
        )
    except RepositoryIdentityError as exc:
        assert "clean tracked Git worktree" in str(exc)
    else:
        raise AssertionError("expected RepositoryIdentityError")
