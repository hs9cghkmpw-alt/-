from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_twin_eval.blind import create_blind_packages, payload_sha256
from brain_twin_eval.dataset import load_dataset


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a private held-out dataset into public runner and private judgement packages.")
    parser.add_argument("--source", type=Path, required=True, help="Private full held-out dataset.")
    parser.add_argument("--runner-out", type=Path, required=True, help="Public runner package path.")
    parser.add_argument("--private-out", type=Path, required=True, help="Private judgement package path; must be outside this repository.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    private_path = args.private_out.resolve()
    if _is_within(private_path, project_root):
        raise SystemExit("private judgement output must be outside the repository")
    if args.runner_out.resolve() == private_path:
        raise SystemExit("runner and private outputs must be different files")

    dataset = load_dataset(args.source)
    packages = create_blind_packages(dataset)

    args.runner_out.parent.mkdir(parents=True, exist_ok=True)
    args.private_out.parent.mkdir(parents=True, exist_ok=True)
    args.runner_out.write_text(
        json.dumps(packages.runner, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    args.private_out.write_text(
        json.dumps(packages.private_judgements, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"runner sha256: {payload_sha256(packages.runner)}")
    print(f"source commitment: {packages.runner['source_dataset_sha256']}")
    print("private judgements written outside repository")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
