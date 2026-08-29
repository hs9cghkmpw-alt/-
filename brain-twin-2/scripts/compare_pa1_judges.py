from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_twin_eval.adjudication import compare_judges, judge_package_from_mapping, summary_payload
from brain_twin_eval.privacy_paths import require_outside_repository


def _load(path: Path):
    return judge_package_from_mapping(json.loads(path.read_text(encoding="utf-8-sig")))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two private PA1 relevance-judge packages before adjudication.")
    parser.add_argument("--judge-a", type=Path, required=True)
    parser.add_argument("--judge-b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    judge_a = require_outside_repository(args.judge_a, repository_root, label="judge A package")
    judge_b = require_outside_repository(args.judge_b, repository_root, label="judge B package")
    out = require_outside_repository(args.out, repository_root, label="adjudication output")
    if len({judge_a, judge_b, out}) != 3:
        raise SystemExit("judge A, judge B and adjudication output paths must be distinct")

    summary = compare_judges(_load(judge_a), _load(judge_b))
    payload = summary_payload(summary)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"queries: {summary.query_count}")
    print(f"exact agreement: {summary.exact_agreement_count}/{summary.query_count} ({summary.exact_agreement_rate:.3f})")
    print(f"needs adjudication: {len(summary.disagreements)}")
    return 0 if not summary.disagreements else 3


if __name__ == "__main__":
    raise SystemExit(main())
