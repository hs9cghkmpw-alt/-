"""Characterization tests for search.search() (Sprint 4C).

These pin the exact current formula/order/limit/short-query behavior before Hybrid ranking
(hybrid_search.py) reuses the same metadata_multiplier() helper. Any future refactor of
search.py must keep these passing unchanged.
"""
from datetime import datetime, timezone

import pytest

from brain_twin import db, search
from brain_twin.retrieval_weights import metadata_multiplier

FIXED_NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def _memory(conn, memory_id, content, *, importance=3, confidence=1.0, event_date="2026-08-20", title=None):
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at=f"{event_date}T00:00:00+00:00",
        event_date=event_date, importance=importance, confidence=confidence, source="test",
        status="active", title=title or content, content=content, raw_log_id=None,
        file_path=f"{memory_id}.md", topics_json="[]",
    )


def test_search_score_matches_bm25_times_metadata_multiplier_formula(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "unique searchable phrase alpha", importance=4, confidence=0.8, event_date="2026-08-20")
        conn.commit()
        [hit] = db.search(conn, "searchable phrase", limit=5)
        results = search.search(conn, "searchable phrase", now=FIXED_NOW)

    assert len(results) == 1
    expected_weight = metadata_multiplier(importance=4, confidence=0.8, event_date="2026-08-20", now=FIXED_NOW)
    expected_score = -hit.rank * expected_weight
    assert results[0].score == pytest.approx(expected_score)
    assert results[0].memory_id == "a"


def test_search_order_is_by_descending_score(config):
    with db.connect(config) as conn:
        _memory(conn, "low", "shared searchable phrase low", importance=1, event_date="2000-01-01")
        _memory(conn, "high", "shared searchable phrase high", importance=5, event_date="2026-08-24")
        conn.commit()
        results = search.search(conn, "shared searchable phrase", now=FIXED_NOW)

    assert [r.memory_id for r in results] == ["high", "low"]
    assert results[0].score > results[1].score


def test_search_respects_limit(config):
    with db.connect(config) as conn:
        for i in range(5):
            _memory(conn, f"m{i}", f"limit test phrase number {i}")
        conn.commit()
        results = search.search(conn, "limit test phrase", limit=2, now=FIXED_NOW)

    assert len(results) == 2


def test_search_short_query_returns_empty(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "unique searchable phrase")
        conn.commit()
        assert search.search(conn, "ab", now=FIXED_NOW) == []


def test_plain_search_works_without_any_embedding_configuration(config, monkeypatch):
    monkeypatch.delenv("BRAIN_TWIN_CONFIG", raising=False)
    with db.connect(config) as conn:
        _memory(conn, "a", "unique searchable phrase")
        conn.commit()
        assert search.search(conn, "searchable phrase", now=FIXED_NOW) != []


def test_search_module_does_not_reference_embedding_provider_machinery():
    import brain_twin.search as search_module

    names = set(dir(search_module))
    assert "embedding_runtime" not in names
    assert "embedding_provider" not in names
    assert "embedding_service" not in names


# ---- Sprint 4C: pure lexical candidate API used by Hybrid ranking ----


def test_search_lexical_candidates_returns_pure_relevance_no_metadata(config):
    with db.connect(config) as conn:
        _memory(conn, "low_importance", "lexical candidate phrase alpha", importance=1)
        _memory(conn, "high_importance", "lexical candidate phrase beta", importance=5)
        conn.commit()
        candidates = db.search_lexical_candidates(conn, "lexical candidate phrase", limit=10)

    assert {c.memory_id for c in candidates} == {"low_importance", "high_importance"}
    assert [c.lexical_rank for c in candidates] == [1, 2]
    # Rank must follow ascending bm25_score (smaller/more negative = better) with no
    # importance/confidence/recency weighting applied anywhere in this API.
    assert [c.bm25_score for c in candidates] == sorted(c.bm25_score for c in candidates)


def test_search_lexical_candidates_excludes_inactive(config):
    with db.connect(config) as conn:
        _memory(conn, "active", "candidate exclusion phrase")
        db.upsert_memory(
            conn, id="archived", type="thought", created_at="2026-08-20T00:00:00+00:00",
            event_date="2026-08-20", importance=3, confidence=1.0, source="test",
            status="archived", title="candidate exclusion phrase", content="candidate exclusion phrase",
            raw_log_id=None, file_path="archived.md", topics_json="[]",
        )
        conn.commit()
        candidates = db.search_lexical_candidates(conn, "candidate exclusion phrase", limit=10)

    assert [c.memory_id for c in candidates] == ["active"]


def test_search_lexical_candidates_respects_limit(config):
    with db.connect(config) as conn:
        for i in range(5):
            _memory(conn, f"m{i}", f"lexical limit phrase number {i}")
        conn.commit()
        candidates = db.search_lexical_candidates(conn, "lexical limit phrase", limit=2)

    assert len(candidates) == 2
    assert [c.lexical_rank for c in candidates] == [1, 2]


def test_search_lexical_candidates_no_match_returns_empty(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "totally unrelated content")
        conn.commit()
        assert db.search_lexical_candidates(conn, "nonexistent query text", limit=10) == []


# ---- Sprint 4C: lightweight ranking signal vs. full result detail ----


def test_memory_ranking_signals_excludes_body_and_inactive(config):
    with db.connect(config) as conn:
        _memory(conn, "active", "ranking signal body", importance=4, confidence=0.9, event_date="2026-08-01")
        db.upsert_memory(
            conn, id="archived", type="thought", created_at="2026-08-01T00:00:00+00:00",
            event_date="2026-08-01", importance=5, confidence=1.0, source="test",
            status="archived", title="x", content="x", raw_log_id=None,
            file_path="archived.md", topics_json="[]",
        )
        conn.commit()
        signals = db.memory_ranking_signals_by_ids(conn, ["active", "archived", "missing"])

    assert set(signals) == {"active"}
    assert signals["active"].importance == 4
    assert signals["active"].confidence == 0.9
    assert signals["active"].event_date == "2026-08-01"


def test_memory_result_details_includes_topics_and_entities(config):
    with db.connect(config) as conn:
        _memory(conn, "a", "detail body")
        db.upsert_memory(
            conn, id="a", type="thought", created_at="2026-08-01T00:00:00+00:00",
            event_date="2026-08-01", importance=3, confidence=1.0, source="test",
            status="active", title="detail body", content="detail body", raw_log_id=None,
            file_path="a.md", topics_json='["work"]',
        )
        entity_id = db.get_or_create_entity(conn, "テスト")
        conn.execute(
            "INSERT INTO memory_entities(memory_id, entity_id, confidence, method) VALUES ('a', ?, 1.0, 'test')",
            (entity_id,),
        )
        conn.commit()
        details = db.memory_result_details_by_ids(conn, ["a"])

    assert details["a"].topics == ["work"]
    assert details["a"].entities == ["テスト"]
    assert details["a"].content == "detail body"


def test_memory_result_details_empty_input_returns_empty(config):
    with db.connect(config) as conn:
        assert db.memory_result_details_by_ids(conn, []) == {}
