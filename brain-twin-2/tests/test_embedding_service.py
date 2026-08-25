import math
from dataclasses import replace

import pytest

from brain_twin import db, embedding_repository as repository, memory_io
from brain_twin.embedding_provider import (
    EmbeddingConfigurationError, EmbeddingDimensionError, EmbeddingProfile,
    EmbeddingTransientError, EmbeddingValidationError,
)
from brain_twin.embedding_service import EmbeddingService, EmbeddingSyncPolicy
from brain_twin.pipeline import reindex
from brain_twin.models import Memory, MemoryStatus, MemoryType
from brain_twin.vector_exact import ExactScanBackend


class RecordingProvider:
    def __init__(self, profile=None, *, fail_calls=None, outputs=None):
        self._profile = profile or _profile()
        self.fail_calls = dict(fail_calls or {})
        self.outputs = outputs
        self.batches = []

    @property
    def profile(self):
        return self._profile

    def embed_documents(self, texts):
        self.batches.append(list(texts))
        error = self.fail_calls.get(len(self.batches))
        if error:
            raise error
        if self.outputs is not None:
            return self.outputs(texts)
        vectors = []
        for text in texts:
            seed = sum(text.encode("utf-8")) or 1
            vectors.append([float((seed + i) % 17 + 1) for i in range(self.profile.dimension)])
        return vectors

    def embed_query(self, text):
        return self.embed_documents([text])[0]


class FailingBuildBackend(ExactScanBackend):
    def build(self, conn, profile_fingerprint):
        raise RuntimeError("build failed")


class TrackingBackend(ExactScanBackend):
    def __init__(self, *, fail_build=False):
        self.fail_build = fail_build
        self.sync_upserts = []
        self.builds = []

    def sync_upsert(self, conn, memory_id, profile_fingerprint, vector):
        self.sync_upserts.append((memory_id, profile_fingerprint, len(vector)))
        return super().sync_upsert(conn, memory_id, profile_fingerprint, vector)

    def build(self, conn, profile_fingerprint):
        self.builds.append(profile_fingerprint)
        if self.fail_build:
            raise RuntimeError("build failed")
        return super().build(conn, profile_fingerprint)


def _profile(*, epoch="generation-1", dimension=3, normalized=False):
    return EmbeddingProfile(
        provider_id="fake", model_name="fake", model_revision=None,
        profile_epoch=epoch, embedding_contract_version=1, dimension=dimension,
        normalized=normalized, document_template_version=1,
    )


def _memory(conn, memory_id, *, title=None, content=None, status="active", type="thought", topics="[]"):
    db.upsert_memory(
        conn, id=memory_id, type=type, created_at="2026-08-25T00:00:00+09:00",
        event_date="2026-08-25", importance=3, confidence=1.0, source="test",
        status=status, title=title or f"title {memory_id}", content=content or f"content {memory_id}",
        raw_log_id=None, file_path=f"{memory_id}.md", topics_json=topics,
    )


def _service(config, provider=None, backend=None, **policy):
    return EmbeddingService(
        config, provider or RecordingProvider(), backend or ExactScanBackend(),
        policy=EmbeddingSyncPolicy(**policy) if policy else EmbeddingSyncPolicy(),
        sleep=lambda _: None,
    )


def test_sync_embeds_missing_then_skips_matching_hash(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); _memory(conn, "b"); conn.commit()
    provider = RecordingProvider(); service = _service(config, provider)
    first = service.sync(); second = service.sync()
    assert (first.embedded, first.skipped) == (2, 0)
    assert (second.embedded, second.skipped) == (0, 2)
    assert len(provider.batches) == 1


@pytest.mark.parametrize("field", ["title", "content"])
def test_title_or_content_change_reembeds(config, field):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); service = _service(config, provider); service.sync()
    with db.connect(config) as conn:
        changes = {field: "changed"}
        _memory(conn, "a", **changes); conn.commit()
    assert service.sync().embedded == 1


@pytest.mark.parametrize("change", [
    {"type": "fact"}, {"topics": '["new"]'}, {"entity": "Entity"},
])
def test_metadata_only_change_does_not_reembed(config, change):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); service = _service(config, provider); service.sync()
    with db.connect(config) as conn:
        if "entity" in change:
            entity_id = db.get_or_create_entity(conn, change["entity"])
            conn.execute("INSERT INTO memory_entities(memory_id, entity_id) VALUES ('a', ?)", (entity_id,))
        else:
            _memory(conn, "a", **change)
        conn.commit()
    assert service.sync().skipped == 1
    assert len(provider.batches) == 1


