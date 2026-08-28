from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from brain_twin import hybrid_search, search, vector_search
from brain_twin.embedding_provider import EmbeddingProvider
from brain_twin.vector_index import VectorIndexBackend

from .runner import RankedResult


@dataclass
class LexicalRetriever:
    """Thin evaluation-only adapter over the existing lexical search API."""

    conn: sqlite3.Connection

    def search(self, query: str, k: int) -> list[RankedResult]:
        return [
            RankedResult(result.memory_id, result.score)
            for result in search.search(self.conn, query, limit=k)
        ]


@dataclass
class VectorRetriever:
    """Adapter over Vector Primary Search; works with ExactScan or future backends."""

    conn: sqlite3.Connection
    provider: EmbeddingProvider
    backend: VectorIndexBackend

    def search(self, query: str, k: int) -> list[RankedResult]:
        return [
            RankedResult(result.memory_id, result.similarity)
            for result in vector_search.vector_search(
                self.conn, query, self.provider, self.backend, limit=k
            )
        ]


@dataclass
class HybridRetriever:
    """Thin evaluation-only adapter over the existing Weighted-RRF Hybrid search."""

    conn: sqlite3.Connection
    provider: EmbeddingProvider
    backend: VectorIndexBackend

    def search(self, query: str, k: int) -> list[RankedResult]:
        return [
            RankedResult(result.memory_id, result.final_score)
            for result in hybrid_search.hybrid_search(
                self.conn, query, self.provider, self.backend, limit=k
            )
        ]
