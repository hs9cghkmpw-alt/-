"""Explicitly acquire immutable PA1 candidate snapshots and pinned remote-code dependencies.

This script is an acquisition-only network boundary. Evaluation remains local-files-only.
Candidates marked ``requires_remote_code_smoke`` may be acquired, but acquisition does not
make them runnable; their exact custom-code path must pass an isolated smoke first.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.candidate_catalog import CandidateSpec, load_catalog  # noqa: E402


def default_model_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BrainTwin" / "models"
    return Path.home() / ".local" / "share" / "brain-twin" / "models"


def candidate_directory_name(candidate: CandidateSpec) -> str:
    if candidate.revision is None:
        raise ValueError(f"candidate {candidate.candidate_id} is not pinned")
    return f"{candidate.candidate_id}_{candidate.revision[:8]}"


def _verify_remote_sha(
    *,
    repo_id: str,
    revision: str,
    repo_info_fn: Callable[..., object],
) -> None:
    info = repo_info_fn(repo_id=repo_id, revision=revision)
    resolved = getattr(info, "sha", None)
    if resolved != revision:
        raise RuntimeError(
            f"Hugging Face resolved {repo_id}@{revision} to unexpected SHA {resolved!r}"
        )


def acquire_candidate(
    candidate: CandidateSpec,
    root: Path,
    *,
    repo_info_fn: Callable[..., object],
    snapshot_download_fn: Callable[..., str],
) -> Path:
    if not candidate.acquirable:
        raise ValueError(f"candidate is not safely acquirable: {candidate.candidate_id}")
    assert candidate.revision is not None

    _verify_remote_sha(
        repo_id=candidate.model_name,
        revision=candidate.revision,
        repo_info_fn=repo_info_fn,
    )
    target = root / candidate_directory_name(candidate)
    target.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        snapshot_download_fn(
            repo_id=candidate.model_name,
            revision=candidate.revision,
            local_dir=str(target),
        )
    ).resolve()
    if downloaded != target.resolve():
        raise RuntimeError(
            f"snapshot_download returned unexpected destination {downloaded}; expected {target.resolve()}"
        )

    code_manifest = None
    if candidate.code_dependency is not None:
        dependency = candidate.code_dependency
        _verify_remote_sha(
            repo_id=dependency.repo_id,
            revision=dependency.revision,
            repo_info_fn=repo_info_fn,
        )
        # Deliberately populate the standard HF cache. Transformers resolves external
        # auto_map code by repo id; local-files-only evaluation can only use it if the
        # exact code revision has already been cached by this explicit acquisition step.
        code_cache_path = Path(
            snapshot_download_fn(
                repo_id=dependency.repo_id,
                revision=dependency.revision,
            )
        )
        if not code_cache_path.exists():
            raise RuntimeError(
                f"remote-code snapshot cache path does not exist: {code_cache_path}"
            )
        code_manifest = {
            "repo_id": dependency.repo_id,
            "revision": dependency.revision,
            "cache_policy": "huggingface-cache-for-local-files-only-resolution",
        }

    manifest = {
        "schema": 2,
        "candidate_id": candidate.candidate_id,
        "role": candidate.role,
        "repo_id": candidate.model_name,
        "revision": candidate.revision,
        "runtime_status": candidate.runtime_status,
        "trust_remote_code": candidate.trust_remote_code,
        "code_dependency": code_manifest,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_policy": "evaluation loads with local_files_only=True",
    }
    (target / "brain_twin_model_pin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _select(candidates: tuple[CandidateSpec, ...], candidate_ids: list[str]) -> tuple[CandidateSpec, ...]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if candidate_ids:
        missing = sorted(set(candidate_ids) - set(by_id))
        if missing:
            raise ValueError("unknown candidate_id(s): " + ", ".join(missing))
        selected = tuple(by_id[candidate_id] for candidate_id in candidate_ids)
    else:
        selected = tuple(
            candidate
            for candidate in candidates
            if candidate.enabled and candidate.role == "embedding"
        )
    unsafe = [candidate.candidate_id for candidate in selected if not candidate.acquirable]
    if unsafe:
        raise ValueError("selected candidate(s) are not safely acquirable: " + ", ".join(unsafe))
    return selected


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=project_root / "evaluation_profiles" / "challenger_catalog_v1.json",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_model_root(),
        help="local model root; defaults to %%LOCALAPPDATA%%\\BrainTwin\\models on Windows",
    )
    parser.add_argument(
        "--candidate-id",
        action="append",
        default=[],
        help="candidate to acquire; repeat for multiple. Default: all enabled embedding candidates.",
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print(
            "[NG] huggingface-hub is not installed. Use the isolated PA1 evaluation environment.",
            file=sys.stderr,
        )
        return 2

    candidates = load_catalog(args.catalog)
    try:
        selected = _select(candidates, args.candidate_id)
    except ValueError as exc:
        print(f"[NG] {exc}", file=sys.stderr)
        return 2

    api = HfApi()
    args.root.mkdir(parents=True, exist_ok=True)
    print(f"model root: {args.root.resolve()}")
    for candidate in selected:
        print(f"acquiring {candidate.model_name}@{candidate.revision}")
        path = acquire_candidate(
            candidate,
            args.root,
            repo_info_fn=api.model_info,
            snapshot_download_fn=snapshot_download,
        )
        status = "OK" if candidate.runnable else "PREPARED"
        print(f"[{status}] {candidate.candidate_id}: {path}")
        if not candidate.runnable:
            print(
                f"  execution blocked: runtime_status={candidate.runtime_status}; "
                "acquisition alone does not authorize custom-code execution"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
