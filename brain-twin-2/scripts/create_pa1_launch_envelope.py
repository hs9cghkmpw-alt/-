"""Create the immutable launch envelope that must be frozen before formal blind query execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.acceptance import policy_from_mapping  # noqa: E402
from brain_twin_eval.launch_envelope import build_launch_envelope, envelope_sha256, envelope_to_dict  # noqa: E402
from brain_twin_eval.privacy_paths import require_outside_repository  # noqa: E402


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-artifact-manifest", type=Path)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    runner_path = require_outside_repository(args.runner, repository_root, label="formal blind runner")
    out_path = require_outside_repository(args.out, repository_root, label="formal blind launch envelope")
    if runner_path == out_path:
        raise SystemExit("runner and launch-envelope paths must be distinct")

    runner_raw = json.loads(runner_path.read_text(encoding="utf-8-sig"))
    policy_raw = json.loads(args.policy.read_text(encoding="utf-8-sig"))
    policy = policy_from_mapping(policy_raw)
    artifact_sha = None
    if args.model_artifact_manifest is not None:
        artifact_path = require_outside_repository(
            args.model_artifact_manifest,
            repository_root,
            label="model artifact manifest",
        )
        artifact_sha = _file_sha256(artifact_path)

    envelope = build_launch_envelope(
        runner_raw,
        policy,
        cycle_id=args.cycle_id,
        model_artifact_manifest_sha256=artifact_sha,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(envelope_to_dict(envelope), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"launch envelope sha256: {envelope_sha256(envelope)}")
    print(f"policy sha256: {envelope.policy_sha256}")
    print(f"retrieval config sha256: {envelope.expected_retrieval_config_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
