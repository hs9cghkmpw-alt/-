"""Sprint 4C: Vector Primary Search.

Flow: query -> provider.embed_query() -> query vector validation -> availability gate ->
VectorIndexBackend.search() -> top-ID detail fetch. Query text is never persisted; only the
query string itself goes to the provider (no other Memory body is sent alongside it).
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from brain_twin import db, embedding_repository as repository
from brain_twin.embedding_provider import (
    EmbeddingProfile, EmbeddingProvider, EmbeddingValidationError, VectorSearchUnavailableError,
)
from brain_twin.embedding_vector import validate_vector
from brain_twin.vector_index import VectorIndexBackend


@dataclass(frozen=True)
class VectorResult:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float
    topics: list[str]
    entities: list[str]
    similarity: float
    vector_rank: int


def check_vector_availability(
    conn: sqlite3.Connection, profile: EmbeddingProfile, backend: VectorIndexBackend
) -> None:
    """Vector search may run only once the canonical cache and backend index are fully
    activated for exactly this profile+backend. A partially staged profile, or a ready
    backend built for a different profile, must never be queried -- this is checked
    against live SQLite state, not just the presence of a user config profile."""
    active_fp = repository.active_profile_fingerprint(conn)
    if active_fp != profile.fingerprint:
        raise VectorSearchUnavailableError(
            "configured embedding profile is not the active profile; run `embeddings sync`"
        )
    state = repository.backend_state(conn)
    if (
        state is None
        or state.backend != backend.backend_id
        or state.schema_version != backend.schema_version
        or state.profile_fingerprint != profile.fingerprint
        or state.build_status != "ready"
    ):
        raise VectorSearchUnavailableError(
            "vector backend index is not ready for the active profile; run `embeddings sync`"
        )


def embed_and_validate_query(provider: EmbeddingProvider, query: str) -> tuple[float, ...]:
    """Same contract as document embedding validation: dimension, finite, non-zero, and
    (for a normalized profile) unit norm. No retry system here -- query search stays simple;
    retries belong to the batch sync path in embedding_service.py."""
    profile = provider.profile
    vector = provider.embed_query(query)
    values = validate_vector(vector, profile.dimension)
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise EmbeddingValidationError("query embedding must not be a zero vector")
    if profile.normalized and not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4):
        raise EmbeddingValidationError("query embedding violates the normalized profile contract")
    return values


def vector_search(
    conn: sqlite3.Connection, query: str, provider: EmbeddingProvider, backend: VectorIndexBackend,
    *, limit: int = 20,
) -> list[VectorResult]:
    if limit <= 0:
        return []
    profile = provider.profile
    check_vector_availability(conn, profile, backend)
    query_vector = embed_and_validate_query(provider, query)

    hits = backend.search(conn, profile.fingerprint, query_vector, limit=limit)
    if not hits:
        return []

    # Lazy detail fetch: only the backend's already-ranked top-K ids ever touch Memory body.
    details = db.memory_result_details_by_ids(conn, [hit.memory_id for hit in hits])
    results: list[VectorResult] = []
    for hit in hits:
        detail = details.get(hit.memory_id)
        if detail is None:
            # Became inactive between the backend index read and this detail fetch; skip
            # rather than surface a partial/incorrect result.
            continue
        results.append(
            VectorResult(
                memory_id=hit.memory_id, title=detail.title, content=detail.content,
                type=detail.type, event_date=detail.event_date, importance=detail.importance,
                confidence=detail.confidence, topics=detail.topics, entities=detail.entities,
                similarity=hit.similarity, vector_rank=hit.rank,
            )
        )
    return results
