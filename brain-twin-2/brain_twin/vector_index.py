"""Backend-neutral contract for indexes derived from canonical embedding cache.

Canonical BLOB persistence/update/deletion belongs to the repository/service layer.  Mutation
methods here synchronize only a backend-specific search index and must never change that cache.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class VectorSearchResult:
    memory_id: str
    similarity: float
    rank: int


@runtime_checkable
class VectorIndexBackend(Protocol):
    """Manage a rebuildable search index derived from canonical embedding BLOBs."""

    backend_id: str
    schema_version: int

    def build(self, conn: sqlite3.Connection, profile_fingerprint: str) -> int: ...
    def sync_upsert(
        self, conn: sqlite3.Connection, memory_id: str,
        profile_fingerprint: str, vector: Sequence[float]
    ) -> None: ...
    def sync_delete(self, conn: sqlite3.Connection, memory_id: str) -> None: ...
    def search(
        self, conn: sqlite3.Connection, profile_fingerprint: str,
        query_vector: Sequence[float], *, limit: int
    ) -> list[VectorSearchResult]: ...
    def clear_index(self, conn: sqlite3.Connection) -> None: ...
