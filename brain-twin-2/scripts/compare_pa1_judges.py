from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_twin_eval.adjudication import compare_judges, judge_package_from_mapping, summary_payload


def _load(path: Path):
    return judge_package_from_mapping(json.loads(path.read_text(encoding="utf-8-sig")))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two private PA1 relevance-judge packages before adjudication.")
    parser.add_argument("--judge-a", type=Path, required=True)
    parser.add_argument("--judge-b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    summary = compare_judges(_load(args.judge_a), _load(args.judge_b))
    payload = summary_payload(summary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"queries: {summary.query_count}")
    print(f"exact agreement: {summary.exact_agreement_count}/{summary.query_count} ({summary.exact_agreement_rate:.3f})")
    print(f"needs adjudication: {len(summary.disagreements)}")
    return 0 if not summary.disagreements else 3


if __name__ == "__main__":
    raise SystemExit(main())
