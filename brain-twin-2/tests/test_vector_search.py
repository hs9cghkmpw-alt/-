"""Sprint 4C: Vector Primary Search tests."""
from __future__ import annotations

import pytest

from brain_twin import db, embedding_repository as repository, vector_search
from brain_twin.embedding_provider import (
    EmbeddingDimensionError, EmbeddingProfile, EmbeddingValidationError,
    VectorSearchUnavailableError,
)
from brain_twin.vector_exact import ExactScanBackend


def _profile(**changes):
    values = dict(
        provider_id="fake", model_name="fake", model_revision=None,
        profile_epoch="vector-generation-1", embedding_contract_version=1,
        dimension=2, normalized=False, document_template_version=1,
    )
    values.update(changes)
    return EmbeddingProfile(**values)


def _memory(conn, memory_id, *, status="active", title=None, content=None, importance=3, confidence=1.0, event_date="2026-08-20"):
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at=f"{event_date}T00:00:00+00:00",
        event_date=event_date, importance=importance, confidence=confidence, source="test",
        status=status, title=title or memory_id, content=content or f"content {memory_id}",
        raw_log_id=None, file_path=f"{memory_id}.md", topics_json="[]",
    )


def _embedding(conn, profile, memory_id, vector):
    db.upsert_memory_embedding(
        conn, memory_id=memory_id, profile=profile, content_hash="a" * 64,
        vector=vector, embedded_at="2026-08-25T00:00:00+00:00",
    )


def _activate(conn, profile, backend):
    repository.set_active_profile(conn, profile.fingerprint)
    repository.set_backend_state(
        conn, backend=backend.backend_id, schema_version=backend.schema_version,
        profile_fingerprint=profile.fingerprint, build_status="ready", built_at="now",
    )


class FakeQueryProvider:
    def __init__(self, profile, vector=None, *, calls=None):
        self._profile = profile
        self._vector = vector or [1.0, 0.0]
        self.queries = calls if calls is not None else []

    @property
    def profile(self):
        return self._profile

    def embed_documents(self, texts):
        return [self._vector for _ in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return self._vector


def _ready_setup(config, *, vector=None, profile=None, backend=None):
    profile = profile or _profile()
    backend = backend or ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        for memory_id, mem_vector in [("b", [1, 0]), ("a", [1, 0]), ("c", [0, 1])]:
            _memory(conn, memory_id)
            _embedding(conn, profile, memory_id, mem_vector)
        _activate(conn, profile, backend)
        conn.commit()
    return profile, backend


def test_vector_search_known_vectors_top_k_and_deterministic_tie(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = vector_search.vector_search(conn, "query", provider, backend, limit=2)
    assert [(r.memory_id, r.vector_rank) for r in results] == [("a", 1), ("b", 2)]
    assert results[0].similarity == pytest.approx(1.0)
    assert results[0].title == "a"


def test_vector_search_excludes_inactive_memory(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        _memory(conn, "inactive", status="archived"); _embedding(conn, profile, "inactive", [1, 0])
        _memory(conn, "active"); _embedding(conn, profile, "active", [1, 0])
        _activate(conn, profile, backend); conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = vector_search.vector_search(conn, "query", provider, backend, limit=5)
    assert [r.memory_id for r in results] == ["active"]


def test_vector_search_excludes_stale_embedding(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        _memory(conn, "a", content="changed"); conn.commit()  # trigger invalidates "a"
        results = vector_search.vector_search(conn, "query", provider, backend, limit=5)
    assert "a" not in {r.memory_id for r in results}


def test_vector_search_rejects_active_profile_mismatch(config):
    profile, backend = _ready_setup(config)
    other = _profile(profile_epoch="a-different-generation")
    provider = FakeQueryProvider(other, [1, 0])
    with db.connect(config) as conn:
        with pytest.raises(VectorSearchUnavailableError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_backend_id_mismatch(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        repository.set_active_profile(conn, profile.fingerprint)
        repository.set_backend_state(
            conn, backend="sqlite_vec", schema_version=backend.schema_version,
            profile_fingerprint=profile.fingerprint, build_status="ready", built_at="now",
        )
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        with pytest.raises(VectorSearchUnavailableError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_backend_schema_mismatch(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        repository.set_active_profile(conn, profile.fingerprint)
        repository.set_backend_state(
            conn, backend=backend.backend_id, schema_version=backend.schema_version + 1,
            profile_fingerprint=profile.fingerprint, build_status="ready", built_at="now",
        )
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        with pytest.raises(VectorSearchUnavailableError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_indexed_profile_mismatch(config):
    profile = _profile(); backend = ExactScanBackend()
    other = _profile(profile_epoch="stale-indexed-profile")
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        db.upsert_embedding_profile(conn, other, created_at="now")
        repository.set_active_profile(conn, profile.fingerprint)
        repository.set_backend_state(
            conn, backend=backend.backend_id, schema_version=backend.schema_version,
            profile_fingerprint=other.fingerprint, build_status="ready", built_at="now",
        )
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        with pytest.raises(VectorSearchUnavailableError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_backend_not_ready(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        repository.set_active_profile(conn, profile.fingerprint)
        repository.set_backend_state(
            conn, backend=backend.backend_id, schema_version=backend.schema_version,
            profile_fingerprint=profile.fingerprint, build_status="building", built_at=None,
        )
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        with pytest.raises(VectorSearchUnavailableError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_query_dimension_mismatch(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0, 0])  # profile dimension is 2
    with db.connect(config) as conn:
        with pytest.raises(EmbeddingDimensionError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_query_nan(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [float("nan"), 0.0])
    with db.connect(config) as conn:
        with pytest.raises(EmbeddingValidationError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_query_inf(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [float("inf"), 0.0])
    with db.connect(config) as conn:
        with pytest.raises(EmbeddingValidationError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_rejects_query_zero_vector(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [0.0, 0.0])
    with db.connect(config) as conn:
        with pytest.raises(EmbeddingValidationError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_normalized_profile_rejects_query_norm_violation(config):
    profile, backend = _ready_setup(config, profile=_profile(normalized=True))
    provider = FakeQueryProvider(profile, [1.0, 1.0])  # norm sqrt(2) != 1
    with db.connect(config) as conn:
        with pytest.raises(EmbeddingValidationError):
            vector_search.vector_search(conn, "query", provider, backend, limit=5)


def test_vector_search_does_not_load_full_body_before_top_n(config, monkeypatch):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    real_details = db.memory_result_details_by_ids
    seen_ids = []

    def spy(conn, memory_ids):
        seen_ids.append(list(memory_ids))
        return real_details(conn, memory_ids)

    monkeypatch.setattr(db, "memory_result_details_by_ids", spy)
    with db.connect(config) as conn:
        vector_search.vector_search(conn, "query", provider, backend, limit=1)

    # Detail fetch happens exactly once, only for the backend's already-ranked top-K ids.
    assert len(seen_ids) == 1
    assert len(seen_ids[0]) == 1


def test_vector_search_does_not_persist_query_text(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        vector_search.vector_search(conn, "this exact query text must not be stored", provider, backend, limit=5)
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for column in columns:
                for row in conn.execute(f"SELECT {column} FROM {table}"):
                    assert row[0] != "this exact query text must not be stored"


def test_vector_search_empty_limit_returns_empty(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        assert vector_search.vector_search(conn, "query", provider, backend, limit=0) == []
