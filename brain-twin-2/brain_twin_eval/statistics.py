from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import fmean
from typing import Sequence

from .runner import EvaluatedQuery, EvaluationRun


@dataclass(frozen=True)
class ConfidenceInterval:
    low: float
    high: float


@dataclass(frozen=True)
class PairedMetricDelta:
    metric: str
    query_count: int
    mean_delta: float
    ci95: ConfidenceInterval


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(values)
    if quantile == 0:
        return ordered[0]
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    iterations: int = 2000,
    seed: int = 0,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    """Deterministic non-parametric bootstrap CI for a macro mean."""
    if not values:
        raise ValueError("values must not be empty")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ValueError("iterations must be a positive integer")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if len(values) == 1:
        value = float(values[0])
        return ConfidenceInterval(value, value)

    rng = random.Random(seed)
    n = len(values)
    sample_means = [
        fmean(values[rng.randrange(n)] for _ in range(n))
        for _ in range(iterations)
    ]
    alpha = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        _nearest_rank(sample_means, alpha),
        _nearest_rank(sample_means, 1.0 - alpha),
    )


def _metric_value(item: EvaluatedQuery, metric: str) -> float | None:
    if metric.startswith("recall_at_"):
        try:
            k = int(metric.removeprefix("recall_at_"))
        except ValueError as exc:
            raise ValueError(f"invalid recall metric: {metric}") from exc
        if k not in item.metrics.recall_at:
            raise ValueError(f"recall metric not available: {metric}")
        return item.metrics.recall_at[k]
    if metric == "mrr_at_10":
        return item.metrics.mrr_at_10
    if metric == "ndcg_at_10":
        return item.metrics.ndcg_at_10
    if metric == "must_hit_at_5":
        return item.metrics.must_hit_at_5
    if metric == "false_positive_at_5":
        return item.metrics.false_positive_at_5
    raise ValueError(f"unsupported metric: {metric}")


def metric_values(run: EvaluationRun, metric: str) -> list[float]:
    values = [_metric_value(item, metric) for item in run.queries]
    return [float(value) for value in values if value is not None]


def metric_ci95(
    run: EvaluationRun,
    metric: str,
    *,
    iterations: int = 2000,
    seed: int = 0,
) -> ConfidenceInterval | None:
    values = metric_values(run, metric)
    if not values:
        return None
    return bootstrap_mean_ci(values, iterations=iterations, seed=seed, confidence=0.95)


def paired_metric_delta(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    metric: str,
    *,
    iterations: int = 2000,
    seed: int = 0,
) -> PairedMetricDelta:
    """Candidate-minus-baseline paired query delta with deterministic bootstrap CI."""
    if baseline.dataset_sha256 != candidate.dataset_sha256:
        raise ValueError("paired runs must use the identical dataset hash")
    if baseline.split != candidate.split:
        raise ValueError("paired runs must use the same split")

    baseline_by_id = {item.query_id: item for item in baseline.queries}
    candidate_by_id = {item.query_id: item for item in candidate.queries}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("paired runs must contain the same query IDs")

    deltas: list[float] = []
    for query_id in sorted(baseline_by_id):
        before = _metric_value(baseline_by_id[query_id], metric)
        after = _metric_value(candidate_by_id[query_id], metric)
        if before is None or after is None:
            continue
        deltas.append(float(after - before))
    if not deltas:
        raise ValueError(f"no paired values available for metric {metric}")

    return PairedMetricDelta(
        metric=metric,
        query_count=len(deltas),
        mean_delta=fmean(deltas),
        ci95=bootstrap_mean_ci(deltas, iterations=iterations, seed=seed, confidence=0.95),
    )
