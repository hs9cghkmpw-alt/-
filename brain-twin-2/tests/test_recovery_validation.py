"""Sprint 4D: end-to-end failure/recovery/migration validation (item 6, 7).

Most individual failure-mode mechanics (partial provider failure resume, profile-switch
failure keeping the old active profile, backend-only rebuild never calling the provider,
inactive/malformed/dimension-mismatch rejection, legacy self-heal on missing columns) are
already covered by focused unit tests in `test_embedding_service.py`, `test_vector_search.py`,
`test_vector_storage.py`, and `test_db_entities_links.py`. This file adds the full end-to-end
loops that exercise those mechanics *through* `vector_search()`/`hybrid_search()`/
`retrieval.retrieve_from_primary()` (not just internal repository state), plus the complete
"delete the SQLite file, reindex from Markdown, resync embeddings" recovery flow -- the single
most important recovery path, since SQLite is a rebuildable cache and Markdown is the source
of truth.
"""
from __future__ import annotations

from pathlib import Path

from brain_twin import (
    db, embedding_repository as repository, hybrid_search, pipeline, retrieval, search,
    vector_search,
)
from brain_twin.embedding_provider import EmbeddingProfile, VectorSearchUnavailableError
from brain_twin.embedding_service import EmbeddingService
from brain_twin.vector_exact import ExactScanBackend


def _profile(**changes):
    values = dict(
        provider_id="fake", model_name="fake", model_revision=None,
        profile_epoch="recovery-generation-1", embedding_contract_version=1,
        dimension=3, normalized=False, document_template_version=1,
    )
    values.update(changes)
    return EmbeddingProfile(**values)


class DeterministicProvider:
    """Offline, deterministic -- same shape as tests/fake_embedding_provider.py, defined
    locally so this file has no cross-test-module import."""

    def __init__(self, profile=None):
        self._profile = profile or _profile()

    @property
    def profile(self):
        return self._profile

    def _vector(self, text: str) -> list[float]:
        seed = sum(text.encode("utf-8")) or 1
        return [float((seed + i) % 13 + 1) for i in range(self._profile.dimension)]

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


def _memory(conn, memory_id, *, title=None, content=None, status="active"):
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at="2026-08-25T00:00:00+09:00",
        event_date="2026-08-25", importance=3, confidence=1.0, source="test",
        status=status, title=title or f"title {memory_id}", content=content or f"content {memory_id}",
        raw_log_id=None, file_path=f"{memory_id}.md", topics_json="[]",
    )


# ---- 6C: backend index / bookkeeping loss -> unavailable -> backend-only rebuild -> recovered ----

def test_backend_index_loss_recovers_via_backend_only_rebuild_without_provider(config):
    provider = DeterministicProvider()
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    service = EmbeddingService(config, provider, ExactScanBackend())
    service.sync()

    with db.connect(config) as conn:
        vector_search.vector_search(conn, "content a", provider, ExactScanBackend(), limit=5)

    # Simulate losing the derived backend index/bookkeeping (e.g. vector_backend_state wiped
    # by an operator, or a fresh backend adapter with no build history) while the canonical
    # embedding BLOBs remain untouched.
    with db.connect(config) as conn:
        conn.execute("DELETE FROM vector_backend_state")
        conn.commit()

    class _FailIfCalled:
        def embed_documents(self, texts):
            raise AssertionError("backend-only rebuild must never call the provider")

        def embed_query(self, text):
            raise AssertionError("backend-only rebuild must never call the provider")

        @property
        def profile(self):
            return provider.profile

    with db.connect(config) as conn:
        try:
            vector_search.vector_search(conn, "content a", provider, ExactScanBackend(), limit=5)
            assert False, "vector_search should be unavailable once backend state is lost"
        except VectorSearchUnavailableError:
            pass

    recovery_service = EmbeddingService(config, _FailIfCalled(), ExactScanBackend())
    rebuilt_count = recovery_service.rebuild_backend()
    assert rebuilt_count == 1

    with db.connect(config) as conn:
        results = vector_search.vector_search(conn, "content a", provider, ExactScanBackend(), limit=5)
    assert [r.memory_id for r in results] == ["a"]


# ---- 6D: stale Memory -> excluded from Vector-only, still found via Hybrid's lexical channel,
#          restored to Vector after the next sync ----

