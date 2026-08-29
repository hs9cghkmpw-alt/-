from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class RepositoryIdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryIdentity:
    head_sha: str
    tracked_worktree_clean: bool


def _sha40(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise RepositoryIdentityError(f"{field} must be a string")
    text = value.strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise RepositoryIdentityError(
            f"{field} must be a 40-character hexadecimal Git SHA"
        )
    return text


def verify_repository_identity(
    expected_sha: str,
    actual_head_sha: str,
    tracked_porcelain: str,
) -> RepositoryIdentity:
    expected = _sha40(expected_sha, "expected Git SHA")
    actual = _sha40(actual_head_sha, "actual Git HEAD")
    if actual != expected:
        raise RepositoryIdentityError(
            f"repository HEAD {actual} does not match frozen evaluator {expected}"
        )
    if not isinstance(tracked_porcelain, str):
        raise RepositoryIdentityError("tracked worktree status must be text")
    if tracked_porcelain.strip():
        raise RepositoryIdentityError(
            "formal blind evaluation requires a clean tracked Git worktree"
        )
    return RepositoryIdentity(head_sha=actual, tracked_worktree_clean=True)


def _run_git(
    repository_root: Path,
    args: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    try:
        completed = runner(
            ["git", "-C", str(repository_root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RepositoryIdentityError(
            f"unable to verify Git repository identity: {' '.join(args)}"
        ) from exc
    return completed.stdout


def require_frozen_repository(
    repository_root: Path,
    expected_sha: str,
) -> RepositoryIdentity:
    root = Path(repository_root).resolve()
    head = _run_git(root, ("rev-parse", "HEAD")).strip()
    tracked = _run_git(
        root,
        ("status", "--porcelain", "--untracked-files=no"),
    )
    return verify_repository_identity(expected_sha, head, tracked)
