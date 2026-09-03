from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence

from .dataset import (
    EvaluationDataset,
    EvaluationQuery,
    dataset_sha256,
    is_formal_blind_run,
)
from .metrics import QueryMetrics, ann_recall_at_k, compute_query_metrics, mean
from .resources import PeakRssReading, peak_rss_reading


@dataclass(frozen=True)
class RankedResult:
    memory_id: str
    score: float | None = None


class EvaluationRetriever(Protocol):
    def search(self, query: str, k: int) -> Sequence[RankedResult]:
        ...


@dataclass(frozen=True)
class EvaluatedQuery:
    query_id: str
    split: str
    slice_tags: tuple[str, ...]
    ranked_ids: tuple[str, ...]
    latency_seconds: float | None
    warm_latency_seconds: tuple[float, ...]
    warm_rank_drift_count: int
    metrics: QueryMetrics


@dataclass(frozen=True)
class AggregateMetrics:
    query_count: int
    recall_at: Mapping[int, float]
    mrr_at_10: float
    ndcg_at_10: float
    must_hit_at_5: float | None
    false_positive_at_5: float


@dataclass(frozen=True)
class EvaluationRun:
    dataset_version: str
    dataset_sha256: str
    judgement_visibility: str
    split: str | None
    queries: tuple[EvaluatedQuery, ...]
    overall: AggregateMetrics
    per_slice: Mapping[str, AggregateMetrics]
    reproducible: bool
    selection_eligible: bool
    peak_rss_before_bytes: int | None = None
    peak_rss_after_bytes: int | None = None
    peak_rss_method: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reproducible, bool):
            raise ValueError("reproducible must be boolean")
        if not isinstance(self.selection_eligible, bool):
            raise ValueError("selection_eligible must be boolean")
        for query in self.queries:
            if (
                isinstance(query.warm_rank_drift_count, bool)
                or not isinstance(query.warm_rank_drift_count, int)
                or query.warm_rank_drift_count < 0
            ):
                raise ValueError("warm_rank_drift_count must be a non-negative integer")
            if self.split is not None and query.split != self.split:
                raise ValueError("evaluation query split does not match run split")
        has_drift = any(query.warm_rank_drift_count > 0 for query in self.queries)
        if has_drift and self.reproducible:
            raise ValueError("a run with ranking drift cannot be reproducible")
        if self.selection_eligible and not self.reproducible:
            raise ValueError("a non-reproducible run cannot be selection eligible")

    @property
    def acceptance_blind_ready(self) -> bool:
        return is_formal_blind_run(self.judgement_visibility, self.split)


@dataclass(frozen=True)
class AnnRecallSummary:
    k: int
    query_count: int
    mean_recall: float
    per_query: Mapping[str, float]


def _validate_ranked_ids(
    dataset: EvaluationDataset,
    query: EvaluationQuery,
    ranked_ids: Sequence[str],
) -> tuple[str, ...]:
    result = tuple(ranked_ids)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate ranked memory IDs for query {query.query_id}")
    unknown = [memory_id for memory_id in result if memory_id not in dataset.memory_ids]
    if unknown:
        raise ValueError(
            f"query {query.query_id} returned unknown memory IDs: {', '.join(unknown)}"
        )
    active_ids = {memory.memory_id for memory in dataset.memories if memory.active}
    inactive = [memory_id for memory_id in result if memory_id not in active_ids]
    if inactive:
        raise ValueError(
            f"query {query.query_id} returned inactive memory IDs: {', '.join(inactive)}"
        )
    return result


def _aggregate(items: Sequence[EvaluatedQuery]) -> AggregateMetrics:
    if not items:
        return AggregateMetrics(
            query_count=0,
            recall_at={1: 0.0, 3: 0.0, 5: 0.0, 10: 0.0},
            mrr_at_10=0.0,
            ndcg_at_10=0.0,
            must_hit_at_5=None,
            false_positive_at_5=0.0,
        )
    recall_keys = tuple(sorted(items[0].metrics.recall_at))
    must_hit_values = [
        item.metrics.must_hit_at_5
        for item in items
        if item.metrics.must_hit_at_5 is not None
    ]
    return AggregateMetrics(
        query_count=len(items),
        recall_at={
            k: mean([item.metrics.recall_at[k] for item in items])
            for k in recall_keys
        },
        mrr_at_10=mean([item.metrics.mrr_at_10 for item in items]),
        ndcg_at_10=mean([item.metrics.ndcg_at_10 for item in items]),
        must_hit_at_5=mean(must_hit_values) if must_hit_values else None,
        false_positive_at_5=mean([item.metrics.false_positive_at_5 for item in items]),
    )


def _build_run(
    dataset: EvaluationDataset,
    evaluated: Sequence[EvaluatedQuery],
    *,
    split: str | None,
    rss_before: PeakRssReading | None = None,
    rss_after: PeakRssReading | None = None,
) -> EvaluationRun:
    evaluated_tuple = tuple(evaluated)
    reproducible = all(item.warm_rank_drift_count == 0 for item in evaluated_tuple)
    slices = sorted({tag for item in evaluated_tuple for tag in item.slice_tags})
    per_slice = {
        tag: _aggregate([item for item in evaluated_tuple if tag in item.slice_tags])
        for tag in slices
    }
    method = None
    if rss_after is not None:
        method = rss_after.method
    elif rss_before is not None:
        method = rss_before.method
    return EvaluationRun(
        dataset_version=dataset.version,
        dataset_sha256=dataset_sha256(dataset),
        judgement_visibility=dataset.judgement_visibility,
        split=split,
        queries=evaluated_tuple,
        overall=_aggregate(evaluated_tuple),
        per_slice=per_slice,
        reproducible=reproducible,
        selection_eligible=reproducible,
        peak_rss_before_bytes=rss_before.bytes if rss_before else None,
        peak_rss_after_bytes=rss_after.bytes if rss_after else None,
        peak_rss_method=method,
    )


