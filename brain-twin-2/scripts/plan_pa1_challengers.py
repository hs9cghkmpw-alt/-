"""Create the deterministic PA1 fixed-profile challenger execution plan without loading models."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.candidate_catalog import load_catalog  # noqa: E402
from brain_twin_eval.challenger_plan import build_challenger_plan  # noqa: E402


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=project_root / "evaluation_profiles" / "challenger_catalog_v1.json",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    candidates = load_catalog(args.catalog)
    runs = build_challenger_plan(candidates, project_root=project_root)
    payload = {
        "schema": 1,
        "scope": "open-development-fixed-profile-challengers",
        "runs": [run.to_mapping() for run in runs],
        "runnable_count": sum(1 for run in runs if run.runnable),
        "blocked_count": sum(1 for run in runs if not run.runnable),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
