"""Evaluate precomputed Brain Twin Japanese retrieval rankings.

This PA1 script is deliberately model/backend independent. It does not download models,
instantiate production providers, or touch a user Vault. A future provider/backend adapter can
produce the same rankings format and reuse this evaluator.

Usage:
    python scripts/evaluate_retrieval.py ^
      --dataset fixtures/japanese_retrieval_v1.json ^
      --rankings path/to/rankings.json ^
      --manifest path/to/manifest_input.json ^
      --out-json evaluation.json ^
      --out-md evaluation.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.dataset import load_dataset  # noqa: E402
from brain_twin_eval.manifest import build_manifest  # noqa: E402
from brain_twin_eval.report import report_json, report_markdown  # noqa: E402
from brain_twin_eval.runner import evaluate_rankings  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--rankings", required=True)
    parser.add_argument("--manifest", required=True, help="non-secret experiment input JSON")
    parser.add_argument("--split", choices=("dev", "blind"))
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    return parser.parse_args()


def _load_rankings(path: str | Path) -> dict[str, list[str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rankings JSON must be an object keyed by query_id")
    result: dict[str, list[str]] = {}
    for query_id, ranked in raw.items():
        if not isinstance(query_id, str) or not query_id.strip():
            raise ValueError("ranking query IDs must be non-empty strings")
        if not isinstance(ranked, list) or not all(isinstance(item, str) for item in ranked):
            raise ValueError(f"rankings[{query_id!r}] must be a list of memory IDs")
        result[query_id] = ranked
    return result


def _build_manifest(dataset, path: str | Path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest input must be an object")
    allowed = {
        "experiment_id",
        "git_commit",
        "provider_label",
        "model_name",
        "model_revision",
        "instruction_id",
        "instruction_text",
        "dimension",
        "normalized",
        "document_template_version",
        "backend_label",
        "backend_params",
        "random_seed",
        "timestamp_utc",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError("unknown manifest fields: " + ", ".join(sorted(unknown)))
    return build_manifest(dataset=dataset, **raw)


def main() -> int:
    args = _parse_args()
    dataset = load_dataset(args.dataset)
    rankings = _load_rankings(args.rankings)
    manifest = _build_manifest(dataset, args.manifest)
    run = evaluate_rankings(dataset, rankings, split=args.split)

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(report_json(run, manifest), encoding="utf-8")
    out_md.write_text(report_markdown(run, manifest), encoding="utf-8")
    print(f"evaluated {run.overall.query_count} queries")
    print(f"json: {out_json}")
    print(f"markdown: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
