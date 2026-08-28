"""Regenerate the deterministic PA1 open Japanese benchmark v2."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.open_gold_v2 import write_open_gold_v2  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=".evaluation-results/japanese_retrieval_v2_open.json",
        help="output JSON path (default: .evaluation-results/japanese_retrieval_v2_open.json)",
    )
    args = parser.parse_args()
    path = write_open_gold_v2(args.out)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
