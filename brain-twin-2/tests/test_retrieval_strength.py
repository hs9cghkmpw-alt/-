from brain_twin import db, memory_io, pipeline, retrieval
from brain_twin.memory_persistence import LEGACY_LINK_STRENGTH

from test_retrieval import _link, _memory


def test_low_confidence_entity_does_not_outrank_stronger_topic(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        _memory(conn, "entity", "weak entity")
        _memory(conn, "topic", "strong topic")
        _link(conn, "primary", "entity", "same_entity", strength=0.2)
        _link(conn, "primary", "topic", "same_topic", strength=1.0)
        result = retrieval.retrieve(conn, "searchable phrase")
    assert [item.memory_id for item in result.related] == ["topic", "entity"]


def test_high_confidence_and_multiple_entity_strengths_rank_by_actual_value(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        _memory(conn, "topic", "topic")
        _memory(conn, "entity", "entity")
        _memory(conn, "multi", "multi")
        _link(conn, "primary", "topic", "same_topic", strength=1.0)
        _link(conn, "primary", "entity", "same_entity", strength=1.2)
        _link(conn, "primary", "multi", "same_entity", strength=0.8)
        _link(conn, "primary", "multi", "same_topic", strength=0.7)
        result = retrieval.retrieve(conn, "searchable phrase")
    assert [item.memory_id for item in result.related] == ["multi", "entity", "topic"]


def test_legacy_link_details_without_strength_reindex_with_conservative_fallback(config):
    pipeline.add_capture(config, "ナイキの特別なランニングシューズを買って詳しく考えた")
    pipeline.process_all(config)
    pipeline.add_capture(config, "今日はナイキ本社について詳しく調べて記録することにした")
    pipeline.process_all(config)
    linked = next(memory for memory in memory_io.list_all_memories(config) if memory.link_details)
    for detail in linked.link_details:
        detail.pop("strength", None)
    memory_io.write_memory(config, linked)

    pipeline.reindex(config)
    with db.connect(config) as conn:
        strengths = conn.execute(
            "SELECT strength FROM links WHERE source_memory_id = ?", (linked.id,)
        ).fetchall()
    assert strengths
    assert {row[0] for row in strengths} == {LEGACY_LINK_STRENGTH}


def test_reconcile_restores_strength_from_markdown(config):
    pipeline.add_capture(config, "ナイキの特別なランニングシューズを買って詳しく考えた")
    pipeline.process_all(config)
    pipeline.add_capture(config, "今日はナイキ本社について詳しく調べて記録することにした")
    pipeline.process_all(config)
    linked = next(memory for memory in memory_io.list_all_memories(config) if memory.link_details)
    expected = sorted(detail["strength"] for detail in linked.link_details)

    with db.connect(config) as conn:
        conn.execute("DELETE FROM links WHERE source_memory_id = ?", (linked.id,))
        conn.execute(
            "UPDATE raw_logs SET processed_at = NULL WHERE id = ?", (linked.raw_log_id,)
        )
        conn.commit()

    summary = pipeline.process_all(config)
    assert linked.raw_log_id in summary.reconciled_raw_log_ids
    with db.connect(config) as conn:
        restored = sorted(row[0] for row in conn.execute(
            "SELECT strength FROM links WHERE source_memory_id = ?", (linked.id,)
        ).fetchall())
    assert restored == expected


def test_large_incoming_set_fetches_details_only_for_related_limit(config, monkeypatch):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        for index in range(250):
            memory_id = f"incoming-{index:03d}"
            _memory(conn, memory_id, "x" * 1000, importance=index % 5 + 1)
            _link(conn, memory_id, "primary", strength=index / 1000)

        candidates = db.related_link_candidates_for_memories(conn, ["primary"])
        assert len(candidates) == 250
        assert all(not hasattr(candidate, "content") for candidate in candidates)

        fetched_ids = []
        original = db.memory_details_by_ids

        def recording_details(connection, memory_ids):
            fetched_ids.extend(memory_ids)
            return original(connection, memory_ids)

        monkeypatch.setattr(db, "memory_details_by_ids", recording_details)
        result = retrieval.retrieve(conn, "searchable phrase", related_limit=7)

    assert len(result.related) == 7
    assert len(fetched_ids) == 7
    assert [item.memory_id for item in result.related] == [
        f"incoming-{index:03d}" for index in range(249, 242, -1)
    ]