def test_profile_and_epoch_change_create_new_generation(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    first = RecordingProvider(_profile(epoch="one")); _service(config, first).sync()
    second = RecordingProvider(_profile(epoch="two")); result = _service(config, second).sync()
    assert result.embedded == 1
    with db.connect(config) as conn:
        assert conn.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] == 2
        assert repository.active_profile_fingerprint(conn) == second.profile.fingerprint


def test_archived_memory_is_excluded(config):
    with db.connect(config) as conn:
        _memory(conn, "active"); _memory(conn, "archived", status="archived"); conn.commit()
    provider = RecordingProvider(); result = _service(config, provider).sync()
    assert result.embedded == 1
    assert provider.batches[0][0].startswith("title: title active")


def test_delete_cache_then_sync_regenerates_and_explicit_delete_syncs_backend(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); service = _service(config, provider); service.sync()
    service.delete_cached_embedding("a")
    assert service.status().missing == 1
    assert service.sync().embedded == 1


@pytest.mark.parametrize("outputs,error", [
    (lambda texts: [], EmbeddingValidationError),
    (lambda texts: [[1.0]], EmbeddingDimensionError),
    (lambda texts: [[math.nan, 1.0, 2.0]], EmbeddingValidationError),
    (lambda texts: [[math.inf, 1.0, 2.0]], EmbeddingValidationError),
    (lambda texts: [[0.0, 0.0, 0.0]], EmbeddingValidationError),
])
def test_malformed_provider_batch_is_not_saved(config, outputs, error):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(outputs=outputs)
    with pytest.raises(error):
        _service(config, provider).sync()
    with db.connect(config) as conn:
        assert conn.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] == 0


def test_normalized_profile_contract_is_validated(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(
        _profile(normalized=True), outputs=lambda texts: [[1.0, 1.0, 0.0]]
    )
    with pytest.raises(EmbeddingValidationError):
        _service(config, provider).sync()


def test_provider_and_db_batch_sizes_are_respected(config, monkeypatch):
    with db.connect(config) as conn:
        for i in range(7): _memory(conn, f"m{i}")
        conn.commit()
    seen_limits = []
    real_page = repository.active_memories_page
    def spy_page(conn, *, after_memory_id, limit):
        seen_limits.append(limit)
        return real_page(conn, after_memory_id=after_memory_id, limit=limit)
    monkeypatch.setattr(repository, "active_memories_page", spy_page)
    provider = RecordingProvider()
    _service(config, provider, provider_batch_size=2, db_read_batch_size=3, commit_batch_size=1).sync()
    assert all(len(batch) <= 2 for batch in provider.batches)
    assert set(seen_limits) == {3}


def test_partial_progress_is_resumed_without_reembedding_success(config):
    with db.connect(config) as conn:
        for i in range(5): _memory(conn, f"m{i}")
        conn.commit()
    failing = RecordingProvider(fail_calls={2: EmbeddingConfigurationError("stop")})
    with pytest.raises(EmbeddingConfigurationError):
        _service(config, failing, provider_batch_size=2, db_read_batch_size=10).sync()
    with db.connect(config) as conn:
        assert conn.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] == 2
    resumed = RecordingProvider()
    result = _service(config, resumed, provider_batch_size=2, db_read_batch_size=10).sync()
    assert (result.embedded, result.skipped) == (3, 2)
    assert sum(map(len, resumed.batches)) == 3


