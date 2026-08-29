from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, cast

from .candidate_runtime import (
    DenseCandidateProfile,
    DenseCandidateRetriever,
    DenseModel,
    DensePreparationStats,
    PairScorer,
    RerankingRetriever,
    prepare_dense_candidate,
)
from .dataset import EvaluationDataset, EvaluationMemory
from .runner import EvaluationRetriever


@dataclass(frozen=True)
class _MemoryOnlyDataset:
    """Fail-closed adapter: formal blind model execution exposes Memories, never judgements."""

    memories: tuple[EvaluationMemory, ...]

    @property
    def queries(self) -> Any:  # pragma: no cover - should never be touched
        raise RuntimeError("formal blind model execution must not access query judgements")


def prepare_dense_from_memories(
    memories: Sequence[EvaluationMemory],
    profile: DenseCandidateProfile,
    *,
    model: DenseModel | None = None,
    model_load_seconds: float = 0.0,
    clock=None,
) -> tuple[DenseCandidateRetriever, DensePreparationStats]:
    proxy = cast(EvaluationDataset, _MemoryOnlyDataset(tuple(memories)))
    kwargs = {"model": model, "model_load_seconds": model_load_seconds}
    if clock is not None:
        kwargs["clock"] = clock
    return prepare_dense_candidate(proxy, profile, **kwargs)


def reranker_from_memories(
    memories: Sequence[EvaluationMemory],
    *,
    base: EvaluationRetriever,
    scorer: PairScorer,
    candidate_k: int = 50,
) -> RerankingRetriever:
    proxy = cast(EvaluationDataset, _MemoryOnlyDataset(tuple(memories)))
    return RerankingRetriever(
        dataset=proxy,
        base=base,
        scorer=scorer,
        candidate_k=candidate_k,
    )
