from brain_twin import db, pipeline, retrieval


def _memory(conn, memory_id, content, *, status="active", importance=3, date="2026-08-10"):
    db.upsert_memory(
        conn,
        id=memory_id,
        type="thought",
        created_at=f"{date}T00:00:00+00:00",
        event_date=date,
        importance=importance,
        confidence=1.0,
        source="test",
        status=status,
        title=content,
        content=content,
        raw_log_id=None,
        file_path=f"20_Memory/Thoughts/{memory_id}.md",
        topics_json="[]",
    )


def _link(conn, source, target, relation="same_topic", reason="shared topic"):
    db.upsert_link(
        conn,
        source_memory_id=source,
        target_memory_id=target,
        relation_type=relation,
        reason=reason,
        created_at="2026-08-10T00:00:00+00:00",
    )


def test_associative_retrieval_follows_outgoing_link(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        _memory(conn, "related", "other memory")
        _link(conn, "primary", "related")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert result.related[0].memory_id == "related"
    assert result.related[0].relations[0].direction == "outgoing"


def test_associative_retrieval_follows_incoming_link(config):
    with db.connect(config) as conn:
        _memory(conn, "older", "other memory")
        _memory(conn, "primary", "unique searchable phrase")
        _link(conn, "older", "primary")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert result.related[0].memory_id == "older"
    assert result.related[0].relations[0].direction == "incoming"


def test_primary_is_never_in_related_even_when_primaries_are_linked(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "common searchable phrase alpha")
        _memory(conn, "b", "common searchable phrase beta")
        _link(conn, "a", "b")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert {item.memory_id for item in result.primary} == {"a", "b"}
    assert result.related == []


def test_memory_already_in_primary_is_excluded_from_another_primarys_related(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "common searchable phrase alpha")
        _memory(conn, "b", "common searchable phrase beta")
        _memory(conn, "c", "unmatched destination")
        _link(conn, "a", "b")
        _link(conn, "a", "c")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert [item.memory_id for item in result.related] == ["c"]


def test_related_is_deduplicated_across_multiple_primaries(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "common searchable phrase alpha")
        _memory(conn, "b", "common searchable phrase beta")
        _memory(conn, "c", "unmatched destination")
        _link(conn, "a", "c")
        _link(conn, "b", "c", "same_entity", "shared entity")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert [item.memory_id for item in result.related] == ["c"]
    assert {r.primary_memory_id for r in result.related[0].relations} == {"a", "b"}


def test_multiple_relation_types_and_reasons_are_preserved(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        _memory(conn, "related", "other memory")
        _link(conn, "primary", "related", "same_topic", "topic reason")
        _link(conn, "primary", "related", "same_entity", "entity reason")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert {(r.relation_type, r.reason) for r in result.related[0].relations} == {
        ("same_topic", "topic reason"),
        ("same_entity", "entity reason"),
    }


def test_inactive_related_memory_is_excluded(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        _memory(conn, "related", "other memory", status="archived")
        _link(conn, "primary", "related")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert result.related == []


def test_related_limit_is_applied_after_deduplication(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        for index in range(4):
            memory_id = f"related-{index}"
            _memory(conn, memory_id, f"other memory {index}")
            _link(conn, "primary", memory_id)
        result = retrieval.retrieve(conn, "searchable phrase", related_limit=2)
    assert len(result.related) == 2


def test_associative_retrieval_is_one_hop_only(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        _memory(conn, "one-hop", "first related")
        _memory(conn, "two-hop", "second related")
        _link(conn, "primary", "one-hop")
        _link(conn, "one-hop", "two-hop")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert [item.memory_id for item in result.related] == ["one-hop"]


def test_no_links_keeps_normal_search_results(config):
    with db.connect(config) as conn:
        _memory(conn, "primary", "unique searchable phrase")
        result = retrieval.retrieve(conn, "searchable phrase")
    assert [item.memory_id for item in result.primary] == ["primary"]
    assert result.related == []


def test_associative_retrieval_survives_reindex(config):
    pipeline.add_capture(config, "ナイキの特別なランニングシューズを買って走るのが楽しみ")
    pipeline.process_all(config)
    pipeline.add_capture(config, "ナイキ本社について詳しく調べて考えたことを記録する")
    pipeline.process_all(config)
    before = retrieval.retrieve_with_config(config, "ランニングシューズ")
    assert before.related
    pipeline.reindex(config)
    after = retrieval.retrieve_with_config(config, "ランニングシューズ")
    assert after == before