def test_transient_error_retries_with_injected_sleep(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(fail_calls={1: EmbeddingTransientError("retry")})
    sleeps = []
    service = EmbeddingService(
        config, provider, ExactScanBackend(),
        policy=EmbeddingSyncPolicy(transient_retry_count=2, retry_base_delay_seconds=0.5),
        sleep=sleeps.append,
    )
    assert service.sync().embedded == 1
    assert sleeps == [0.5]


def test_transient_retry_limit_is_bounded(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(fail_calls={
        1: EmbeddingTransientError("x"), 2: EmbeddingTransientError("x"),
    })
    with pytest.raises(EmbeddingTransientError):
        _service(config, provider, transient_retry_count=1).sync()
    assert len(provider.batches) == 2


@pytest.mark.parametrize("error", [
    EmbeddingConfigurationError("bad"), EmbeddingDimensionError("bad"),
    EmbeddingValidationError("bad"),
])
def test_permanent_errors_are_not_retried(config, error):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(fail_calls={1: error})
    with pytest.raises(type(error)):
        _service(config, provider, transient_retry_count=5).sync()
    assert len(provider.batches) == 1


def test_profile_switch_occurs_only_after_successful_build(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    old = RecordingProvider(_profile(epoch="old")); _service(config, old).sync()
    new = RecordingProvider(_profile(epoch="new"))
    with pytest.raises(RuntimeError):
        _service(config, new, FailingBuildBackend()).sync()
    with db.connect(config) as conn:
        assert repository.active_profile_fingerprint(conn) == old.profile.fingerprint
        assert conn.execute(
            "SELECT count(*) FROM memory_embeddings WHERE profile_fingerprint = ?",
            (new.profile.fingerprint,),
        ).fetchone()[0] == 1
    assert _service(config, new).sync().skipped == 1


def test_partial_new_profile_failure_keeps_old_active_and_resumes(config):
    with db.connect(config) as conn:
        for i in range(3): _memory(conn, f"m{i}")
        conn.commit()
    old = RecordingProvider(_profile(epoch="old")); _service(config, old).sync()
    new_profile = _profile(epoch="new")
    broken = RecordingProvider(new_profile, fail_calls={2: EmbeddingConfigurationError("stop")})
    with pytest.raises(EmbeddingConfigurationError):
        _service(config, broken, provider_batch_size=2).sync()
    with db.connect(config) as conn:
        assert repository.active_profile_fingerprint(conn) == old.profile.fingerprint
    resumed = RecordingProvider(new_profile)
    assert _service(config, resumed).sync().skipped == 2


def test_status_makes_config_and_active_profile_mismatch_explicit(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    old = RecordingProvider(_profile(epoch="old")); _service(config, old).sync()
    status = _service(config, RecordingProvider(_profile(epoch="new"))).status()
    assert not status.active_matches_config
    assert status.active_profile_fingerprint == old.profile.fingerprint


def test_backend_only_rebuild_never_calls_provider(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); service = _service(config, provider); service.sync()
    provider.batches.clear()
    assert service.rebuild_backend() == 1
    assert provider.batches == []


def test_backend_only_rebuild_rejects_incomplete_canonical_cache(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider()
    with pytest.raises(EmbeddingValidationError):
        _service(config, provider).rebuild_backend()
    assert provider.batches == []


def test_explicit_rebuild_calls_provider_and_is_idempotent(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); service = _service(config, provider); service.sync()
    assert service.rebuild().embedded == 1
    assert service.rebuild().embedded == 1
    with db.connect(config) as conn:
        assert conn.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] == 1


def test_normal_reindex_succeeds_without_provider_and_keeps_fts_usable(config):
    counts = reindex(config)
    assert counts["memories"] == 0
    with db.connect(config) as conn:
        assert conn.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] == 0


def test_embedding_rebuild_failure_does_not_break_lexical_fts(config):
    with db.connect(config) as conn:
        _memory(conn, "a", title="Brain Twin memory"); conn.commit()
    provider = RecordingProvider(fail_calls={1: EmbeddingConfigurationError("offline")})
    with pytest.raises(EmbeddingConfigurationError):
        _service(config, provider).rebuild()
    with db.connect(config) as conn:
        assert db.search(conn, "Brain Twin", limit=5)[0].memory_id == "a"


def test_cache_deleted_after_vault_reindex_is_rebuilt_from_markdown_memory(config):
    memory_io.write_memory(config, Memory(
        id="mem_vault", type=MemoryType.THOUGHT,
        created_at="2026-08-25T00:00:00+09:00", event_date="2026-08-25",
        importance=3, confidence=1.0, source="test", status=MemoryStatus.ACTIVE,
        title="Vault title", content="Vault content", raw_log_id=None,
    ))
    assert reindex(config)["memories"] == 1
    provider = RecordingProvider(); service = _service(config, provider); service.sync()
    service.delete_cached_embedding("mem_vault")
    assert service.rebuild().embedded == 1
    with db.connect(config) as conn:
        assert conn.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] == 1


def test_staging_profile_does_not_sync_upsert_before_activation(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    backend = TrackingBackend()
    old = RecordingProvider(_profile(epoch="old", dimension=3))
    _service(config, old, backend).sync()
    backend.sync_upserts.clear(); backend.builds.clear()

    new = RecordingProvider(_profile(epoch="new", dimension=5))
    result = _service(config, new, backend).sync()
    assert backend.sync_upserts == []
    assert backend.builds == [new.profile.fingerprint]
    assert result.active_switched


def test_staging_provider_failure_leaves_active_backend_untouched(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); _memory(conn, "b"); conn.commit()
    backend = TrackingBackend(); old = RecordingProvider(_profile(epoch="old"))
    _service(config, old, backend).sync()
    backend.sync_upserts.clear(); backend.builds.clear()
    old_state = None
    with db.connect(config) as conn:
        old_state = repository.backend_state(conn)
    new = RecordingProvider(
        _profile(epoch="new"), fail_calls={2: EmbeddingConfigurationError("stop")}
    )
    with pytest.raises(EmbeddingConfigurationError):
        _service(config, new, backend, provider_batch_size=1).sync()
    assert backend.sync_upserts == [] and backend.builds == []
    with db.connect(config) as conn:
        assert repository.active_profile_fingerprint(conn) == old.profile.fingerprint
        assert repository.backend_state(conn) == old_state


def test_staging_build_failure_preserves_old_profile_and_backend_state(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    old_backend = TrackingBackend(); old = RecordingProvider(_profile(epoch="old"))
    _service(config, old, old_backend).sync()
    with db.connect(config) as conn:
        old_state = repository.backend_state(conn)
    failing = TrackingBackend(fail_build=True)
    new = RecordingProvider(_profile(epoch="new"))
    with pytest.raises(RuntimeError):
        _service(config, new, failing).sync()
    assert failing.sync_upserts == []
    with db.connect(config) as conn:
        assert repository.active_profile_fingerprint(conn) == old.profile.fingerprint
        assert repository.backend_state(conn) == old_state


def test_same_active_ready_profile_uses_incremental_sync_upsert(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    backend = TrackingBackend(); provider = RecordingProvider(); service = _service(config, provider, backend)
    assert service.sync().active_switched
    backend.sync_upserts.clear(); backend.builds.clear()
    with db.connect(config) as conn:
        _memory(conn, "a", title="changed"); conn.commit()
    result = service.sync()
    assert backend.sync_upserts == [("a", provider.profile.fingerprint, 3)]
    assert backend.builds == []
    assert not result.active_switched


def test_same_profile_backend_not_ready_uses_safe_build_path(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    backend = TrackingBackend(); provider = RecordingProvider(); service = _service(config, provider, backend)
    service.sync(); backend.sync_upserts.clear(); backend.builds.clear()
    with db.connect(config) as conn:
        _memory(conn, "a", content="changed")
        repository.set_backend_state(
            conn, backend=backend.backend_id, schema_version=backend.schema_version,
            profile_fingerprint=provider.profile.fingerprint, build_status="building", built_at=None,
        )
        conn.commit()
    result = service.sync()
    assert backend.sync_upserts == []
    assert backend.builds == [provider.profile.fingerprint]
    assert not result.active_switched


@pytest.mark.parametrize("field", ["title", "content"])
def test_exact_scan_excludes_stale_vector_before_sync(config, field):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); backend = ExactScanBackend(); service = _service(config, provider, backend)
    service.sync()
    with db.connect(config) as conn:
        assert backend.search(conn, provider.profile.fingerprint, [1, 1, 1], limit=5)
        _memory(conn, "a", **{field: "changed"}); conn.commit()
        assert backend.search(conn, provider.profile.fingerprint, [1, 1, 1], limit=5) == []


@pytest.mark.parametrize("change", [
    {"type": "fact"}, {"topics": '["changed"]'}, {"entity": "Entity"},
])
def test_metadata_only_change_remains_exact_searchable(config, change):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    provider = RecordingProvider(); backend = ExactScanBackend(); service = _service(config, provider, backend)
    service.sync()
    with db.connect(config) as conn:
        if "entity" in change:
            entity_id = db.get_or_create_entity(conn, change["entity"])
            conn.execute("INSERT INTO memory_entities(memory_id, entity_id) VALUES ('a', ?)", (entity_id,))
        else:
            _memory(conn, "a", **change)
        conn.commit()
        assert backend.search(conn, provider.profile.fingerprint, [1, 1, 1], limit=5)


def test_failed_stale_reembedding_stays_unsearchable_then_success_restores(config):
    with db.connect(config) as conn:
        _memory(conn, "a"); conn.commit()
    profile = _profile(); backend = ExactScanBackend()
    initial = RecordingProvider(profile); _service(config, initial, backend).sync()
    with db.connect(config) as conn:
        _memory(conn, "a", content="changed"); conn.commit()
    failing = RecordingProvider(profile, fail_calls={1: EmbeddingConfigurationError("offline")})
    with pytest.raises(EmbeddingConfigurationError):
        _service(config, failing, backend).sync()
    with db.connect(config) as conn:
        assert backend.search(conn, profile.fingerprint, [1, 1, 1], limit=5) == []
    assert _service(config, RecordingProvider(profile), backend).sync().embedded == 1
    with db.connect(config) as conn:
        assert backend.search(conn, profile.fingerprint, [1, 1, 1], limit=5)[0].memory_id == "a"
