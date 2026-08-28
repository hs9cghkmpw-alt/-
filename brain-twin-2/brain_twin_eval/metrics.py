from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean
from typing import Mapping, Sequence

from .dataset import EvaluationQuery


@dataclass(frozen=True)
class QueryMetrics:
    recall_at: Mapping[int, float]
    mrr_at_10: float
    ndcg_at_10: float
    must_hit_at_5: float | None
    false_positive_at_5: float


def _relevant_ids(query: EvaluationQuery) -> set[str]:
    return {memory_id for memory_id, grade in query.relevance.items() if grade > 0}


def recall_at_k(query: EvaluationQuery, ranked_ids: Sequence[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = _relevant_ids(query)
    if not relevant:
        return 0.0
    hits = sum(1 for memory_id in ranked_ids[:k] if memory_id in relevant)
    return hits / len(relevant)


def reciprocal_rank_at_k(query: EvaluationQuery, ranked_ids: Sequence[str], k: int = 10) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = _relevant_ids(query)
    for index, memory_id in enumerate(ranked_ids[:k], start=1):
        if memory_id in relevant:
            return 1.0 / index
    return 0.0


def dcg_at_k(query: EvaluationQuery, ranked_ids: Sequence[str], k: int = 10) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    total = 0.0
    for index, memory_id in enumerate(ranked_ids[:k], start=1):
        grade = query.relevance.get(memory_id, 0)
        gain = (2**grade) - 1
        total += gain / math.log2(index + 1)
    return total


def ndcg_at_k(query: EvaluationQuery, ranked_ids: Sequence[str], k: int = 10) -> float:
    actual = dcg_at_k(query, ranked_ids, k)
    ideal_grades = sorted(query.relevance.values(), reverse=True)[:k]
    ideal = sum(
        ((2**grade) - 1) / math.log2(index + 1)
        for index, grade in enumerate(ideal_grades, start=1)
    )
    if ideal == 0:
        return 0.0
    return actual / ideal


def must_hit_at_k(query: EvaluationQuery, ranked_ids: Sequence[str], k: int = 5) -> float | None:
    if k <= 0:
        raise ValueError("k must be positive")
    if not query.must_hit_ids:
        return None
    top = set(ranked_ids[:k])
    return 1.0 if set(query.must_hit_ids).issubset(top) else 0.0


def false_positive_at_k(query: EvaluationQuery, ranked_ids: Sequence[str], k: int = 5) -> float:
    """Fraction of top-k occupied by explicitly adjudicated grade-0 hard negatives.

    Unannotated IDs are not silently treated as judged negatives: the PA1 gold set is
    intentionally sparse and grows over time. This keeps the metric honest while hard-negative
    coverage is expanded toward the final dataset.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    top = ranked_ids[:k]
    if not top:
        return 0.0
    explicit_zero = {memory_id for memory_id, grade in query.relevance.items() if grade == 0}
    false_positives = sum(1 for memory_id in top if memory_id in explicit_zero)
    return false_positives / len(top)


def compute_query_metrics(
    query: EvaluationQuery,
    ranked_ids: Sequence[str],
    *,
    recall_ks: Sequence[int] = (1, 3, 5, 10),
) -> QueryMetrics:
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError(f"duplicate ranked memory IDs for query {query.query_id}")
    return QueryMetrics(
        recall_at={k: recall_at_k(query, ranked_ids, k) for k in recall_ks},
        mrr_at_10=reciprocal_rank_at_k(query, ranked_ids, 10),
        ndcg_at_10=ndcg_at_k(query, ranked_ids, 10),
        must_hit_at_5=must_hit_at_k(query, ranked_ids, 5),
        false_positive_at_5=false_positive_at_k(query, ranked_ids, 5),
    )


def mean(values: Sequence[float]) -> float:
    return fmean(values) if values else 0.0


def ann_recall_at_k(
    exact_ranked_ids: Sequence[str],
    ann_ranked_ids: Sequence[str],
    k: int = 10,
) -> float:
    """Recall of ANN top-k against ExactScan top-k for the same canonical vectors."""
    if k <= 0:
        raise ValueError("k must be positive")
    reference = list(exact_ranked_ids[:k])
    if not reference:
        return 1.0
    return len(set(reference) & set(ann_ranked_ids[:k])) / len(set(reference))
