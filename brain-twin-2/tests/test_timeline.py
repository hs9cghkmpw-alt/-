import pytest

from brain_twin import db, pipeline, search


def _memory(conn, memory_id, content, *, status="active", date="2026-08-10"):
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at=f"{date}T00:00:00+00:00",
        event_date=date, importance=3, confidence=1.0, source="test", status=status,
        title=content, content=content, raw_log_id=None,
        file_path=f"20_Memory/Thoughts/{memory_id}.md", topics_json="[]",
    )


def test_timeline_filters_inside_inclusive_range_and_excludes_outside(config):
    with db.connect(config) as conn:
        _memory(conn, "before", "before", date="2026-07-31")
        _memory(conn, "start", "start", date="2026-08-01")
        _memory(conn, "middle", "middle", date="2026-08-15")
        _memory(conn, "end", "end", date="2026-08-31")
        _memory(conn, "after", "after", date="2026-09-01")
        results = search.timeline(conn, from_date="2026-08-01", to_date="2026-08-31")
    assert [item.memory_id for item in results] == ["start", "middle", "end"]


def test_timeline_only_returns_active_memories(config):
    with db.connect(config) as conn:
        _memory(conn, "active", "active")
        _memory(conn, "archived", "archived", status="archived")
        results = search.timeline(conn)
    assert [item.memory_id for item in results] == ["active"]


def test_timeline_has_deterministic_ascending_order(config):
    with db.connect(config) as conn:
        _memory(conn, "later", "later", date="2026-08-20")
        _memory(conn, "earlier-b", "earlier b", date="2026-08-10")
        _memory(conn, "earlier-a", "earlier a", date="2026-08-10")
        results = search.timeline(conn)
    assert [item.memory_id for item in results] == ["earlier-a", "earlier-b", "later"]


def test_timeline_empty_result(config):
    with db.connect(config) as conn:
        _memory(conn, "memory", "memory", date="2026-08-10")
        assert search.timeline(conn, from_date="2027-01-01") == []


@pytest.mark.parametrize("value", ["2026-02-30", "2026/08/01", "2026-8-1", "not-a-date"])
def test_timeline_rejects_invalid_dates(config, value):
    with db.connect(config) as conn:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            search.timeline(conn, from_date=value)


def test_timeline_rejects_reversed_range(config):
    with db.connect(config) as conn:
        with pytest.raises(ValueError, match="on or before"):
            search.timeline(conn, from_date="2026-08-31", to_date="2026-08-01")


def test_timeline_supports_from_only(config):
    with db.connect(config) as conn:
        _memory(conn, "before", "before", date="2026-08-09")
        _memory(conn, "start", "start", date="2026-08-10")
        assert [r.memory_id for r in search.timeline(conn, from_date="2026-08-10")] == ["start"]


def test_timeline_supports_to_only(config):
    with db.connect(config) as conn:
        _memory(conn, "end", "end", date="2026-08-10")
        _memory(conn, "after", "after", date="2026-08-11")
        assert [r.memory_id for r in search.timeline(conn, to_date="2026-08-10")] == ["end"]


def test_timeline_survives_reindex(config):
    pipeline.add_capture(config, "今日はタイムライン再構築テストについて十分詳しく考えた")
    pipeline.process_all(config)
    before = search.timeline_with_config(config)
    assert before
    pipeline.reindex(config)
    assert search.timeline_with_config(config) == before
