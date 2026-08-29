"""Score judgement-free blind ranking evidence inside the private adjudication environment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.blind_ranking import score_blind_evidence  # noqa: E402
from brain_twin_eval.privacy_paths import require_outside_repository  # noqa: E402
from brain_twin_eval.report import report_json, report_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--private-judgements", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--report-md", type=Path, required=True)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    paths = {
        "blind runner": require_outside_repository(args.runner, repository_root, label="blind runner"),
        "private judgements": require_outside_repository(args.private_judgements, repository_root, label="private judgements"),
        "ranking evidence": require_outside_repository(args.evidence, repository_root, label="ranking evidence"),
        "JSON report": require_outside_repository(args.report_json, repository_root, label="formal blind JSON report"),
        "Markdown report": require_outside_repository(args.report_md, repository_root, label="formal blind Markdown report"),
    }
    if len(set(paths.values())) != len(paths):
        raise SystemExit("formal blind input/output paths must all be distinct")

    runner_raw = json.loads(paths["blind runner"].read_text(encoding="utf-8-sig"))
    private_raw = json.loads(paths["private judgements"].read_text(encoding="utf-8-sig"))
    evidence_raw = json.loads(paths["ranking evidence"].read_text(encoding="utf-8-sig"))
    run, manifest = score_blind_evidence(runner_raw, private_raw, evidence_raw)

    paths["JSON report"].parent.mkdir(parents=True, exist_ok=True)
    paths["Markdown report"].parent.mkdir(parents=True, exist_ok=True)
    paths["JSON report"].write_text(report_json(run, manifest) + "\n", encoding="utf-8")
    paths["Markdown report"].write_text(report_markdown(run, manifest), encoding="utf-8")
    print("formal blind report created with query/slice/failure details redacted")
    print(f"queries scored: {run.overall.query_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