def test_stale_memory_excluded_from_vector_but_reachable_via_hybrid_lexical_until_resync(config):
    provider = DeterministicProvider()
    backend = ExactScanBackend()
    with db.connect(config) as conn:
        _memory(conn, "a", title="unique stale marker phrase", content="unique stale marker phrase")
        conn.commit()
    service = EmbeddingService(config, provider, backend)
    service.sync()

    with db.connect(config) as conn:
        before = vector_search.vector_search(conn, "unique stale marker phrase", provider, backend, limit=5)
    assert [r.memory_id for r in before] == ["a"]

    # Title/content change invalidates the cached vector (SQLite trigger), simulating a Memory
    # edited after being embedded but before the next sync runs.
    with db.connect(config) as conn:
        _memory(conn, "a", title="unique stale marker phrase changed", content="unique stale marker phrase changed")
        conn.commit()

    with db.connect(config) as conn:
        vector_only = vector_search.vector_search(
            conn, "unique stale marker phrase changed", provider, backend, limit=5
        )
        assert vector_only == []  # stale vector correctly excluded, not served as if valid

        # Hybrid degrades gracefully: its lexical (BM25) channel is independent of embedding
        # validity, so the Memory is still findable through Hybrid while Vector alone can't see it.
        hybrid_hits = hybrid_search.hybrid_search(
            conn, "unique stale marker phrase changed", provider, backend, limit=5
        )
        assert [r.memory_id for r in hybrid_hits] == ["a"]
        assert hybrid_hits[0].vector_rank is None
        assert hybrid_hits[0].lexical_rank is not None

    # The next sync re-embeds the changed content and Vector search recovers.
    assert service.sync().embedded == 1
    with db.connect(config) as conn:
        after = vector_search.vector_search(
            conn, "unique stale marker phrase changed", provider, backend, limit=5
        )
    assert [r.memory_id for r in after] == ["a"]


# ---- 7: full SQLite deletion -> reindex from Markdown -> resync embeddings (most important) ----

def test_full_sqlite_delete_recovery_restores_lexical_link_and_vector_search(config):
    # Build a small Vault through the real pipeline (Markdown + auto-generated Links), not
    # direct DB inserts, so this test exercises the same Markdown-is-source-of-truth path a
    # real crash-recovery would go through.
    pipeline.add_capture(config, "ナイキの特別なランニングシューズを買って走るのが楽しみ")
    pipeline.process_all(config)
    pipeline.add_capture(config, "ナイキ本社について詳しく調べて考えたことを記録する")
    pipeline.process_all(config)

    before_search = [r.memory_id for r in search.search_with_config(config, "ランニングシューズ")]
    assert before_search
    before_retrieval = retrieval.retrieve_with_config(config, "ランニングシューズ")
    assert before_retrieval.related  # confirms a real Link exists to validate recovery against

    provider = DeterministicProvider()
    backend = ExactScanBackend()
    EmbeddingService(config, provider, backend).sync()
    with db.connect(config) as conn:
        before_vector = vector_search.vector_search(conn, "ランニングシューズ", provider, backend, limit=5)
    assert before_vector

    # Snapshot every Markdown file in the Vault (Memory, Daily Log, and Raw Log alike) so we
    # can prove none of it was touched by deleting/rebuilding the derived SQLite cache.
    markdown_before = {
        path: path.read_bytes() for path in config.vault_dir.rglob("*.md")
    }
    assert markdown_before

    # Simulate total SQLite loss (corruption, accidental delete, disk failure recovery, ...).
    config.db_path.unlink()

    counts = pipeline.reindex(config)
    assert counts["memories"] == 2
    assert counts["links"] >= 1

    markdown_after = {path: path.read_bytes() for path in config.vault_dir.rglob("*.md")}
    assert markdown_after == markdown_before  # Markdown/Raw Log content is untouched by reindex

    after_search = [r.memory_id for r in search.search_with_config(config, "ランニングシューズ")]
    assert after_search == before_search  # Memory metadata + FTS fully restored

    after_retrieval = retrieval.retrieve_with_config(config, "ランニングシューズ")
    assert after_retrieval.related == before_retrieval.related  # Link/strength restored

    # Embeddings/vector state are derived, not source-of-truth, so it is correct that they do
    # not survive the SQLite delete -- Vector Search must now report unavailable...
    with db.connect(config) as conn:
        try:
            vector_search.vector_search(conn, "ランニングシューズ", provider, backend, limit=5)
            assert False, "vector search must be unavailable immediately after a SQLite rebuild"
        except VectorSearchUnavailableError:
            pass

    # ...until an offline-provider resync recreates the canonical cache and backend index.
    result = EmbeddingService(config, provider, backend).sync()
    assert result.embedded == counts["memories"]

    with db.connect(config) as conn:
        after_vector = vector_search.vector_search(conn, "ランニングシューズ", provider, backend, limit=5)
        assert [r.memory_id for r in after_vector] == [r.memory_id for r in before_vector]

        after_hybrid = hybrid_search.hybrid_search(conn, "ランニングシューズ", provider, backend, limit=5)
        assert after_hybrid

        # limit=1 here (not 5): with only two Memories in this dataset, a limit=5 Hybrid
        # Primary already surfaces both linked Memories directly, which correctly leaves
        # `related` empty (a primary result is never duplicated into `related`; see
        # test_primary_is_never_in_related_even_when_primaries_are_linked in
        # test_retrieval.py). limit=1 forces the linked Memory out of `primary` so this
        # assertion actually exercises 1-hop expansion recovery, not just Hybrid Primary.
        hybrid_primary_top1 = hybrid_search.hybrid_search(conn, "ランニングシューズ", provider, backend, limit=1)
        hybrid_related = retrieval.retrieve_from_primary(conn, hybrid_primary_top1, related_limit=5)
        assert hybrid_related.related  # Hybrid Primary + 1-hop Associative Retrieval both recovered
