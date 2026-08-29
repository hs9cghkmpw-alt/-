#!/usr/bin/env python3
"""Run the frozen organizer open benchmark against acquired local model snapshots."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin_eval.organizer import OrganizerDataset, evaluate_organizer  # noqa: E402
from brain_twin_eval.organizer_candidates import (  # noqa: E402
    OrganizerCandidateError,
    load_organizer_candidate_catalog,
)
from brain_twin_eval.organizer_gold_v2 import build_organizer_open_v2  # noqa: E402
from brain_twin_eval.organizer_local_runtime import (  # noqa: E402
    TransformersLocalOrganizerGenerator,
    build_organizer_run_config,
    run_public_package,
)
from brain_twin_eval.organizer_matrix import (  # noqa: E402
    load_organizer_model_matrix,
    organizer_candidate_directory_name,
)
from acquire_organizer_models import default_model_root  # noqa: E402


def default_results_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BrainTwin" / "evaluation" / "organizer"
    return Path.home() / ".local" / "share" / "brain-twin" / "evaluation" / "organizer"


def _dataset_with_limit(dataset: OrganizerDataset, limit: int | None) -> OrganizerDataset:
    if limit is None:
        return dataset
    if limit <= 0:
        raise OrganizerCandidateError("sample-limit must be positive")
    if limit >= len(dataset.samples):
        return dataset
    return OrganizerDataset(
        version=f"{dataset.version}-smoke-{limit}",
        judgement_visibility="open",
        samples=dataset.samples[:limit],
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_predictions(path: Path, predictions: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample_id in sorted(predictions):
            handle.write(
                json.dumps(
                    {"sample_id": sample_id, "output": predictions[sample_id]},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )


def _summary_entry(candidate_id: str, report: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    overall = report["overall"]
    return {
        "candidate_id": candidate_id,
        "schema_valid_rate": overall["schema_valid_rate"],
        "strict_record_accuracy": overall["strict_record_accuracy"],
        "memory_worthy_f1": overall["memory_worthy_f1"],
        "memory_type_accuracy": overall["memory_type_accuracy"],
        "topics_f1": overall["topics_f1"],
        "entities_f1": overall["entities_f1"],
        "entity_hallucination_rate": overall["entity_hallucination_rate"],
        "event_date_exact_rate": overall["event_date_exact_rate"],
        "event_date_null_accuracy": overall["event_date_null_accuracy"],
        "links_f1": overall["links_f1"],
        "confidence_brier": overall["confidence_brier"],
        "latency_ms_median": runtime["latency_ms"]["median"],
        "latency_ms_p95": runtime["latency_ms"]["p95"],
        "peak_rss_after_bytes": runtime["peak_rss"]["after_bytes"],
        "model_disk_bytes": runtime["model_disk_bytes"],
        "deterministic": runtime["determinism"]["deterministic"],
    }


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("core", "extended", "all"), default="core")
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--model-root", type=Path, default=default_model_root())
    parser.add_argument("--results-root", type=Path, default=default_results_root())
    parser.add_argument("--sample-limit", type=int, default=None, help="open smoke only; omit for comparable full v2 run")
    parser.add_argument("--determinism-samples", type=int, default=8)
    parser.add_argument("--determinism-repeats", type=int, default=2)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=project_root / "evaluation_profiles" / "organizer_candidate_catalog_v1.json",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=project_root / "evaluation_profiles" / "organizer_model_matrix_v1.json",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=project_root / "evaluation_profiles" / "organizer_system_prompt_v1.txt",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=project_root / "evaluation_profiles" / "organizer_output_schema_v1.json",
    )
    args = parser.parse_args(argv)

    # The runner is deliberately offline. Acquisition must have happened first.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        candidates = load_organizer_candidate_catalog(args.catalog)
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        matrix = load_organizer_model_matrix(args.matrix, candidates)
        ids = tuple(args.candidate_id) if args.candidate_id else matrix.candidate_ids(args.tier)
        unknown = sorted(set(ids) - set(by_id))
        if unknown:
            raise OrganizerCandidateError(f"unknown organizer candidate(s): {unknown}")
        selected = tuple(by_id[candidate_id] for candidate_id in ids)
        unsafe = [candidate.candidate_id for candidate in selected if not candidate.runnable_reference]
        if unsafe:
            raise OrganizerCandidateError(f"blocked organizer candidate(s) cannot run directly: {unsafe}")
        system_prompt = args.prompt.read_text(encoding="utf-8").strip()
        schema_text = args.schema.read_text(encoding="utf-8").strip()
        if not system_prompt or not schema_text:
            raise OrganizerCandidateError("organizer prompt/schema must not be empty")
        dataset = _dataset_with_limit(build_organizer_open_v2(), args.sample_limit)
    except (OrganizerCandidateError, OSError) as exc:
        print(f"[NG] {exc}", file=sys.stderr)
        return 2

    combined_prompt = system_prompt + "\n\nAuthoritative output JSON Schema:\n" + schema_text
    run_root = args.results_root / dataset.version
    run_root.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []

    for candidate in selected:
        model_dir = args.model_root / organizer_candidate_directory_name(candidate)
        print(f"running {candidate.candidate_id} from {model_dir}")
        try:
            generator = TransformersLocalOrganizerGenerator.load(
                candidate=candidate,
                model_dir=model_dir,
                system_prompt=combined_prompt,
                max_new_tokens=args.max_new_tokens,
                seed=args.seed,
            )
            config = build_organizer_run_config(
                candidate=candidate,
                generator=generator,
                prompt_path=args.prompt,
                schema_path=args.schema,
                max_new_tokens=args.max_new_tokens,
                seed=args.seed,
            )
            predictions, runtime = run_public_package(
                public_package=dataset.public_payload(),
                generator=generator,
                candidate=candidate,
                config=config,
                model_dir=model_dir,
                determinism_checked_samples=args.determinism_samples,
                determinism_repeats=args.determinism_repeats,
            )
            result = evaluate_organizer(dataset, predictions)
        except (OrganizerCandidateError, OSError, RuntimeError) as exc:
            print(f"[NG] {candidate.candidate_id}: {exc}", file=sys.stderr)
            return 2

        candidate_root = run_root / candidate.candidate_id
        report = result.to_dict(redact_held_out=True)
        runtime_payload = runtime.to_dict()
        _write_predictions(candidate_root / "predictions.jsonl", predictions)
        _write_json(candidate_root / "quality_report.json", report)
        _write_json(candidate_root / "runtime_evidence.json", runtime_payload)
        _write_json(candidate_root / "organizer_run_config.json", config.canonical_payload | {"sha256": config.sha256})
        summaries.append(_summary_entry(candidate.candidate_id, report, runtime_payload))
        print(
            f"[OK] {candidate.candidate_id}: schema={report['overall']['schema_valid_rate']:.4f} "
            f"strict={report['overall']['strict_record_accuracy']:.4f} "
            f"p95={runtime.latency_ms_p95:.1f}ms deterministic={runtime.deterministic}"
        )

    matrix_summary = {
        "schema": 1,
        "dataset_version": dataset.version,
        "dataset_sha256": dataset.canonical_sha256,
        "sample_count": len(dataset.samples),
        "tier": args.tier,
        "smoke_only": args.sample_limit is not None and args.sample_limit < len(build_organizer_open_v2().samples),
        "candidates": summaries,
        "selection_note": "No automatic production winner. Compare quality, hallucination, determinism, latency, RSS and disk before freezing acceptance gates.",
    }
    _write_json(run_root / "matrix_summary.json", matrix_summary)
    print(f"matrix summary: {run_root / 'matrix_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
