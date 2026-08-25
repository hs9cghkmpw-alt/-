import sqlite3

import pytest

from brain_twin import db
from brain_twin.embedding_provider import EmbeddingDimensionError, EmbeddingProfile
from brain_twin.pipeline import reindex
from brain_twin.vector_exact import ExactScanBackend


def _profile(**changes):
    values = dict(
        provider_id="fake", model_name="fake", model_revision=None,
        profile_epoch="test-generation-1", embedding_contract_version=1,
        dimension=2, normalized=True, document_template_version=1,
    )
    values.update(changes)
    return EmbeddingProfile(**values)


def _memory(conn, memory_id, *, status="active"):
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at="2026-08-25T00:00:00+09:00",
        event_date="2026-08-25", importance=3, confidence=1.0, source="test",
        status=status, title="title", content="content", raw_log_id=None,
        file_path=f"{memory_id}.md", topics_json="[]",
    )


def _embedding(conn, profile, memory_id, vector):
    db.upsert_memory_embedding(
        conn, memory_id=memory_id, profile=profile, content_hash="a" * 64,
        vector=vector, embedded_at="2026-08-25T00:00:00+09:00",
    )


def test_legacy_database_gets_non_destructive_embedding_migration(config):
    config.data_dir.mkdir(parents=True)
    old = sqlite3.connect(config.db_path)
    old.execute("CREATE TABLE legacy_keep (value TEXT)")
    old.execute("INSERT INTO legacy_keep VALUES ('preserved')")
    old.commit(); old.close()
    with db.connect(config) as conn:
        assert conn.execute("SELECT value FROM legacy_keep").fetchone()[0] == "preserved"
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"embedding_profiles", "memory_embeddings", "active_embedding_state", "vector_backend_state"} <= names


def test_schema_db_check_rejects_missing_generation_key(config):
    with db.connect(config) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO embedding_profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fp", "p", "m", None, None, 1, 2, 1, 1, "now"),
        )


def test_reindex_requires_no_provider_and_recreates_empty_cache_tables(config):
    counts = reindex(config)
    assert counts["memories"] == 0
    with db.connect(config) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0


def test_connect_recreates_all_dropped_embedding_cache_tables(config):
    with db.connect(config) as conn:
        conn.executescript(
            "DROP TABLE vector_backend_state; DROP TABLE active_embedding_state; "
            "DROP TABLE memory_embeddings; DROP TABLE embedding_profiles;"
        )
    with db.connect(config) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"embedding_profiles", "memory_embeddings", "active_embedding_state", "vector_backend_state"} <= names


def test_memory_delete_cascades_embedding(config):
    profile = _profile()
    with db.connect(config) as conn:
        _memory(conn, "mem_1"); db.upsert_embedding_profile(conn, profile, created_at="now")
        _embedding(conn, profile, "mem_1", [1, 0]); conn.commit()
        conn.execute("DELETE FROM memories WHERE id='mem_1'"); conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0


def test_exact_scan_known_vectors_top_k_and_deterministic_tie_order(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        for memory_id, vector in [("b", [1, 0]), ("a", [1, 0]), ("c", [0, 1])]:
            _memory(conn, memory_id); _embedding(conn, profile, memory_id, vector)
        results = backend.search(conn, profile.fingerprint, [1, 0], limit=2)
        assert [(r.memory_id, r.rank) for r in results] == [("a", 1), ("b", 2)]
        assert results[0].similarity == pytest.approx(1.0)


def test_exact_scan_excludes_inactive_memory(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        _memory(conn, "inactive", status="archived"); _embedding(conn, profile, "inactive", [1, 0])
        _memory(conn, "active"); _embedding(conn, profile, "active", [0, 1])
        assert [r.memory_id for r in backend.search(conn, profile.fingerprint, [1, 0], limit=5)] == ["active"]


def test_exact_scan_empty_index(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        assert backend.search(conn, profile.fingerprint, [1, 0], limit=5) == []


def test_exact_scan_rejects_query_dimension_mismatch(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        with pytest.raises(EmbeddingDimensionError):
            backend.search(conn, profile.fingerprint, [1], limit=5)


def test_exact_build_uses_canonical_cache_without_provider(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        _memory(conn, "mem_1"); _embedding(conn, profile, "mem_1", [1, 0])
        assert backend.build(conn, profile.fingerprint) == 1
        assert backend.search(conn, profile.fingerprint, [1, 0], limit=1)[0].memory_id == "mem_1"
