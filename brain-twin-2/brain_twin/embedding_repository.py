"""SQLite repository for rebuildable embedding cache and derived state."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from brain_twin import db
from brain_twin.embedding_provider import EmbeddingProfile


@dataclass(frozen=True)
class EmbeddingMemoryRow:
    memory_id: str
    title: str
    content: str


@dataclass(frozen=True)
class EmbeddingMetadata:
    memory_id: str
    content_hash: str
    is_valid: bool


@dataclass(frozen=True)
class BackendState:
    backend: str
    schema_version: int
    profile_fingerprint: str | None
    build_status: str
    built_at: str | None


def active_memories_page(
    conn: sqlite3.Connection, *, after_memory_id: str | None, limit: int
) -> list[EmbeddingMemoryRow]:
    """Read one keyset page; never materialize every Memory body at once."""
    if limit <= 0:
        raise ValueError("DB read batch size must be positive")
    rows = conn.execute(
        """
        SELECT id, title, content FROM memories
        WHERE status = 'active' AND (? IS NULL OR id > ?)
        ORDER BY id
        LIMIT ?
        """,
        (after_memory_id, after_memory_id, limit),
    ).fetchall()
    return [EmbeddingMemoryRow(*row) for row in rows]


def memories_by_ids(
    conn: sqlite3.Connection, memory_ids: list[str]
) -> dict[str, EmbeddingMemoryRow]:
    """Re-read current title/content for a small id set.  Used right before a canonical
    embedding write to detect a concurrent Memory change that raced the provider call;
    a Memory that is missing here (deleted or no longer active) is also treated as a
    mismatch by the caller."""
    if not memory_ids:
        return {}
    result: dict[str, EmbeddingMemoryRow] = {}
    for start in range(0, len(memory_ids), 500):
        batch = memory_ids[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT id, title, content FROM memories WHERE status = 'active' AND id IN ({placeholders})",
            batch,
        ).fetchall()
        result.update({row[0]: EmbeddingMemoryRow(*row) for row in rows})
    return result


def embedding_metadata_by_ids(
    conn: sqlite3.Connection, *, memory_ids: list[str], profile_fingerprint: str
) -> dict[str, EmbeddingMetadata]:
    if not memory_ids:
        return {}
    result: dict[str, EmbeddingMetadata] = {}
    for start in range(0, len(memory_ids), 500):
        batch = memory_ids[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT memory_id, content_hash, is_valid FROM memory_embeddings
            WHERE profile_fingerprint = ? AND memory_id IN ({placeholders})
            """,
            [profile_fingerprint, *batch],
        ).fetchall()
        result.update(
            (row[0], EmbeddingMetadata(row[0], row[1], bool(row[2]))) for row in rows
        )
    return result


def count_active_memories(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT count(*) FROM memories WHERE status = 'active'").fetchone()[0])


def upsert_profile(
    conn: sqlite3.Connection, profile: EmbeddingProfile, *, created_at: str
) -> str:
    return db.upsert_embedding_profile(conn, profile, created_at=created_at)


def active_profile_fingerprint(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT active_profile_fingerprint FROM active_embedding_state WHERE singleton = 1"
    ).fetchone()
    return row[0] if row else None


def set_active_profile(conn: sqlite3.Connection, fingerprint: str) -> None:
    conn.execute(
        """
        INSERT INTO active_embedding_state(singleton, active_profile_fingerprint) VALUES (1, ?)
        ON CONFLICT(singleton) DO UPDATE SET active_profile_fingerprint=excluded.active_profile_fingerprint
        """,
        (fingerprint,),
    )


def backend_state(conn: sqlite3.Connection) -> BackendState | None:
    row = conn.execute(
        """
        SELECT backend, backend_schema_version, indexed_profile_fingerprint, build_status, built_at
        FROM vector_backend_state WHERE singleton = 1
        """
    ).fetchone()
    return BackendState(*row) if row else None


def is_backend_ready_for_profile(
    conn: sqlite3.Connection, *, profile_fingerprint: str,
    backend: str, schema_version: int,
) -> bool:
    state = backend_state(conn)
    return bool(
        active_profile_fingerprint(conn) == profile_fingerprint
        and state is not None
        and state.backend == backend
        and state.schema_version == schema_version
        and state.profile_fingerprint == profile_fingerprint
        and state.build_status == "ready"
    )


def set_backend_state(
    conn: sqlite3.Connection, *, backend: str, schema_version: int,
    profile_fingerprint: str | None, build_status: str, built_at: str | None
) -> None:
    conn.execute(
        """
        INSERT INTO vector_backend_state(
            singleton, backend, backend_schema_version, indexed_profile_fingerprint,
            build_status, built_at
        ) VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            backend=excluded.backend,
            backend_schema_version=excluded.backend_schema_version,
            indexed_profile_fingerprint=excluded.indexed_profile_fingerprint,
            build_status=excluded.build_status,
            built_at=excluded.built_at
        """,
        (backend, schema_version, profile_fingerprint, build_status, built_at),
    )


def upsert_embedding(
    conn: sqlite3.Connection, *, memory_id: str, profile: EmbeddingProfile,
    content_hash: str, vector: list[float], embedded_at: str
) -> None:
    db.upsert_memory_embedding(
        conn, memory_id=memory_id, profile=profile, content_hash=content_hash,
        vector=vector, embedded_at=embedded_at,
    )


def delete_embedding(
    conn: sqlite3.Connection, *, memory_id: str, profile_fingerprint: str
) -> None:
    db.delete_memory_embedding(
        conn, memory_id=memory_id, profile_fingerprint=profile_fingerprint
    )


def delete_profile_embeddings(conn: sqlite3.Connection, profile_fingerprint: str) -> int:
    cursor = conn.execute(
        "DELETE FROM memory_embeddings WHERE profile_fingerprint = ?", (profile_fingerprint,)
    )
    return cursor.rowcount
