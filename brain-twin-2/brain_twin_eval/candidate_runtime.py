from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from brain_twin.embedding_document import build_embedding_document

from .dataset import EvaluationDataset
from .runner import EvaluationRetriever, RankedResult


class CandidateRuntimeError(RuntimeError):
    pass


class DenseModel(Protocol):
    def encode(self, sentences: Sequence[str], **kwargs: Any) -> Any:
        ...


class PairScorer(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        ...


@dataclass(frozen=True)
class DenseCandidateProfile:
    candidate_id: str
    model_path: str
    model_name: str
    model_revision: str
    instruction_id: str
    query_template: str = "{query}"
    document_template: str = "{document}"
    dimension: int | None = None
    normalized: bool = True
    batch_size: int = 16
    trust_remote_code: bool = False

    def __post_init__(self) -> None:
        for name in ("candidate_id", "model_path", "model_name", "model_revision", "instruction_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if "{query}" not in self.query_template:
            raise ValueError("query_template must contain {query}")
        if "{document}" not in self.document_template:
            raise ValueError("document_template must contain {document}")
        if self.dimension is not None and (
            isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension <= 0
        ):
            raise ValueError("dimension must be a positive integer or None")
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int) or self.batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(self.normalized, bool):
            raise ValueError("normalized must be boolean")
        if not isinstance(self.trust_remote_code, bool):
            raise ValueError("trust_remote_code must be boolean")

    def format_query(self, query: str) -> str:
        return self.query_template.replace("{query}", query)

    def format_document(self, document: str) -> str:
        return self.document_template.replace("{document}", document)


@dataclass(frozen=True)
class RerankerCandidateProfile:
    candidate_id: str
    model_path: str
    model_name: str
    model_revision: str
    instruction_id: str
    instruction_text: str
    batch_size: int = 8
    trust_remote_code: bool = False

    def __post_init__(self) -> None:
        for name in ("candidate_id", "model_path", "model_name", "model_revision", "instruction_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.instruction_text, str):
            raise ValueError("instruction_text must be a string")
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int) or self.batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(self.trust_remote_code, bool):
            raise ValueError("trust_remote_code must be boolean")


@dataclass(frozen=True)
class DensePreparationStats:
    candidate_id: str
    model_name: str
    model_revision: str
    model_load_seconds: float
    corpus_encode_seconds: float
    active_memory_count: int
    vector_dimension: int
    normalized: bool
    query_template_sha256: str
    document_template_sha256: str


@dataclass(frozen=True)
class RerankerLoadStats:
    candidate_id: str
    model_name: str
    model_revision: str
    model_load_seconds: float
    instruction_sha256: str


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _model_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.exists() or not path.is_dir():
        raise CandidateRuntimeError(
            f"local model directory does not exist: {path}. "
            "Acquire/pin the model explicitly before evaluation; automatic download is disabled."
        )
    return path


def _as_rows(value: Any) -> list[list[float]]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise CandidateRuntimeError("model encode output must be a 2-D sequence")
    rows: list[list[float]] = []
    for raw_row in value:
        if hasattr(raw_row, "tolist"):
            raw_row = raw_row.tolist()
        if not isinstance(raw_row, (list, tuple)) or not raw_row:
            raise CandidateRuntimeError("model encode output contains an invalid vector")
        row: list[float] = []
        for raw_item in raw_row:
            if isinstance(raw_item, bool):
                raise CandidateRuntimeError("embedding contains a boolean value")
            try:
                item = float(raw_item)
            except (TypeError, ValueError) as exc:
                raise CandidateRuntimeError("embedding contains a non-numeric value") from exc
            if not math.isfinite(item):
                raise CandidateRuntimeError("embedding contains a non-finite value")
            row.append(item)
        rows.append(row)
    return rows


def _prepare_rows(value: Any, *, dimension: int | None, normalized: bool) -> tuple[tuple[float, ...], ...]:
    rows = _as_rows(value)
    if not rows:
        raise CandidateRuntimeError("model returned no embeddings")
    native_dimension = len(rows[0])
    if any(len(row) != native_dimension for row in rows):
        raise CandidateRuntimeError("model returned inconsistent embedding dimensions")
    target_dimension = dimension or native_dimension
    if target_dimension > native_dimension:
        raise CandidateRuntimeError(
            f"requested dimension {target_dimension} exceeds model output dimension {native_dimension}"
        )

    result: list[tuple[float, ...]] = []
    for row in rows:
        truncated = row[:target_dimension]
        norm = math.sqrt(sum(item * item for item in truncated))
        if norm <= 0.0:
            raise CandidateRuntimeError("embedding vector has zero norm")
        if normalized:
            truncated = [item / norm for item in truncated]
        result.append(tuple(truncated))
    return tuple(result)


def _encode(
    model: DenseModel,
    texts: Sequence[str],
    *,
    profile: DenseCandidateProfile,
) -> tuple[tuple[float, ...], ...]:
    raw = model.encode(
        list(texts),
        batch_size=profile.batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=False,
        prompt="",
    )
    return _prepare_rows(raw, dimension=profile.dimension, normalized=profile.normalized)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise CandidateRuntimeError("query/document embedding dimensions do not match")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        raise CandidateRuntimeError("cannot score a zero-norm embedding")
    return dot / (left_norm * right_norm)


class DenseCandidateRetriever(EvaluationRetriever):
    def __init__(
        self,
        *,
        profile: DenseCandidateProfile,
        model: DenseModel,
        memory_vectors: Mapping[str, Sequence[float]],
    ) -> None:
        self.profile = profile
        self.model = model
        self.memory_vectors = {
            memory_id: tuple(float(item) for item in vector)
            for memory_id, vector in memory_vectors.items()
        }

    def search(self, query: str, k: int) -> Sequence[RankedResult]:
        if k <= 0:
            return ()
        query_vector = _encode(
            self.model,
            [self.profile.format_query(query)],
            profile=self.profile,
        )[0]
        scored = [
            RankedResult(memory_id=memory_id, score=_cosine(query_vector, vector))
            for memory_id, vector in self.memory_vectors.items()
        ]
        scored.sort(key=lambda item: (-(item.score if item.score is not None else -math.inf), item.memory_id))
        return tuple(scored[:k])


def load_local_sentence_transformer(
    profile: DenseCandidateProfile,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[DenseModel, float]:
    path = _model_path(profile.model_path)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise CandidateRuntimeError(
            "sentence-transformers is not installed in this environment; "
            "install the explicitly approved evaluation runtime before running local models"
        ) from exc

    started = clock()
    model = SentenceTransformer(
        str(path),
        local_files_only=True,
        trust_remote_code=profile.trust_remote_code,
        default_prompt_name=None,
    )
    if hasattr(model, "default_prompt_name"):
        model.default_prompt_name = None
    return model, clock() - started


def prepare_dense_candidate(
    dataset: EvaluationDataset,
    profile: DenseCandidateProfile,
    *,
    model: DenseModel | None = None,
    model_load_seconds: float = 0.0,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[DenseCandidateRetriever, DensePreparationStats]:
    if model is None:
        model, model_load_seconds = load_local_sentence_transformer(profile, clock=clock)
    active_memories = [memory for memory in dataset.memories if memory.active]
    documents = [
        profile.format_document(build_embedding_document(memory).text)
        for memory in active_memories
    ]
    started = clock()
    vectors = _encode(model, documents, profile=profile)
    corpus_encode_seconds = clock() - started
    if len(vectors) != len(active_memories):
        raise CandidateRuntimeError("model returned a different number of document vectors")
    memory_vectors = {
        memory.memory_id: vector for memory, vector in zip(active_memories, vectors)
    }
    retriever = DenseCandidateRetriever(
        profile=profile,
        model=model,
        memory_vectors=memory_vectors,
    )
    stats = DensePreparationStats(
        candidate_id=profile.candidate_id,
        model_name=profile.model_name,
        model_revision=profile.model_revision,
        model_load_seconds=float(model_load_seconds),
        corpus_encode_seconds=corpus_encode_seconds,
        active_memory_count=len(active_memories),
        vector_dimension=len(vectors[0]),
        normalized=profile.normalized,
        query_template_sha256=_hash_text(profile.query_template),
        document_template_sha256=_hash_text(profile.document_template),
    )
    return retriever, stats


class CrossEncoderPairScorer(PairScorer):
    def __init__(self, model: Any, *, batch_size: int) -> None:
        self.model = model
        self.batch_size = batch_size

    def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        if not documents:
            return ()
        pairs = [(query, document) for document in documents]
        raw = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        scores: list[float] = []
        for value in raw:
            if isinstance(value, (list, tuple)):
                if len(value) != 1:
                    raise CandidateRuntimeError("reranker returned a non-scalar score")
                value = value[0]
            score = float(value)
            if not math.isfinite(score):
                raise CandidateRuntimeError("reranker returned a non-finite score")
            scores.append(score)
        if len(scores) != len(documents):
            raise CandidateRuntimeError("reranker returned the wrong number of scores")
        return tuple(scores)


def load_local_cross_encoder(
    profile: RerankerCandidateProfile,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[PairScorer, RerankerLoadStats]:
    path = _model_path(profile.model_path)
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise CandidateRuntimeError(
            "sentence-transformers is not installed in this environment; "
            "install the explicitly approved evaluation runtime before running the reranker"
        ) from exc

    started = clock()
    prompts = None
    default_prompt_name = None
    if profile.instruction_text:
        prompts = {"brain_twin": profile.instruction_text}
        default_prompt_name = "brain_twin"
    model = CrossEncoder(
        str(path),
        local_files_only=True,
        trust_remote_code=profile.trust_remote_code,
        prompts=prompts,
        default_prompt_name=default_prompt_name,
    )
    elapsed = clock() - started
    return (
        CrossEncoderPairScorer(model, batch_size=profile.batch_size),
        RerankerLoadStats(
            candidate_id=profile.candidate_id,
            model_name=profile.model_name,
            model_revision=profile.model_revision,
            model_load_seconds=elapsed,
            instruction_sha256=_hash_text(profile.instruction_text),
        ),
    )


class RerankingRetriever(EvaluationRetriever):
    def __init__(
        self,
        *,
        dataset: EvaluationDataset,
        base: EvaluationRetriever,
        scorer: PairScorer,
        candidate_k: int = 50,
    ) -> None:
        if isinstance(candidate_k, bool) or not isinstance(candidate_k, int) or candidate_k <= 0:
            raise ValueError("candidate_k must be a positive integer")
        self.base = base
        self.scorer = scorer
        self.candidate_k = candidate_k
        self.documents = {
            memory.memory_id: build_embedding_document(memory).text
            for memory in dataset.memories
            if memory.active
        }

    def search(self, query: str, k: int) -> Sequence[RankedResult]:
        if k <= 0:
            return ()
        candidates = tuple(self.base.search(query, max(k, self.candidate_k)))
        if len({item.memory_id for item in candidates}) != len(candidates):
            raise CandidateRuntimeError("base retriever returned duplicate candidate IDs")
        unknown = [item.memory_id for item in candidates if item.memory_id not in self.documents]
        if unknown:
            raise CandidateRuntimeError(
                "base retriever returned unknown/inactive candidate IDs: " + ", ".join(unknown)
            )
        candidate_documents = [self.documents[item.memory_id] for item in candidates]
        scores = tuple(self.scorer.score(query, candidate_documents))
        if len(scores) != len(candidates):
            raise CandidateRuntimeError("reranker returned the wrong number of scores")
        ranked = [
            (float(score), rank, item.memory_id)
            for rank, (item, score) in enumerate(zip(candidates, scores))
        ]
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        return tuple(
            RankedResult(memory_id=memory_id, score=score)
            for score, _rank, memory_id in ranked[:k]
        )


def stats_json(stats: DensePreparationStats | RerankerLoadStats) -> str:
    payload = asdict(stats)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
