"""Sprint 4C: Hybrid Primary Search (Weighted Reciprocal Rank Fusion) tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from brain_twin import db, embedding_repository as repository, hybrid_search
from brain_twin.embedding_provider import EmbeddingProfile, VectorSearchUnavailableError
from brain_twin.retrieval_weights import RetrievalWeights, metadata_multiplier
from brain_twin.vector_exact import ExactScanBackend

FIXED_NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def _profile(**changes):
    values = dict(
        provider_id="fake", model_name="fake", model_revision=None,
        profile_epoch="hybrid-generation-1", embedding_contract_version=1,
        dimension=2, normalized=False, document_template_version=1,
    )
    values.update(changes)
    return EmbeddingProfile(**values)


def _memory(conn, memory_id, content, *, importance=3, confidence=1.0, event_date="2026-08-20", topics="[]"):
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at=f"{event_date}T00:00:00+00:00",
        event_date=event_date, importance=importance, confidence=confidence, source="test",
        status="active", title=content, content=content, raw_log_id=None,
        file_path=f"{memory_id}.md", topics_json=topics,
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
    def __init__(self, profile, vector=None):
        self._profile = profile
        self._vector = vector or [1.0, 0.0]

    @property
    def profile(self):
        return self._profile

    def embed_documents(self, texts):
        return [self._vector for _ in texts]

    def embed_query(self, text):
        return self._vector


def _ready_setup(config, *, profile=None, backend=None):
    """Three Memories matching the FTS phrase "shared phrase", with distinct vectors so "a"
    is the closest cosine match, "b" second, "c" orthogonal (worst)."""
    profile = profile or _profile()
    backend = backend or ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        for memory_id, vector in [("b", [1, 0]), ("a", [1, 0]), ("c", [0, 1])]:
            _memory(conn, memory_id, f"shared phrase content {memory_id}", topics='["work"]')
            _embedding(conn, profile, memory_id, vector)
        _activate(conn, profile, backend)
        conn.commit()
    return profile, backend


# ---- availability / input guards ----


def test_hybrid_search_respects_availability_gate(config):
    profile = _profile(); backend = ExactScanBackend()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        conn.commit()
        with pytest.raises(VectorSearchUnavailableError):
            hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=5)


def test_hybrid_search_short_query_returns_empty(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        assert hybrid_search.hybrid_search(conn, "ab", provider, backend, limit=5) == []


def test_hybrid_search_zero_limit_returns_empty(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        assert hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=0) == []


@pytest.mark.parametrize("kwargs", [
    dict(lexical_weight=-1), dict(vector_weight=-1),
    dict(lexical_weight=0, vector_weight=0), dict(rrf_k=0), dict(candidate_multiplier=0),
])
def test_retrieval_weights_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        RetrievalWeights(**kwargs)


# ---- channel coverage ----


def test_hybrid_search_lexical_only_hit_included(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        _memory(conn, "lex_only", "lexical only unique phrase text")
        _activate(conn, profile, backend); conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(
            conn, "lexical only unique phrase", provider, backend, limit=5, now=FIXED_NOW
        )
    assert len(results) == 1
    assert results[0].memory_id == "lex_only"
    assert results[0].vector_rank is None
    assert results[0].vector_similarity is None
    assert results[0].lexical_rank == 1


def test_hybrid_search_vector_only_hit_included(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        _memory(conn, "vec_only", "totally unrelated content not matching the query")
        _embedding(conn, profile, "vec_only", [1, 0])
        _activate(conn, profile, backend); conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(
            conn, "vector only search phrase", provider, backend, limit=5, now=FIXED_NOW
        )
    assert len(results) == 1
    assert results[0].memory_id == "vec_only"
    assert results[0].lexical_rank is None
    assert results[0].lexical_raw_score is None
    assert results[0].vector_rank == 1


def test_hybrid_search_dedupes_memory_present_in_both_channels(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)
    ids = [r.memory_id for r in results]
    assert len(ids) == len(set(ids))
    a = next(r for r in results if r.memory_id == "a")
    assert a.lexical_rank is not None
    assert a.vector_rank is not None


def test_hybrid_search_stale_memory_still_participates_via_lexical_channel(config):
    profile, backend = _ready_setup(config)
    with db.connect(config) as conn:
        # Changing content invalidates the embedding (trigger), but the new content still
        # matches the FTS phrase, so "a" must stay a lexical-only candidate.
        _memory(conn, "a", "shared phrase content a, now edited")
        conn.commit()
        results = hybrid_search.hybrid_search(conn, "shared phrase", provider=FakeQueryProvider(profile, [1, 0]), backend=backend, limit=10, now=FIXED_NOW)
    by_id = {r.memory_id: r for r in results}
    assert "a" in by_id
    assert by_id["a"].vector_rank is None
    assert by_id["a"].lexical_rank is not None


# ---- RRF formula and metadata multiplier ----


def test_hybrid_search_matches_weighted_rrf_formula(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    weights = RetrievalWeights(lexical_weight=0.6, vector_weight=0.4, rrf_k=60, candidate_multiplier=3)
    with db.connect(config) as conn:
        lexical = {c.memory_id: c for c in db.search_lexical_candidates(conn, "shared phrase", limit=10)}
        vector = {h.memory_id: h for h in backend.search(conn, profile.fingerprint, [1, 0], limit=10)}
        results = hybrid_search.hybrid_search(
            conn, "shared phrase", provider, backend, limit=10, weights=weights, now=FIXED_NOW
        )
    assert results  # sanity: candidates actually exist
    for r in results:
        expected = 0.0
        if r.memory_id in lexical:
            expected += weights.lexical_weight / (weights.rrf_k + lexical[r.memory_id].lexical_rank)
        if r.memory_id in vector:
            expected += weights.vector_weight / (weights.rrf_k + vector[r.memory_id].rank)
        assert r.fusion_score == pytest.approx(expected)
        assert r.lexical_rank == (lexical[r.memory_id].lexical_rank if r.memory_id in lexical else None)
        assert r.vector_rank == (vector[r.memory_id].rank if r.memory_id in vector else None)


def test_hybrid_search_final_score_equals_fusion_times_metadata_multiplier_applied_once(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)
    assert results
    for r in results:
        expected_multiplier = metadata_multiplier(
            importance=r.importance, confidence=r.confidence, event_date=r.event_date, now=FIXED_NOW
        )
        assert r.metadata_multiplier == pytest.approx(expected_multiplier)
        assert r.final_score == pytest.approx(r.fusion_score * expected_multiplier)


def test_hybrid_search_final_score_increases_with_higher_importance(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        before = {r.memory_id: r.final_score for r in hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)}
        _memory(conn, "a", "shared phrase content a", importance=5, topics='["work"]')
        conn.commit()
        after = {r.memory_id: r.final_score for r in hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)}
    assert after["a"] > before["a"]


def test_hybrid_search_final_score_increases_with_higher_confidence(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        _memory(conn, "a", "shared phrase content a", confidence=0.2, topics='["work"]')
        conn.commit()
        low = {r.memory_id: r.final_score for r in hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)}
        _memory(conn, "a", "shared phrase content a", confidence=1.0, topics='["work"]')
        conn.commit()
        high = {r.memory_id: r.final_score for r in hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)}
    assert high["a"] > low["a"]


def test_hybrid_search_final_score_increases_with_more_recent_event_date(config):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        _memory(conn, "a", "shared phrase content a", event_date="2000-01-01", topics='["work"]')
        conn.commit()
        old = {r.memory_id: r.final_score for r in hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)}
        _memory(conn, "a", "shared phrase content a", event_date="2026-08-24", topics='["work"]')
        conn.commit()
        recent = {r.memory_id: r.final_score for r in hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=10, now=FIXED_NOW)}
    assert recent["a"] > old["a"]


# ---- deterministic ordering ----


def test_hybrid_search_deterministic_tie_break_by_memory_id(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        _memory(conn, "tie_b", "tie phrase content only")  # lexical-only, rank 1
        _memory(conn, "tie_a", "unrelated content")  # vector-only, rank 1
        _embedding(conn, profile, "tie_a", [1, 0])
        _activate(conn, profile, backend)
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    weights = RetrievalWeights(lexical_weight=0.5, vector_weight=0.5, rrf_k=60, candidate_multiplier=3)
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(
            conn, "tie phrase content", provider, backend, limit=10, weights=weights, now=FIXED_NOW
        )
    assert [r.memory_id for r in results] == ["tie_a", "tie_b"]
    assert results[0].final_score == pytest.approx(results[1].final_score)


# ---- result limit / candidate overfetch / lazy detail fetch ----


def test_hybrid_search_respects_result_limit(config):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        for i in range(5):
            _memory(conn, f"m{i}", f"limit test hybrid phrase number {i}")
        _activate(conn, profile, backend)
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(conn, "limit test hybrid phrase", provider, backend, limit=2, now=FIXED_NOW)
    assert len(results) == 2


def test_hybrid_search_uses_candidate_multiplier_for_channel_overfetch(config, monkeypatch):
    profile, backend = _ready_setup(config)
    provider = FakeQueryProvider(profile, [1, 0])
    weights = RetrievalWeights(candidate_multiplier=5)
    seen = {}
    real_lexical = db.search_lexical_candidates

    def spy_lexical(conn, query, *, limit):
        seen["lexical_limit"] = limit
        return real_lexical(conn, query, limit=limit)

    monkeypatch.setattr(db, "search_lexical_candidates", spy_lexical)
    real_backend_search = backend.search

    def spy_backend_search(conn, fingerprint, query_vector, *, limit):
        seen["vector_limit"] = limit
        return real_backend_search(conn, fingerprint, query_vector, limit=limit)

    monkeypatch.setattr(backend, "search", spy_backend_search)

    with db.connect(config) as conn:
        hybrid_search.hybrid_search(conn, "shared phrase", provider, backend, limit=3, weights=weights, now=FIXED_NOW)

    assert seen["lexical_limit"] == 15
    assert seen["vector_limit"] == 15


def test_hybrid_search_fetches_full_detail_only_for_final_top_n(config, monkeypatch):
    profile = _profile(); backend = ExactScanBackend()
    with db.connect(config) as conn:
        db.upsert_embedding_profile(conn, profile, created_at="now")
        for i in range(6):
            _memory(conn, f"m{i}", f"top n detail phrase number {i}", topics='["work"]')
        _activate(conn, profile, backend)
        conn.commit()
    provider = FakeQueryProvider(profile, [1, 0])
    real_details = db.memory_result_details_by_ids
    seen_ids = []

    def spy(conn, memory_ids):
        seen_ids.append(sorted(memory_ids))
        return real_details(conn, memory_ids)

    monkeypatch.setattr(db, "memory_result_details_by_ids", spy)
    with db.connect(config) as conn:
        results = hybrid_search.hybrid_search(conn, "top n detail phrase", provider, backend, limit=2, now=FIXED_NOW)

    # Detail fetch (title/content/topics/entities) happens exactly once, only for the
    # final top-2 ids -- never for the full 6-candidate pool.
    assert len(seen_ids) == 1
    assert len(seen_ids[0]) == 2
    assert len(results) == 2
    assert all(r.topics == ["work"] for r in results)
