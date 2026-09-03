"""Evidence hardening for organizer model evaluation.

Evaluation-only. This module never writes the production Vault or SQLite database.
It binds local model artifacts, Git state, and machine identity before Windows evidence
is interpreted as comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Callable, Sequence

from .organizer_candidates import OrganizerCandidateError, sha256_file


@dataclass(frozen=True)
class OrganizerArtifactFingerprint:
    sha256: str
    file_count: int
    total_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }


def artifact_tree_fingerprint(
    model_dir: Path,
    *,
    manifest_name: str,
) -> OrganizerArtifactFingerprint:
    """Hash the actual local model artifact tree, excluding volatile HF cache metadata.

    Every non-cache file contributes relative path, byte size, and full SHA-256. This is
    intentionally more expensive than trusting only the repo revision: a corrupted or
    locally modified weight/config file must change the evidence identity.
    """
    root = Path(model_dir).resolve()
    if not root.is_dir():
        raise OrganizerCandidateError(f"organizer model directory does not exist: {root}")

    records: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.as_posix() == manifest_name:
            continue
        if relative.parts and relative.parts[0] == ".cache":
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise OrganizerCandidateError(f"cannot stat organizer artifact file: {path}") from exc
        records.append((relative.as_posix(), int(size), sha256_file(path)))

    if not records:
        raise OrganizerCandidateError(f"organizer model artifact contains no hashable files: {root}")

    digest = hashlib.sha256()
    total_bytes = 0
    for relative, size, file_sha in records:
        total_bytes += size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return OrganizerArtifactFingerprint(
        sha256=digest.hexdigest(),
        file_count=len(records),
        total_bytes=total_bytes,
    )


def verify_artifact_manifest(
    model_dir: Path,
    manifest: dict[str, Any],
    *,
    manifest_name: str,
) -> OrganizerArtifactFingerprint:
    if manifest.get("schema") != 2:
        raise OrganizerCandidateError(
            "organizer pin manifest schema 2 is required for artifact-integrity evidence; reacquire the pinned model"
        )
    expected_sha = manifest.get("artifact_sha256")
    expected_files = manifest.get("artifact_file_count")
    expected_bytes = manifest.get("artifact_bytes")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise OrganizerCandidateError("organizer pin manifest has invalid artifact_sha256")
    if isinstance(expected_files, bool) or not isinstance(expected_files, int) or expected_files <= 0:
        raise OrganizerCandidateError("organizer pin manifest has invalid artifact_file_count")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes <= 0:
        raise OrganizerCandidateError("organizer pin manifest has invalid artifact_bytes")

    actual = artifact_tree_fingerprint(model_dir, manifest_name=manifest_name)
    if actual.sha256 != expected_sha:
        raise OrganizerCandidateError("organizer local model artifact SHA-256 does not match acquisition manifest")
    if actual.file_count != expected_files:
        raise OrganizerCandidateError("organizer local model artifact file count does not match acquisition manifest")
    if actual.total_bytes != expected_bytes:
        raise OrganizerCandidateError("organizer local model artifact byte count does not match acquisition manifest")
    return actual


def require_clean_git_head(
    repository_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    root = Path(repository_root).resolve()
    head = _git(root, ("rev-parse", "HEAD"), runner=runner).strip().lower()
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise OrganizerCandidateError("could not resolve a full immutable Git HEAD for organizer evidence")
    tracked = _git(
        root,
        ("status", "--porcelain", "--untracked-files=no"),
        runner=runner,
    )
    if tracked.strip():
        raise OrganizerCandidateError("organizer evidence requires a clean tracked Git worktree")
    return head


def machine_evidence() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "total_memory_bytes": _total_memory_bytes(),
    }


def _git(
    root: Path,
    args: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    try:
        completed = runner(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OrganizerCandidateError(f"git evidence command failed: {' '.join(args)}") from exc
    return completed.stdout


def _total_memory_bytes() -> int | None:
    if platform.system() == "Windows":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            if ok:
                return int(status.ullTotalPhys)
        except Exception:
            return None
        return None

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages) * int(page_size)
    except (AttributeError, OSError, ValueError):
        return None
