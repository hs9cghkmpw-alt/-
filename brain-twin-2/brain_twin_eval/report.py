from __future__ import annotations

import json
from typing import Any

from .manifest import ExperimentManifest, manifest_to_dict
from .runner import AggregateMetrics, EvaluationRun


def _aggregate_to_dict(metrics: AggregateMetrics) -> dict[str, Any]:
    return {
        "query_count": metrics.query_count,
        "recall_at": {str(k): v for k, v in sorted(metrics.recall_at.items())},
        "mrr_at_10": metrics.mrr_at_10,
        "ndcg_at_10": metrics.ndcg_at_10,
        "must_hit_at_5": metrics.must_hit_at_5,
        "false_positive_at_5": metrics.false_positive_at_5,
    }


def report_payload(run: EvaluationRun, manifest: ExperimentManifest) -> dict[str, Any]:
    failed_must_hit: list[dict[str, Any]] = []
    false_positive_cases: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []

    for item in run.queries:
        query_payload = {
            "query_id": item.query_id,
            "split": item.split,
            "slice_tags": list(item.slice_tags),
            "ranked_ids": list(item.ranked_ids),
            "latency_seconds": item.latency_seconds,
            "metrics": {
                "recall_at": {
                    str(k): v for k, v in sorted(item.metrics.recall_at.items())
                },
                "mrr_at_10": item.metrics.mrr_at_10,
                "ndcg_at_10": item.metrics.ndcg_at_10,
                "must_hit_at_5": item.metrics.must_hit_at_5,
                "false_positive_at_5": item.metrics.false_positive_at_5,
            },
        }
        queries.append(query_payload)
        if item.metrics.must_hit_at_5 == 0.0:
            failed_must_hit.append({"query_id": item.query_id, "ranked_ids": list(item.ranked_ids[:5])})
        if item.metrics.false_positive_at_5 > 0:
            false_positive_cases.append(
                {
                    "query_id": item.query_id,
                    "false_positive_at_5": item.metrics.false_positive_at_5,
                    "ranked_ids": list(item.ranked_ids[:5]),
                }
            )

    return {
        "manifest": manifest_to_dict(manifest),
        "dataset_version": run.dataset_version,
        "split": run.split,
        "overall": _aggregate_to_dict(run.overall),
        "per_slice": {
            tag: _aggregate_to_dict(metrics)
            for tag, metrics in sorted(run.per_slice.items())
        },
        "failed_must_hit_queries": failed_must_hit,
        "false_positive_cases": false_positive_cases,
        "queries": queries,
    }


def report_json(run: EvaluationRun, manifest: ExperimentManifest) -> str:
    return json.dumps(
        report_payload(run, manifest),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def report_markdown(run: EvaluationRun, manifest: ExperimentManifest) -> str:
    payload = report_payload(run, manifest)
    overall = run.overall
    lines = [
        "# Japanese Retrieval Evaluation Report",
        "",
        f"- Experiment: `{manifest.experiment_id}`",
        f"- Dataset: `{manifest.dataset_version}` (`{manifest.dataset_sha256}`)",
        f"- Split: `{run.split or 'all'}`",
        f"- Provider/model: `{manifest.provider_label}` / `{manifest.model_name}`",
        f"- Backend: `{manifest.backend_label}`",
        f"- Queries: {overall.query_count}",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for k, value in sorted(overall.recall_at.items()):
        lines.append(f"| Recall@{k} | {_fmt(value)} |")
    lines.extend(
        [
            f"| MRR@10 | {_fmt(overall.mrr_at_10)} |",
            f"| nDCG@10 | {_fmt(overall.ndcg_at_10)} |",
            f"| must-hit@5 | {_fmt(overall.must_hit_at_5)} |",
            f"| false-positive@5 | {_fmt(overall.false_positive_at_5)} |",
            "",
            "## Per slice",
            "",
            "| Slice | Queries | Recall@5 | MRR@10 | nDCG@10 | must-hit@5 | false-positive@5 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for tag, metrics in sorted(run.per_slice.items()):
        lines.append(
            f"| {tag} | {metrics.query_count} | {_fmt(metrics.recall_at.get(5, 0.0))} | "
            f"{_fmt(metrics.mrr_at_10)} | {_fmt(metrics.ndcg_at_10)} | "
            f"{_fmt(metrics.must_hit_at_5)} | {_fmt(metrics.false_positive_at_5)} |"
        )

    lines.extend(["", "## Failed must-hit queries", ""])
    if payload["failed_must_hit_queries"]:
        for item in payload["failed_must_hit_queries"]:
            lines.append(f"- `{item['query_id']}`: top5={item['ranked_ids']}")
    else:
        lines.append("- None")

    lines.extend(["", "## False-positive cases", ""])
    if payload["false_positive_cases"]:
        for item in payload["false_positive_cases"]:
            lines.append(
                f"- `{item['query_id']}`: fp@5={item['false_positive_at_5']:.4f}, "
                f"top5={item['ranked_ids']}"
            )
    else:
        lines.append("- None")

    latencies = [
        item.latency_seconds for item in run.queries if item.latency_seconds is not None
    ]
    lines.extend(["", "## Latency", ""])
    if latencies:
        ordered = sorted(latencies)
        median = ordered[len(ordered) // 2]
        lines.append(f"- median query latency: {median:.6f} s")
        lines.append(f"- max query latency: {max(ordered):.6f} s")
    else:
        lines.append("- Not recorded for precomputed rankings.")

    return "\n".join(lines) + "\n"
