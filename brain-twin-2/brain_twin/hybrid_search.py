"""Sprint 4C: Hybrid Primary Search (Weighted Reciprocal Rank Fusion).

Flow:
  pure lexical candidates (db.search_lexical_candidates)
  + pure vector candidates (VectorIndexBackend.search)
  -> memory_id union/dedupe
  -> RRF fusion (rank-only, no metadata)
  -> lightweight ranking metadata fetch (db.memory_ranking_signals_by_ids)
  -> metadata_multiplier applied exactly once
  -> deterministic final ranking
  -> top N ids confirmed
  -> full detail fetch (db.memory_result_details_by_ids) for the top N only

This module never calls search.search() -- Hybrid's lexical channel must be pure BM25
relevance with no importance/confidence/recency baked in yet.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from brain_twin import db
from brain_twin.embedding_provider import EmbeddingProvider
from brain_twin.retrieval_weights import MIN_QUERY_LENGTH, RetrievalWeights, metadata_multiplier
from brain_twin.vector_index import VectorIndexBackend
from brain_twin.vector_search import check_vector_availability, embed_and_validate_query


@dataclass(frozen=True)
class HybridResult:
    memory_id: str
    final_score: float
    fusion_score: float
    lexical_rank: int | None
    vector_rank: int | None
    lexical_raw_score: float | None
    vector_similarity: float | None
    metadata_multiplier: float
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float
    topics: list[str]
    entities: list[str]


@dataclass(frozen=True)
class _ScoredCandidate:
    memory_id: str
    final_score: float
    fusion_score: float
    lexical: db.LexicalCandidate | None
    vector: object | None  # brain_twin.vector_index.VectorSearchResult
    metadata_multiplier: float
    event_date: str


def _best_channel_rank(lexical: db.LexicalCandidate | None, vector) -> int:
    ranks = []
    if lexical is not None:
        ranks.append(lexical.lexical_rank)
    if vector is not None:
        ranks.append(vector.rank)
    return min(ranks) if ranks else 2**31


def hybrid_search(
    conn: sqlite3.Connection, query: str, provider: EmbeddingProvider, backend: VectorIndexBackend,
    *, limit: int = 20, weights: RetrievalWeights | None = None, now: datetime | None = None,
) -> list[HybridResult]:
    weights = weights or RetrievalWeights()
    query = query.strip()
    if len(query) < MIN_QUERY_LENGTH or limit <= 0:
        return []

    profile = provider.profile
    check_vector_availability(conn, profile, backend)
    query_vector = embed_and_validate_query(provider, query)

    candidate_count = limit * weights.candidate_multiplier
    lexical_candidates = db.search_lexical_candidates(conn, query, limit=candidate_count)
    vector_hits = backend.search(conn, profile.fingerprint, query_vector, limit=candidate_count)

    lexical_by_id = {c.memory_id: c for c in lexical_candidates}
    vector_by_id = {h.memory_id: h for h in vector_hits}
    memory_ids = list(set(lexical_by_id) | set(vector_by_id))
    if not memory_ids:
        return []

    # Lightweight ranking metadata for the *whole* candidate union -- never full Memory bodies.
    signals = db.memory_ranking_signals_by_ids(conn, memory_ids)

    scored: list[_ScoredCandidate] = []
    for memory_id in memory_ids:
        signal = signals.get(memory_id)
        if signal is None:
            continue  # became inactive between candidate retrieval and ranking
        lexical = lexical_by_id.get(memory_id)
        vector = vector_by_id.get(memory_id)

        fusion = 0.0
        if lexical is not None:
            fusion += weights.lexical_weight / (weights.rrf_k + lexical.lexical_rank)
        if vector is not None:
            fusion += weights.vector_weight / (weights.rrf_k + vector.rank)

        # metadata_multiplier is applied exactly once, after fusion -- never per-channel.
        multiplier = metadata_multiplier(
            importance=signal.importance, confidence=signal.confidence,
            event_date=signal.event_date, now=now,
        )
        scored.append(
            _ScoredCandidate(
                memory_id=memory_id, final_score=fusion * multiplier, fusion_score=fusion,
                lexical=lexical, vector=vector, metadata_multiplier=multiplier,
                event_date=signal.event_date,
            )
        )

    # Deterministic ordering via repeated stable sorts, least-significant key first:
    # 1. final_score DESC  2. best channel rank ASC  3. event_date DESC  4. memory_id ASC
    scored.sort(key=lambda c: c.memory_id)
    scored.sort(key=lambda c: c.event_date, reverse=True)
    scored.sort(key=lambda c: _best_channel_rank(c.lexical, c.vector))
    scored.sort(key=lambda c: c.final_score, reverse=True)

    top = scored[:limit]
    details = db.memory_result_details_by_ids(conn, [c.memory_id for c in top])

    results: list[HybridResult] = []
    for c in top:
        detail = details.get(c.memory_id)
        if detail is None:
            continue
        results.append(
            HybridResult(
                memory_id=c.memory_id, final_score=c.final_score, fusion_score=c.fusion_score,
                lexical_rank=c.lexical.lexical_rank if c.lexical else None,
                vector_rank=c.vector.rank if c.vector else None,
                lexical_raw_score=c.lexical.bm25_score if c.lexical else None,
                vector_similarity=c.vector.similarity if c.vector else None,
                metadata_multiplier=c.metadata_multiplier,
                title=detail.title, content=detail.content, type=detail.type,
                event_date=detail.event_date, importance=detail.importance,
                confidence=detail.confidence, topics=detail.topics, entities=detail.entities,
            )
        )
    return results
