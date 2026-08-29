from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from brain_twin_eval.acceptance import evaluate_acceptance, policy_from_mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a frozen PA1 acceptance policy to one evaluation report.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--development", action="store_true", help="Skip formal held-out/runtime-only gates.")
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    policy = policy_from_mapping(json.loads(args.policy.read_text(encoding="utf-8-sig")))
    decision = evaluate_acceptance(report, policy, formal=not args.development)
    payload = {
        "status": decision.status,
        "passed": decision.passed,
        "policy_id": decision.policy_id,
        "policy_sha256": decision.policy_sha256,
        "gates": [asdict(gate) for gate in decision.gates],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"acceptance: {decision.status}")
    print(f"policy sha256: {decision.policy_sha256}")
    return 0 if decision.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
