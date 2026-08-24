from datetime import datetime, timedelta

from brain_twin.linking import MemoryCandidate, from_wikilink, suggest_links, to_wikilink


def _dt(minutes_offset: int = 0) -> datetime:
    return datetime(2026, 8, 24, 12, 0, 0) + timedelta(minutes=minutes_offset)


def test_same_topic_creates_link():
    candidates = [MemoryCandidate(id="mem_a", topics=["work"], entities=[], created_at=_dt(-999))]
    suggestions = suggest_links(["work"], [], _dt(), candidates)
    assert len(suggestions) == 1
    assert suggestions[0].target_memory_id == "mem_a"
    assert suggestions[0].relation_type == "same_topic"
    assert "work" in suggestions[0].reason


def test_same_entity_creates_link_and_outranks_same_topic():
    candidates = [
        MemoryCandidate(id="mem_topic_only", topics=["work"], entities=[], created_at=_dt(-999)),
        MemoryCandidate(id="mem_entity_match", topics=[], entities=["ナイキ"], created_at=_dt(-999)),
    ]
    suggestions = suggest_links(["work"], ["ナイキ"], _dt(), candidates)
    ids_by_rank = [s.target_memory_id for s in suggestions]
    assert ids_by_rank[0] == "mem_entity_match"  # same_entityの方が強いシグナルとして先に来る
    assert "mem_topic_only" in ids_by_rank


def test_temporal_relation_within_window():
    candidates = [MemoryCandidate(id="mem_recent", topics=[], entities=[], created_at=_dt(-10))]
    suggestions = suggest_links([], [], _dt(), candidates)
    assert len(suggestions) == 1
    assert suggestions[0].relation_type == "temporal_relation"


def test_no_link_when_nothing_shared_and_time_far_apart():
    candidates = [MemoryCandidate(id="mem_far", topics=["health"], entities=["ソニー"], created_at=_dt(-999))]
    suggestions = suggest_links(["work"], ["ナイキ"], _dt(), candidates)
    assert suggestions == []


def test_multiple_relation_types_for_same_candidate_are_both_returned():
    candidates = [MemoryCandidate(id="mem_both", topics=["work"], entities=[], created_at=_dt(-5))]
    suggestions = suggest_links(["work"], [], _dt(), candidates)
    relation_types = {s.relation_type for s in suggestions}
    assert relation_types == {"same_topic", "temporal_relation"}


def test_max_links_per_memory_cap():
    candidates = [
        MemoryCandidate(id=f"mem_{i}", topics=["work"], entities=[], created_at=_dt(-999)) for i in range(30)
    ]
    suggestions = suggest_links(["work"], [], _dt(), candidates)
    assert len(suggestions) <= 10


def test_wikilink_roundtrip():
    assert to_wikilink("mem_20260824_001") == "[[mem_20260824_001]]"
    assert from_wikilink("[[mem_20260824_001]]") == "mem_20260824_001"
    assert from_wikilink("not a wikilink") is None
