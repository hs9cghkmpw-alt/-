"""Rebuildable embedding-cache orchestration; no search or CLI presentation logic."""
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from brain_twin import db, embedding_repository as repository
from brain_twin.config import Config
from brain_twin.embedding_document import build_embedding_document
from brain_twin.embedding_provider import (
    EmbeddingProfile, EmbeddingProvider, EmbeddingTransientError, EmbeddingValidationError,
)
from brain_twin.embedding_vector import validate_vector
from brain_twin.vector_index import VectorIndexBackend


@dataclass(frozen=True)
class EmbeddingSyncPolicy:
    provider_batch_size: int = 32
    db_read_batch_size: int = 200
    commit_batch_size: int = 32
    transient_retry_count: int = 2
    retry_base_delay_seconds: float = 0.25

    def __post_init__(self) -> None:
        if min(self.provider_batch_size, self.db_read_batch_size, self.commit_batch_size) <= 0:
            raise ValueError("embedding batch sizes must be positive")
        if self.transient_retry_count < 0 or self.retry_base_delay_seconds < 0:
            raise ValueError("embedding retry settings must be non-negative")


@dataclass(frozen=True)
class EmbeddingStatus:
    profile_fingerprint: str
    backend: str
    total_active: int
    ready: int
    missing: int
    stale: int
    active_profile_fingerprint: str | None

    @property
    def active_matches_config(self) -> bool:
        return self.active_profile_fingerprint == self.profile_fingerprint


@dataclass(frozen=True)
class EmbeddingSyncResult:
    embedded: int
    skipped: int
    failed: int
    active_switched: bool


