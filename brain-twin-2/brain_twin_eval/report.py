from __future__ import annotations

import json
import math
import statistics
from typing import Any, Sequence

from .manifest import ExperimentManifest, manifest_to_dict
from .runner import AggregateMetrics, EvaluationRun
from .statistics import metric_ci95


def _aggregate_to_dict(metrics: AggregateMetrics) -> dict[str, Any]:
    return {
        "query_count": metrics.query_count,
        "recall_at": {str(k): v for k, v in sorted(metrics.recall_at.items())},
        "mrr_at_10": metrics.mrr_at_10,
        "ndcg_at_10": metrics.ndcg_at_10,
        "must_hit_at_5": metrics.must_hit_at_5,
        "false_positive_at_5": metrics.false_positive_at_5,
    }


def _percentile_nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _latency_summary(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"samples": 0, "median_seconds": None, "p95_seconds": None, "max_seconds": None}
    return {
        "samples": len(values),
        "median_seconds": statistics.median(values),
        "p95_seconds": _percentile_nearest_rank(values, 0.95),
        "max_seconds": max(values),
    }


def _redact_query_details(run: EvaluationRun) -> bool:
    return run.acceptance_blind_ready


def _validate_manifest_run(run: EvaluationRun, manifest: ExperimentManifest) -> None:
    if manifest.dataset_version != run.dataset_version:
        raise ValueError("manifest and evaluation run dataset versions do not match")
    if manifest.dataset_sha256 != run.dataset_sha256:
        raise ValueError("manifest and evaluation run dataset hashes do not match")
    if manifest.dataset_judgement_visibility != run.judgement_visibility:
        raise ValueError("manifest and evaluation run judgement visibility do not match")


def _ci_to_dict(ci) -> dict[str, float] | None:
    if ci is None:
        return None
    return {"low": ci.low, "high": ci.high}


def _overall_ci95(run: EvaluationRun, seed: int) -> dict[str, Any]:
    metrics = [
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "recall_at_10",
        "mrr_at_10",
        "ndcg_at_10",
        "must_hit_at_5",
        "false_positive_at_5",
    ]
    return {
        metric: _ci_to_dict(metric_ci95(run, metric, iterations=2000, seed=seed))
        for metric in metrics
    }


