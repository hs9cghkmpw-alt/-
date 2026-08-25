"""Small-Vault/reference exact cosine search over canonical embedding BLOBs."""
from __future__ import annotations

import math
import sqlite3
from collections.abc import Sequence

from brain_twin import db
from brain_twin.embedding_provider import EmbeddingValidationError
from brain_twin.embedding_vector import decode_embedding, validate_vector
from brain_twin.vector_index import VectorSearchResult


class ExactScanBackend:
    """Index adapter with no separate index; sync operations intentionally do nothing.

    Search reads the repository-owned canonical cache.  Callers must mutate that cache before
    calling sync_upsert/sync_delete; none of these backend methods changes canonical BLOBs.
    """

    backend_id = "exact_scan"
    schema_version = 1

    def build(self, conn: sqlite3.Connection, profile_fingerprint: str) -> int:
        rows = db.active_embedding_blobs(conn, profile_fingerprint)
        dimension = db.embedding_profile_dimension(conn, profile_fingerprint)
        for _, blob in rows:
            decode_embedding(blob, dimension)
        return len(rows)

    def sync_upsert(
        self, conn: sqlite3.Connection, memory_id: str,
        profile_fingerprint: str, vector: Sequence[float]
    ) -> None:
        dimension = db.embedding_profile_dimension(conn, profile_fingerprint)
        validate_vector(vector, dimension)
        # Canonical cache was written by the repository first; ExactScan has no second index.
        return None

    def sync_delete(self, conn: sqlite3.Connection, memory_id: str) -> None:
        # No backend-specific index exists. Canonical cache lifecycle belongs to db.py.
        return None

    def clear_index(self, conn: sqlite3.Connection) -> None:
        # ExactScan is a view over canonical cache and has no separate state to clear.
        return None

    def search(
        self, conn: sqlite3.Connection, profile_fingerprint: str,
        query_vector: Sequence[float], *, limit: int
    ) -> list[VectorSearchResult]:
        if limit <= 0:
            return []
        dimension = db.embedding_profile_dimension(conn, profile_fingerprint)
        query = validate_vector(query_vector, dimension)
        query_norm = math.sqrt(sum(value * value for value in query))
        if query_norm == 0:
            raise EmbeddingValidationError("query vector must not be zero")

        scored: list[tuple[float, str]] = []
        for memory_id, blob in db.active_embedding_blobs(conn, profile_fingerprint):
            vector = decode_embedding(blob, dimension)
            vector_norm = math.sqrt(sum(value * value for value in vector))
            if vector_norm == 0:
                raise EmbeddingValidationError(f"zero embedding for {memory_id}")
            similarity = sum(a * b for a, b in zip(query, vector)) / (query_norm * vector_norm)
            scored.append((similarity, memory_id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            VectorSearchResult(memory_id=memory_id, similarity=similarity, rank=rank)
            for rank, (similarity, memory_id) in enumerate(scored[:limit], start=1)
        ]
