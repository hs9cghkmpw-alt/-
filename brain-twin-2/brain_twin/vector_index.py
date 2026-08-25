"""Backend-neutral vector index contract."""
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
    backend_id: str
    schema_version: int

    def build(self, conn: sqlite3.Connection, profile_fingerprint: str) -> int: ...
    def upsert(
        self, conn: sqlite3.Connection, memory_id: str,
        profile_fingerprint: str, vector: Sequence[float]
    ) -> None: ...
    def delete(self, conn: sqlite3.Connection, memory_id: str) -> None: ...
    def search(
        self, conn: sqlite3.Connection, profile_fingerprint: str,
        query_vector: Sequence[float], *, limit: int
    ) -> list[VectorSearchResult]: ...
    def clear(self, conn: sqlite3.Connection) -> None: ...
