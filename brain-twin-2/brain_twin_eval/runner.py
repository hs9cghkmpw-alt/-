from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from .dataset import EvaluationDataset, EvaluationQuery
from .metrics import QueryMetrics, compute_query_metrics, mean


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
    split: str | None
    queries: tuple[EvaluatedQuery, ...]
    overall: AggregateMetrics
    per_slice: Mapping[str, AggregateMetrics]


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
) -> EvaluationRun:
    evaluated_tuple = tuple(evaluated)
    slices = sorted({tag for item in evaluated_tuple for tag in item.slice_tags})
    per_slice = {
        tag: _aggregate([item for item in evaluated_tuple if tag in item.slice_tags])
        for tag in slices
    }
    return EvaluationRun(
        dataset_version=dataset.version,
        split=split,
        queries=evaluated_tuple,
        overall=_aggregate(evaluated_tuple),
        per_slice=per_slice,
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
                metrics=compute_query_metrics(query, ranked_ids),
            )
        )
    return _build_run(dataset, evaluated, split=split)


def evaluate_retriever(
    dataset: EvaluationDataset,
    retriever: EvaluationRetriever,
    *,
    split: str | None = None,
    k: int = 10,
) -> EvaluationRun:
    """Run an adapter and evaluate its logical Memory rankings."""
    if k < 10:
        raise ValueError("k must be at least 10 so all PA1 metrics can be computed")
    selected = dataset.queries_for_split(split)
    evaluated: list[EvaluatedQuery] = []
    for query in selected:
        started = time.perf_counter()
        results = tuple(retriever.search(query.text, k))
        elapsed = time.perf_counter() - started
        ranked_ids = _validate_ranked_ids(
            dataset,
            query,
            [result.memory_id for result in results],
        )
        evaluated.append(
            EvaluatedQuery(
                query_id=query.query_id,
                split=query.split,
                slice_tags=query.slice_tags,
                ranked_ids=ranked_ids,
                latency_seconds=elapsed,
                metrics=compute_query_metrics(query, ranked_ids),
            )
        )
    return _build_run(dataset, evaluated, split=split)
