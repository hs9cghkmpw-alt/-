from __future__ import annotations

from pathlib import Path


class PrivateArtifactPathError(ValueError):
    pass


def is_within(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def require_outside_repository(
    path: str | Path,
    repository_root: str | Path,
    *,
    label: str,
) -> Path:
    resolved = Path(path).resolve()
    if is_within(resolved, repository_root):
        raise PrivateArtifactPathError(
            f"{label} must be outside the repository: {resolved}"
        )
    return resolved