def evaluate_rankings(
    dataset: EvaluationDataset,
    rankings: Mapping[str, Sequence[str]],
    *,
    split: str | None = None,
) -> EvaluationRun:
    """Evaluate precomputed logical Memory rankings keyed by query_id."""
    selected = dataset.queries_for_split(split)
    expected_ids = {query.query_id for query in selected}
    missing = expected_ids - set(rankings)
    if missing:
        raise ValueError("missing rankings for query IDs: " + ", ".join(sorted(missing)))

    evaluated: list[EvaluatedQuery] = []
    for query in selected:
        ranked_ids = _validate_ranked_ids(dataset, query, rankings[query.query_id])
        evaluated.append(
            EvaluatedQuery(
                query_id=query.query_id,
                split=query.split,
                slice_tags=query.slice_tags,
                ranked_ids=ranked_ids,
                latency_seconds=None,
                warm_latency_seconds=(),
                warm_rank_drift_count=0,
                metrics=compute_query_metrics(query, ranked_ids),
            )
        )
    return _build_run(dataset, evaluated, split=split)


def _timed_search(
    retriever: EvaluationRetriever,
    query: str,
    k: int,
    *,
    clock: Callable[[], float],
) -> tuple[tuple[RankedResult, ...], float]:
    started = clock()
    results = tuple(retriever.search(query, k))
    return results, clock() - started


def evaluate_retriever(
    dataset: EvaluationDataset,
    retriever: EvaluationRetriever,
    *,
    split: str | None = None,
    k: int = 10,
    warm_repeats: int = 30,
    clock: Callable[[], float] = time.perf_counter,
    rss_reader: Callable[[], PeakRssReading] | None = None,
) -> EvaluationRun:
    """Run an adapter, measuring one cold call plus repeated warm calls per query.

    The cold ranking is the ranking scored for quality. Warm calls are timing samples only;
    if their logical-ID ordering differs, drift is counted instead of silently ignored.
    """
    if k < 10:
        raise ValueError("k must be at least 10 so all PA1 metrics can be computed")
    if isinstance(warm_repeats, bool) or not isinstance(warm_repeats, int) or warm_repeats < 0:
        raise ValueError("warm_repeats must be a non-negative integer")

    read_rss = rss_reader or peak_rss_reading
    rss_before = read_rss()
    selected = dataset.queries_for_split(split)
    evaluated: list[EvaluatedQuery] = []
    for query in selected:
        cold_results, cold_elapsed = _timed_search(
            retriever, query.text, k, clock=clock
        )
        ranked_ids = _validate_ranked_ids(
            dataset,
            query,
            [result.memory_id for result in cold_results],
        )

        warm_latencies: list[float] = []
        drift_count = 0
        for _ in range(warm_repeats):
            warm_results, warm_elapsed = _timed_search(
                retriever, query.text, k, clock=clock
            )
            warm_ids = _validate_ranked_ids(
                dataset,
                query,
                [result.memory_id for result in warm_results],
            )
            warm_latencies.append(warm_elapsed)
            if warm_ids != ranked_ids:
                drift_count += 1

        evaluated.append(
            EvaluatedQuery(
                query_id=query.query_id,
                split=query.split,
                slice_tags=query.slice_tags,
                ranked_ids=ranked_ids,
                latency_seconds=cold_elapsed,
                warm_latency_seconds=tuple(warm_latencies),
                warm_rank_drift_count=drift_count,
                metrics=compute_query_metrics(query, ranked_ids),
            )
        )
    rss_after = read_rss()
    return _build_run(
        dataset,
        evaluated,
        split=split,
        rss_before=rss_before,
        rss_after=rss_after,
    )


def evaluate_ann_recall(
    exact_run: EvaluationRun,
    ann_run: EvaluationRun,
    *,
    k: int = 10,
) -> AnnRecallSummary:
    """Compare ANN rankings to an ExactScan run built from the same canonical vectors."""
    if k <= 0:
        raise ValueError("k must be positive")
    if exact_run.dataset_sha256 != ann_run.dataset_sha256:
        raise ValueError("Exact and ANN runs must use the identical dataset hash")
    if exact_run.split != ann_run.split:
        raise ValueError("Exact and ANN runs must use the same split")
    if not exact_run.selection_eligible or not ann_run.selection_eligible:
        raise ValueError("Exact and ANN runs must both be selection eligible")

    exact_by_id = {item.query_id: item for item in exact_run.queries}
    ann_by_id = {item.query_id: item for item in ann_run.queries}
    if set(exact_by_id) != set(ann_by_id):
        raise ValueError("Exact and ANN runs must contain the same query IDs")

    per_query = {
        query_id: ann_recall_at_k(
            exact_by_id[query_id].ranked_ids,
            ann_by_id[query_id].ranked_ids,
            k,
        )
        for query_id in sorted(exact_by_id)
    }
    return AnnRecallSummary(
        k=k,
        query_count=len(per_query),
        mean_recall=mean(list(per_query.values())),
        per_query=per_query,
    )
