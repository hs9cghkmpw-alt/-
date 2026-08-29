from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from brain_twin_eval.acceptance import (
    evaluate_acceptance,
    policy_from_mapping,
    policy_sha256,
)
from brain_twin_eval.launch_envelope import (
    envelope_from_mapping,
    envelope_sha256,
)
from brain_twin_eval.privacy_paths import require_outside_repository


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a frozen PA1 acceptance policy to one evaluation report."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--launch-envelope", type=Path)
    parser.add_argument(
        "--development",
        action="store_true",
        help="Skip formal held-out/runtime-only gates.",
    )
    args = parser.parse_args()

    formal = not args.development
    repository_root = Path(__file__).resolve().parents[2]

    if formal:
        if args.launch_envelope is None:
            raise SystemExit(
                "--launch-envelope is required for formal acceptance"
            )
        report_path = require_outside_repository(
            args.report,
            repository_root,
            label="formal blind report",
        )
        envelope_path = require_outside_repository(
            args.launch_envelope,
            repository_root,
            label="formal launch envelope",
        )
        out_path = require_outside_repository(
            args.out,
            repository_root,
            label="formal acceptance decision",
        )
    else:
        report_path = args.report
        envelope_path = None
        out_path = args.out

    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    policy = policy_from_mapping(
        json.loads(args.policy.read_text(encoding="utf-8-sig"))
    )
    decision = evaluate_acceptance(report, policy, formal=formal)

    extra_gates: list[dict[str, object]] = []
    envelope_ok = True
    if formal:
        assert envelope_path is not None
        envelope = envelope_from_mapping(
            json.loads(envelope_path.read_text(encoding="utf-8-sig"))
        )
        attestation = report.get("formal_attestation")
        if not isinstance(attestation, dict):
            attestation = {}

        checks = {
            "launch_envelope_attestation": (
                attestation.get("launch_envelope_sha256")
                == envelope_sha256(envelope)
            ),
            "envelope_policy_sha256": (
                envelope.policy_sha256 == policy_sha256(policy)
            ),
            "envelope_retrieval_config_sha256": (
                envelope.expected_retrieval_config_sha256
                == policy.expected_retrieval_config_sha256
            ),
            "envelope_evaluator_commit": (
                envelope.evaluator_git_commit
                == policy.evaluator_git_commit
            ),
            "envelope_dataset_sha": (
                envelope.source_dataset_sha256 == policy.dataset_sha256
            ),
            "envelope_dataset_version": (
                envelope.dataset_version == policy.dataset_version
            ),
            "envelope_evaluation_k": envelope.evaluation_k == 10,
            "envelope_warm_repeats": (
                envelope.expected_warm_repeats
                == policy.expected_warm_repeats
            ),
        }
        envelope_ok = all(checks.values())
        extra_gates = [
            {"gate": name, "passed": passed}
            for name, passed in checks.items()
        ]

    if decision.status == "blocked":
        status = "blocked"
    elif decision.passed and envelope_ok:
        status = "pass"
    else:
        status = "fail"

    payload = {
        "status": status,
        "passed": status == "pass",
        "policy_id": decision.policy_id,
        "policy_sha256": decision.policy_sha256,
        "gates": [asdict(gate) for gate in decision.gates]
        + extra_gates,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"acceptance: {status}")
    print(f"policy sha256: {decision.policy_sha256}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
