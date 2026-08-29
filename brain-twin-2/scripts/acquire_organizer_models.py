#!/usr/bin/env python3
"""Acquire pinned organizer model snapshots for local-only evaluation.

This is the only network boundary for the organizer core/extended matrix. It does
not run models and refuses blocked/gated/remote-code candidates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.organizer_candidates import (  # noqa: E402
    OrganizerCandidate,
    OrganizerCandidateError,
    load_organizer_candidate_catalog,
    sha256_file,
)
from brain_twin_eval.organizer_local_runtime import PIN_MANIFEST  # noqa: E402
from brain_twin_eval.organizer_matrix import (  # noqa: E402
    load_organizer_model_matrix,
    organizer_candidate_directory_name,
)


def default_model_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BrainTwin" / "models"
    return Path.home() / ".local" / "share" / "brain-twin" / "models"


def _verify_remote_sha(
    candidate: OrganizerCandidate,
    *,
    repo_info_fn: Callable[..., object],
) -> None:
    if candidate.revision is None:
        raise OrganizerCandidateError(f"candidate is not pinned: {candidate.candidate_id}")
    info = repo_info_fn(repo_id=candidate.model_name, revision=candidate.revision)
    resolved = getattr(info, "sha", None)
    if resolved != candidate.revision:
        raise OrganizerCandidateError(
            f"Hugging Face resolved {candidate.model_name}@{candidate.revision} to unexpected SHA {resolved!r}"
        )


def acquire_organizer_candidate(
    candidate: OrganizerCandidate,
    root: Path,
    *,
    catalog_sha256: str,
    repo_info_fn: Callable[..., object],
    snapshot_download_fn: Callable[..., str],
) -> Path:
    if not candidate.runnable_reference or candidate.trust_remote_code:
        raise OrganizerCandidateError(
            f"candidate is not authorized for direct organizer acquisition: {candidate.candidate_id}"
        )
    assert candidate.revision is not None
    _verify_remote_sha(candidate, repo_info_fn=repo_info_fn)

    target = root / organizer_candidate_directory_name(candidate)
    target.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        snapshot_download_fn(
            repo_id=candidate.model_name,
            revision=candidate.revision,
            local_dir=str(target),
        )
    ).resolve()
    if downloaded != target.resolve():
        raise OrganizerCandidateError(
            f"snapshot_download returned unexpected destination {downloaded}; expected {target.resolve()}"
        )

    manifest: dict[str, Any] = {
        "schema": 1,
        "candidate_id": candidate.candidate_id,
        "repo_id": candidate.model_name,
        "revision": candidate.revision,
        "runtime_status": candidate.runtime_status,
        "trust_remote_code": candidate.trust_remote_code,
        "catalog_sha256": catalog_sha256,
        "runtime_policy": "evaluation-loads-local-files-only",
    }
    (target / PIN_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _select(
    *,
    candidates: tuple[OrganizerCandidate, ...],
    matrix_path: Path,
    tier: str,
    explicit_ids: list[str],
) -> tuple[OrganizerCandidate, ...]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    matrix = load_organizer_model_matrix(matrix_path, candidates)
    ids = tuple(explicit_ids) if explicit_ids else matrix.candidate_ids(tier)
    unknown = sorted(set(ids) - set(by_id))
    if unknown:
        raise OrganizerCandidateError(f"unknown organizer candidate(s): {unknown}")
    selected = tuple(by_id[candidate_id] for candidate_id in ids)
    unsafe = [candidate.candidate_id for candidate in selected if not candidate.runnable_reference or candidate.trust_remote_code]
    if unsafe:
        raise OrganizerCandidateError(f"blocked organizer candidate(s) cannot be acquired by this script: {unsafe}")
    return selected


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=project_root / "evaluation_profiles" / "organizer_candidate_catalog_v1.json",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=project_root / "evaluation_profiles" / "organizer_model_matrix_v1.json",
    )
    parser.add_argument("--tier", choices=("core", "extended", "all"), default="core")
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--root", type=Path, default=default_model_root())
    args = parser.parse_args(argv)

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print("[NG] huggingface-hub is required in the isolated organizer evaluation environment", file=sys.stderr)
        return 2

    try:
        candidates = load_organizer_candidate_catalog(args.catalog)
        selected = _select(
            candidates=candidates,
            matrix_path=args.matrix,
            tier=args.tier,
            explicit_ids=args.candidate_id,
        )
        catalog_sha256 = sha256_file(args.catalog)
    except OrganizerCandidateError as exc:
        print(f"[NG] {exc}", file=sys.stderr)
        return 2

    api = HfApi()
    args.root.mkdir(parents=True, exist_ok=True)
    print(f"organizer model root: {args.root.resolve()}")
    print("selected: " + ", ".join(candidate.candidate_id for candidate in selected))
    for candidate in selected:
        try:
            path = acquire_organizer_candidate(
                candidate,
                args.root,
                catalog_sha256=catalog_sha256,
                repo_info_fn=api.model_info,
                snapshot_download_fn=snapshot_download,
            )
        except (OrganizerCandidateError, OSError) as exc:
            print(f"[NG] {candidate.candidate_id}: {exc}", file=sys.stderr)
            return 2
        print(f"[OK] {candidate.candidate_id}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
