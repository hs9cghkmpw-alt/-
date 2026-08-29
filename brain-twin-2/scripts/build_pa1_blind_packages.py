from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_twin_eval.blind import create_blind_packages, payload_sha256
from brain_twin_eval.dataset import load_dataset
from brain_twin_eval.privacy_paths import require_outside_repository


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a private held-out dataset into isolated runner and judgement packages.")
    parser.add_argument("--source", type=Path, required=True, help="Private full held-out dataset; must be outside this repository.")
    parser.add_argument("--runner-out", type=Path, required=True, help="Blind runner package; must remain outside the tuning repository.")
    parser.add_argument("--private-out", type=Path, required=True, help="Private judgement package; must remain outside the repository.")
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    source = require_outside_repository(args.source, repository_root, label="held-out source")
    runner_path = require_outside_repository(args.runner_out, repository_root, label="blind runner output")
    private_path = require_outside_repository(args.private_out, repository_root, label="private judgement output")
    if len({source, runner_path, private_path}) != 3:
        raise SystemExit("source, runner and private judgement paths must be distinct")

    dataset = load_dataset(source)
    packages = create_blind_packages(dataset)

    runner_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(
        json.dumps(packages.runner, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    private_path.write_text(
        json.dumps(packages.private_judgements, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"runner sha256: {payload_sha256(packages.runner)}")
    print(f"source commitment: {packages.runner['source_dataset_sha256']}")
    print("formal blind artifacts written outside repository")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