class EmbeddingService:
    """Synchronize canonical cache in restart-safe batches, then activate a built backend."""

    def __init__(
        self, config: Config, provider: EmbeddingProvider, backend: VectorIndexBackend, *,
        policy: EmbeddingSyncPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self.config = config
        self.provider = provider
        self.backend = backend
        self.policy = policy or EmbeddingSyncPolicy()
        self._sleep = sleep
        self._now = now

    def status(self) -> EmbeddingStatus:
        with db.connect(self.config) as conn:
            return inspect_embedding_status(
                conn, self.provider.profile, self.backend.backend_id,
                db_read_batch_size=self.policy.db_read_batch_size,
            )

    def sync(self, *, force: bool = False) -> EmbeddingSyncResult:
        profile = self.provider.profile
        embedded = skipped = 0
        with db.connect(self.config) as conn:
            previous_active = repository.active_profile_fingerprint(conn)
            incremental_backend_sync = repository.is_backend_ready_for_profile(
                conn, profile_fingerprint=profile.fingerprint,
                backend=self.backend.backend_id, schema_version=self.backend.schema_version,
            )
            repository.upsert_profile(conn, profile, created_at=self._timestamp())
            conn.commit()
            after_id: str | None = None
            while True:
                page = repository.active_memories_page(
                    conn, after_memory_id=after_id, limit=self.policy.db_read_batch_size
                )
                if not page:
                    break
                after_id = page[-1].memory_id
                metadata = repository.embedding_metadata_by_ids(
                    conn, memory_ids=[row.memory_id for row in page],
                    profile_fingerprint=profile.fingerprint,
                )
                pending: list[tuple[repository.EmbeddingMemoryRow, str, str]] = []
                for row in page:
                    document = build_embedding_document(row)
                    existing = metadata.get(row.memory_id)
                    if (
                        not force and existing and existing.is_valid
                        and existing.content_hash == document.content_hash
                    ):
                        skipped += 1
                    else:
                        pending.append((row, document.text, document.content_hash))
                for start in range(0, len(pending), self.policy.provider_batch_size):
                    provider_batch = pending[start : start + self.policy.provider_batch_size]
                    vectors = self._embed_with_retry([item[1] for item in provider_batch])
                    validated = self._validate_outputs(vectors, len(provider_batch))
                    for commit_start in range(0, len(provider_batch), self.policy.commit_batch_size):
                        items = provider_batch[commit_start : commit_start + self.policy.commit_batch_size]
                        vector_items = validated[commit_start : commit_start + self.policy.commit_batch_size]
                        try:
                            # Re-read current Memory content in a short transaction right before
                            # persisting is_valid=1. The provider call above can take a long time;
                            # if another process changed this Memory's title/content while we were
                            # waiting on the provider, the vector we just computed is for stale text
                            # and must never be saved as valid (Sprint 4C consistency-race fix).
                            current_rows = repository.memories_by_ids(
                                conn, [item[0].memory_id for item in items]
                            )
                            committed = 0
                            for (row, _, content_hash), vector in zip(items, vector_items):
                                current = current_rows.get(row.memory_id)
                                if current is None or build_embedding_document(current).content_hash != content_hash:
                                    # Content changed (or the Memory left the active set) during
                                    # the provider call. Leave the cache untouched; the next sync
                                    # rereads current content and reprocesses it from scratch.
                                    continue
                                repository.upsert_embedding(
                                    conn, memory_id=row.memory_id, profile=profile,
                                    content_hash=content_hash, vector=list(vector),
                                    embedded_at=self._timestamp(),
                                )
                                if incremental_backend_sync:
                                    self.backend.sync_upsert(
                                        conn, row.memory_id, profile.fingerprint, vector
                                    )
                                committed += 1
                            conn.commit()
                        except BaseException:
                            conn.rollback()
                            raise
                        embedded += committed

            active_switched = False
            if not incremental_backend_sync:
                # Staging activation must only happen once every active Memory truly has a
                # ready embedding under this profile. A race-skipped item above would otherwise
                # let a partially-built staging index become active (Sprint 4C hardening).
                status = inspect_embedding_status(
                    conn, profile, self.backend.backend_id,
                    db_read_batch_size=self.policy.db_read_batch_size,
                )
                if status.ready == status.total_active:
                    # Staging cache is complete. build must preserve the old active index on failure.
                    self.backend.build(conn, profile.fingerprint)
                    repository.set_active_profile(conn, profile.fingerprint)
                    repository.set_backend_state(
                        conn, backend=self.backend.backend_id,
                        schema_version=self.backend.schema_version,
                        profile_fingerprint=profile.fingerprint, build_status="ready",
                        built_at=self._timestamp(),
                    )
                    conn.commit()
                    active_switched = previous_active != profile.fingerprint
        return EmbeddingSyncResult(
            embedded=embedded, skipped=skipped, failed=0,
            active_switched=active_switched,
        )

    def rebuild(self) -> EmbeddingSyncResult:
        """Explicitly re-embed active Memories; old rows are overwritten batch-by-batch."""
        return self.sync(force=True)

    def rebuild_backend(self) -> int:
        """Rebuild only the derived backend index from cache; never call the provider."""
        profile = self.provider.profile
        with db.connect(self.config) as conn:
            status = inspect_embedding_status(
                conn, profile, self.backend.backend_id,
                db_read_batch_size=self.policy.db_read_batch_size,
            )
            if status.ready != status.total_active:
                raise EmbeddingValidationError(
                    "canonical embedding cache is incomplete; sync before rebuilding the backend"
                )
            count = self.backend.build(conn, profile.fingerprint)
            repository.set_backend_state(
                conn, backend=self.backend.backend_id, schema_version=self.backend.schema_version,
                profile_fingerprint=profile.fingerprint, build_status="ready",
                built_at=self._timestamp(),
            )
            conn.commit()
            return count

    def delete_cached_embedding(self, memory_id: str) -> None:
        """Apply canonical deletion before synchronizing the backend-specific index."""
        profile = self.provider.profile
        with db.connect(self.config) as conn:
            try:
                repository.delete_embedding(
                    conn, memory_id=memory_id, profile_fingerprint=profile.fingerprint
                )
                self.backend.sync_delete(conn, memory_id)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _embed_with_retry(self, texts: Sequence[str]) -> list[list[float]]:
        retries = 0
        while True:
            try:
                return self.provider.embed_documents(texts)
            except EmbeddingTransientError:
                if retries >= self.policy.transient_retry_count:
                    raise
                self._sleep(self.policy.retry_base_delay_seconds * (2 ** retries))
                retries += 1

    def _validate_outputs(
        self, vectors: Sequence[Sequence[float]], expected_count: int
    ) -> list[tuple[float, ...]]:
        if len(vectors) != expected_count:
            raise EmbeddingValidationError(
                f"provider returned {len(vectors)} vectors for {expected_count} documents"
            )
        result: list[tuple[float, ...]] = []
        for vector in vectors:
            values = validate_vector(vector, self.provider.profile.dimension)
            norm = math.sqrt(sum(value * value for value in values))
            if norm == 0:
                raise EmbeddingValidationError("provider returned a zero vector")
            if self.provider.profile.normalized and not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4):
                raise EmbeddingValidationError("provider violated normalized vector contract")
            result.append(values)
        return result

    def _timestamp(self) -> str:
        return self._now().isoformat()


def inspect_embedding_status(
    conn: sqlite3.Connection, profile: EmbeddingProfile, backend_id: str, *,
    db_read_batch_size: int = 200,
) -> EmbeddingStatus:
    ready = missing = stale = 0
    total = repository.count_active_memories(conn)
    after_id: str | None = None
    while True:
        page = repository.active_memories_page(
            conn, after_memory_id=after_id, limit=db_read_batch_size
        )
        if not page:
            break
        after_id = page[-1].memory_id
        metadata = repository.embedding_metadata_by_ids(
            conn, memory_ids=[row.memory_id for row in page],
            profile_fingerprint=profile.fingerprint,
        )
        for row in page:
            existing = metadata.get(row.memory_id)
            if existing is None:
                missing += 1
            elif not existing.is_valid or existing.content_hash != build_embedding_document(row).content_hash:
                stale += 1
            else:
                ready += 1
    return EmbeddingStatus(
        profile_fingerprint=profile.fingerprint, backend=backend_id,
        total_active=total, ready=ready, missing=missing, stale=stale,
        active_profile_fingerprint=repository.active_profile_fingerprint(conn),
    )
