"""Run an isolated offline smoke for a pinned PA1 external custom-code candidate.

Success does not promote the candidate. It only produces evidence for a later review.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.candidate_catalog import load_catalog  # noqa: E402
from brain_twin_eval.remote_code_smoke import (  # noqa: E402
    RemoteCodeSmokeError,
    run_remote_code_smoke,
)


def default_model_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BrainTwin" / "models"
    return Path.home() / ".local" / "share" / "brain-twin" / "models"


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=project_root / "evaluation_profiles" / "challenger_catalog_v1.json",
    )
    parser.add_argument("--root", type=Path, default=default_model_root())
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    candidates = load_catalog(args.catalog)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    candidate = by_id.get(args.candidate_id)
    if candidate is None:
        print(f"[NG] unknown candidate_id: {args.candidate_id}", file=sys.stderr)
        return 2

    try:
        result = run_remote_code_smoke(candidate, model_root=args.root)
    except (RemoteCodeSmokeError, OSError, ImportError, RuntimeError, ValueError) as exc:
        print(f"[NG] remote-code smoke failed: {exc}", file=sys.stderr)
        return 1

    payload = json.loads(result.to_json())
    payload["decision"] = "smoke_passed_review_required"
    payload["formal_blind_acceptance"] = False
    payload["production_activation"] = False
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] smoke passed: {candidate.candidate_id}")
    print(f"evidence: {args.out}")
    print("candidate remains blocked until the smoke evidence receives explicit review GO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