def report_payload(run: EvaluationRun, manifest: ExperimentManifest) -> dict[str, Any]:
    _validate_manifest_run(run, manifest)
    failed_must_hit: list[dict[str, Any]] = []
    false_positive_cases: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    redact = _redact_query_details(run)

    first_call_latencies = [
        item.latency_seconds for item in run.queries if item.latency_seconds is not None
    ]
    warm_latencies = [
        value for item in run.queries for value in item.warm_latency_seconds
    ]
    total_drift = sum(item.warm_rank_drift_count for item in run.queries)

    if not redact:
        for item in run.queries:
            query_payload = {
                "query_id": item.query_id,
                "split": item.split,
                "slice_tags": list(item.slice_tags),
                "ranked_ids": list(item.ranked_ids),
                "first_call_seconds": item.latency_seconds,
                "warm_latency_seconds": list(item.warm_latency_seconds),
                "warm_rank_drift_count": item.warm_rank_drift_count,
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
                failed_must_hit.append(
                    {"query_id": item.query_id, "ranked_ids": list(item.ranked_ids[:5])}
                )
            if item.metrics.false_positive_at_5 > 0:
                false_positive_cases.append(
                    {
                        "query_id": item.query_id,
                        "false_positive_at_5": item.metrics.false_positive_at_5,
                        "ranked_ids": list(item.ranked_ids[:5]),
                    }
                )

    rss_growth = None
    if run.peak_rss_before_bytes is not None and run.peak_rss_after_bytes is not None:
        rss_growth = max(0, run.peak_rss_after_bytes - run.peak_rss_before_bytes)

    return {
        "manifest": manifest_to_dict(manifest),
        "dataset_version": run.dataset_version,
        "dataset_sha256": run.dataset_sha256,
        "judgement_visibility": run.judgement_visibility,
        "acceptance_blind_ready": run.acceptance_blind_ready,
        "split": run.split,
        "reproducible": run.reproducible,
        "selection_eligible": run.selection_eligible,
        "query_details_redacted": redact,
        "per_slice_redacted": redact,
        "overall": _aggregate_to_dict(run.overall),
        "overall_ci95": _overall_ci95(run, manifest.random_seed),
        "per_slice": {}
        if redact
        else {
            tag: _aggregate_to_dict(metrics)
            for tag, metrics in sorted(run.per_slice.items())
        },
        "latency": {
            "run_first_query_seconds": first_call_latencies[0] if first_call_latencies else None,
            "first_call_per_query": _latency_summary(first_call_latencies),
            "warm": _latency_summary(warm_latencies),
            "warm_rank_drift_count": total_drift,
        },
        "resources": {
            "peak_rss_before_bytes": run.peak_rss_before_bytes,
            "peak_rss_after_bytes": run.peak_rss_after_bytes,
            "peak_rss_growth_bytes": rss_growth,
            "peak_rss_method": run.peak_rss_method,
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


def _fmt_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f} s"


def _fmt_ci(ci: dict[str, float] | None) -> str:
    if ci is None:
        return "n/a"
    return f"[{ci['low']:.4f}, {ci['high']:.4f}]"


def report_markdown(run: EvaluationRun, manifest: ExperimentManifest) -> str:
    payload = report_payload(run, manifest)
    overall = run.overall
    lines = [
        "# Japanese Retrieval Evaluation Report",
        "",
        f"- Experiment: `{manifest.experiment_id}`",
        f"- Dataset: `{manifest.dataset_version}` (`{manifest.dataset_sha256}`)",
        f"- Judgements: `{run.judgement_visibility}`",
        f"- Split: `{run.split or 'all'}`",
        f"- Reproducible: `{'yes' if run.reproducible else 'no'}`",
        f"- Selection eligible: `{'yes' if run.selection_eligible else 'no'}`",
        f"- Provider/model: `{manifest.provider_label}` / `{manifest.model_name}`",
        f"- Backend: `{manifest.backend_label}`",
        f"- Queries: {overall.query_count}",
        "",
    ]
    if run.split == "blind" and not run.acceptance_blind_ready:
        lines.extend(
            [
                "> WARNING: this blind-labelled split has open judgements and is not valid as a formal held-out acceptance run.",
                "",
            ]
        )
    if not run.selection_eligible:
        lines.extend(
            [
                "> WARNING: ranking drift made this run selection-ineligible; quality metrics are diagnostic only.",
                "",
            ]
        )
    if payload["query_details_redacted"]:
        lines.extend(
            [
                "> Held-out blind run: per-query rankings, failure cases, and per-slice diagnostics are redacted to reduce tuning leakage.",
                "",
            ]
        )

    lines.extend(
        [
            "## Overall",
            "",
            "| Metric | Value | 95% bootstrap CI |",
            "|---|---:|---:|",
        ]
    )
    for k, value in sorted(overall.recall_at.items()):
        metric = f"recall_at_{k}"
        lines.append(f"| Recall@{k} | {_fmt(value)} | {_fmt_ci(payload['overall_ci95'][metric])} |")
    lines.extend(
        [
            f"| MRR@10 | {_fmt(overall.mrr_at_10)} | {_fmt_ci(payload['overall_ci95']['mrr_at_10'])} |",
            f"| nDCG@10 | {_fmt(overall.ndcg_at_10)} | {_fmt_ci(payload['overall_ci95']['ndcg_at_10'])} |",
            f"| must-hit@5 | {_fmt(overall.must_hit_at_5)} | {_fmt_ci(payload['overall_ci95']['must_hit_at_5'])} |",
            f"| false-positive@5 | {_fmt(overall.false_positive_at_5)} | {_fmt_ci(payload['overall_ci95']['false_positive_at_5'])} |",
        ]
    )

    if not payload["per_slice_redacted"]:
        lines.extend(
            [
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

    lines.extend(["", "## Latency / resources", ""])
    latency = payload["latency"]
    first_calls = latency["first_call_per_query"]
    warm = latency["warm"]
    lines.append(f"- run first query: {_fmt_seconds(latency['run_first_query_seconds'])}")
    if first_calls["samples"]:
        lines.append(
            f"- first call per query: n={first_calls['samples']}, "
            f"median={_fmt_seconds(first_calls['median_seconds'])}, "
            f"p95={_fmt_seconds(first_calls['p95_seconds'])}, "
            f"max={_fmt_seconds(first_calls['max_seconds'])}"
        )
    else:
        lines.append("- first call per query: not recorded for precomputed rankings")
    if warm["samples"]:
        lines.append(
            f"- warm: n={warm['samples']}, median={_fmt_seconds(warm['median_seconds'])}, "
            f"p95={_fmt_seconds(warm['p95_seconds'])}, max={_fmt_seconds(warm['max_seconds'])}"
        )
        lines.append(f"- warm ranking drift count: {latency['warm_rank_drift_count']}")
    else:
        lines.append("- warm: not recorded")
    resources = payload["resources"]
    if resources["peak_rss_after_bytes"] is not None:
        lines.append(
            f"- process peak RSS after run: {resources['peak_rss_after_bytes']} bytes "
            f"({resources['peak_rss_method']})"
        )
        lines.append(f"- peak RSS growth vs runner baseline: {resources['peak_rss_growth_bytes']} bytes")
    else:
        lines.append(f"- process peak RSS: unavailable ({resources['peak_rss_method'] or 'not measured'})")

    if not payload["query_details_redacted"]:
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

    return "\n".join(lines) + "\n"
