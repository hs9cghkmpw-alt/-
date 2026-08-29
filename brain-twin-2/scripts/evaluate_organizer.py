#!/usr/bin/env python3
"""Export organizer open inputs or score JSONL predictions without loading any model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from brain_twin_eval.organizer import OrganizerEvaluationError, evaluate_organizer
from brain_twin_eval.organizer_gold import build_organizer_open_v1


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_predictions(path: Path) -> dict[str, object]:
    predictions: dict[str, object] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OrganizerEvaluationError(f"invalid prediction JSONL at line {line_number}") from exc
        if not isinstance(item, dict) or frozenset(item) != {"sample_id", "output"}:
            raise OrganizerEvaluationError(
                f"prediction line {line_number} must contain exactly sample_id and output"
            )
        sample_id = item["sample_id"]
        if not isinstance(sample_id, str) or not sample_id:
            raise OrganizerEvaluationError(f"invalid sample_id at line {line_number}")
        if sample_id in predictions:
            raise OrganizerEvaluationError(f"duplicate prediction sample_id: {sample_id}")
        predictions[sample_id] = item["output"]
    return predictions


def _render_markdown(report: dict[str, object]) -> str:
    overall = report["overall"]
    assert isinstance(overall, dict)
    ordered = [
        "schema_valid_rate",
        "strict_record_accuracy",
        "memory_worthy_f1",
        "memory_type_accuracy",
        "topics_f1",
        "entities_f1",
        "entity_hallucination_rate",
        "event_date_exact_rate",
        "event_date_null_accuracy",
        "importance_mae",
        "importance_within_one_rate",
        "links_f1",
        "confidence_brier",
    ]
    lines = [
        "# Organizer Open Evaluation",
        "",
        f"- Dataset: `{report['dataset_version']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        f"- Samples: {overall['sample_count']}",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in ordered:
        value = overall[key]
        if isinstance(value, float):
            rendered = f"{value:.6f}"
        else:
            rendered = str(value)
        lines.append(f"| `{key}` | {rendered} |")
    invalid = report.get("invalid_sample_ids", [])
    if isinstance(invalid, list):
        lines.extend(["", f"Invalid/missing outputs: **{len(invalid)}**"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-open", help="export model-side open inputs without gold")
    export_parser.add_argument("--output", type=Path, required=True)

    score_parser = subparsers.add_parser("score-open", help="score JSONL model outputs against open gold")
    score_parser.add_argument("--predictions", type=Path, required=True)
    score_parser.add_argument("--json-report", type=Path, required=True)
    score_parser.add_argument("--markdown-report", type=Path)

    args = parser.parse_args(argv)
    dataset = build_organizer_open_v1()

    try:
        if args.command == "export-open":
            payload = dataset.public_payload()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8", newline="\n") as handle:
                for sample in payload["samples"]:
                    handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
            print(f"exported {len(dataset.samples)} organizer samples to {args.output}")
            print(f"dataset_sha256={dataset.canonical_sha256}")
            return 0

        predictions = _load_predictions(args.predictions)
        result = evaluate_organizer(dataset, predictions)
        report = result.to_dict(redact_held_out=True)
        _write_json(args.json_report, report)
        if args.markdown_report:
            args.markdown_report.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_report.write_text(_render_markdown(report), encoding="utf-8")
        print(f"scored {len(dataset.samples)} organizer samples")
        print(f"schema_valid_rate={result.overall['schema_valid_rate']:.6f}")
        print(f"strict_record_accuracy={result.overall['strict_record_accuracy']:.6f}")
        return 0
    except (OSError, OrganizerEvaluationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
