'''Score sealed blind ranking evidence inside the private adjudication environment.'''
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.acceptance import (  # noqa: E402
    policy_from_mapping,
    policy_sha256,
    retrieval_config_sha256,
)
from brain_twin_eval.blind_ranking import score_blind_evidence  # noqa: E402
from brain_twin_eval.critical_slice import (  # noqa: E402
    evaluate_critical_slices,
    rules_from_policy_mapping,
    summary_payload,
)
from brain_twin_eval.launch_envelope import (  # noqa: E402
    envelope_from_mapping,
    envelope_sha256,
    verify_envelope_context,
    verify_evidence_against_envelope,
)
from brain_twin_eval.manifest import manifest_to_dict  # noqa: E402
from brain_twin_eval.privacy_paths import require_outside_repository  # noqa: E402
from brain_twin_eval.report import report_markdown, report_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--private-judgements", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--launch-envelope", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--report-md", type=Path, required=True)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    paths = {
        "blind runner": require_outside_repository(
            args.runner, repository_root, label="blind runner"
        ),
        "private judgements": require_outside_repository(
            args.private_judgements,
            repository_root,
            label="private judgements",
        ),
        "ranking evidence": require_outside_repository(
            args.evidence, repository_root, label="ranking evidence"
        ),
        "launch envelope": require_outside_repository(
            args.launch_envelope,
            repository_root,
            label="launch envelope",
        ),
        "JSON report": require_outside_repository(
            args.report_json,
            repository_root,
            label="formal blind JSON report",
        ),
        "Markdown report": require_outside_repository(
            args.report_md,
            repository_root,
            label="formal blind Markdown report",
        ),
    }
    if len(set(paths.values())) != len(paths):
        raise SystemExit(
            "formal blind input/output paths must all be distinct"
        )

    runner_raw = json.loads(
        paths["blind runner"].read_text(encoding="utf-8-sig")
    )
    private_raw = json.loads(
        paths["private judgements"].read_text(encoding="utf-8-sig")
    )
    evidence_raw = json.loads(
        paths["ranking evidence"].read_text(encoding="utf-8-sig")
    )
    policy_raw = json.loads(args.policy.read_text(encoding="utf-8-sig"))
    policy = policy_from_mapping(policy_raw)
    if not policy.formal_ready:
        raise SystemExit("acceptance policy is not formal-ready")

    envelope = envelope_from_mapping(
        json.loads(
            paths["launch envelope"].read_text(encoding="utf-8-sig")
        )
    )
    verify_envelope_context(
        envelope, runner_raw=runner_raw, policy=policy
    )
    verify_evidence_against_envelope(evidence_raw, envelope)

    run, manifest = score_blind_evidence(
        runner_raw, private_raw, evidence_raw
    )
    actual_config_sha = retrieval_config_sha256(
        manifest_to_dict(manifest)
    )
    if actual_config_sha != policy.expected_retrieval_config_sha256:
        raise SystemExit(
            "scored manifest does not match frozen retrieval configuration"
        )

    rules = rules_from_policy_mapping(policy_raw)
    critical_summary = evaluate_critical_slices(run, rules)
    attestation = {
        "policy_sha256": policy_sha256(policy),
        "launch_envelope_sha256": envelope_sha256(envelope),
        "retrieval_config_sha256": actual_config_sha,
        "critical_slice_gates": summary_payload(critical_summary),
    }

    payload = report_payload(run, manifest)
    payload["formal_attestation"] = attestation

    paths["JSON report"].parent.mkdir(parents=True, exist_ok=True)
    paths["Markdown report"].parent.mkdir(
        parents=True, exist_ok=True
    )
    paths["JSON report"].write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    markdown = (
        report_markdown(run, manifest).rstrip()
        + "\n\n## Formal attestation\n\n"
    )
    markdown += (
        f"- Policy SHA-256: `{attestation['policy_sha256']}`\n"
    )
    markdown += (
        "- Launch envelope SHA-256: "
        f"`{attestation['launch_envelope_sha256']}`\n"
    )
    markdown += (
        "- Retrieval config SHA-256: "
        f"`{attestation['retrieval_config_sha256']}`\n"
    )
    markdown += (
        "- Critical slice gates: "
        f"{'PASS' if critical_summary.all_passed else 'FAIL'} "
        f"({critical_summary.rule_count} frozen rules; scores redacted)\n"
    )
    paths["Markdown report"].write_text(
        markdown, encoding="utf-8"
    )

    print(
        "formal blind report created with query/slice/failure details redacted"
    )
    print(f"queries scored: {run.overall.query_count}")
    print(
        "critical slice gates: "
        f"{'pass' if critical_summary.all_passed else 'fail'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
