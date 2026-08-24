from datetime import datetime, timedelta

from brain_twin.linking import MemoryCandidate, from_wikilink, suggest_links, to_wikilink
from brain_twin.models import ExtractedEntity


def _dt(minutes_offset: int = 0) -> datetime:
    return datetime(2026, 8, 24, 12, 0, 0) + timedelta(minutes=minutes_offset)


def _entity(name: str, confidence: float = 1.0) -> ExtractedEntity:
    return ExtractedEntity(name=name, confidence=confidence, method="test")


def test_same_topic_creates_link():
    candidates = [MemoryCandidate(id="mem_a", topics=["work"], entities=[], created_at=_dt(-999))]
    suggestions = suggest_links(["work"], [], _dt(), candidates)
    assert len(suggestions) == 1
    assert suggestions[0].target_memory_id == "mem_a"
    assert suggestions[0].relation_type == "same_topic"
    assert "work" in suggestions[0].reason


def test_temporal_relation_within_window():
    candidates = [MemoryCandidate(id="mem_recent", topics=[], entities=[], created_at=_dt(-10))]
    suggestions = suggest_links([], [], _dt(), candidates)
    assert len(suggestions) == 1
    assert suggestions[0].relation_type == "temporal_relation"


def test_no_link_when_nothing_shared_and_time_far_apart():
    candidates = [MemoryCandidate(id="mem_far", topics=["health"], entities=[_entity("ソニー")], created_at=_dt(-999))]
    suggestions = suggest_links(["work"], [_entity("ナイキ")], _dt(), candidates)
    assert suggestions == []


def test_multiple_relation_types_for_same_candidate_are_both_returned():
    candidates = [MemoryCandidate(id="mem_both", topics=["work"], entities=[], created_at=_dt(-5))]
    suggestions = suggest_links(["work"], [], _dt(), candidates)
    relation_types = {s.relation_type for s in suggestions}
    assert relation_types == {"same_topic", "temporal_relation"}


def test_wikilink_roundtrip():
    assert to_wikilink("mem_20260824_001") == "[[mem_20260824_001]]"
    assert from_wikilink("[[mem_20260824_001]]") == "mem_20260824_001"
    assert from_wikilink("not a wikilink") is None


# ---- レビュー対応1: Entity一致の信頼度をリンクの強さに反映する ----


def test_low_confidence_single_entity_match_does_not_outrank_topic_match():
    """精度の低い(=confidenceが低い)Entity一致1件だけでは、topic一致より
    弱いリンクとして扱われるべき(過去のレビュー指摘: 以前はsame_entityが
    常にsame_topicより強いstrengthを持っていた)。"""
    candidates = [
        MemoryCandidate(id="mem_topic_only", topics=["work"], entities=[], created_at=_dt(-999)),
        MemoryCandidate(id="mem_weak_entity", topics=[], entities=[_entity("ナイキ", confidence=0.3)], created_at=_dt(-999)),
    ]
    suggestions = suggest_links(["work"], [_entity("ナイキ", confidence=0.3)], _dt(), candidates)
    ranked_ids = [s.target_memory_id for s in suggestions]
    assert ranked_ids[0] == "mem_topic_only"


def test_multiple_high_confidence_entity_matches_can_outrank_a_single_topic_match():
    """一方で、信頼度の高いEntity一致が複数重なれば、単独のtopic一致より
    強いリンクになってよい(confidenceを考慮しつつも、Entity一致の価値自体は
    否定しない、という設計の確認)。"""
    shared = [_entity("ブレインツイン", confidence=0.9), _entity("クラルティ", confidence=0.9)]
    candidates = [
        MemoryCandidate(id="mem_topic_only", topics=["work"], entities=[], created_at=_dt(-999)),
        MemoryCandidate(id="mem_strong_entities", topics=[], entities=shared, created_at=_dt(-999)),
    ]
    suggestions = suggest_links(["work"], shared, _dt(), candidates)
    ranked_ids = [s.target_memory_id for s in suggestions]
    assert ranked_ids[0] == "mem_strong_entities"


def test_entity_match_strength_uses_min_of_both_sides_confidence():
    """片側だけ高confidenceでも、もう片側が低ければ全体としては弱い一致として
    扱われる(保守的な扱い)。"""
    candidates = [
        MemoryCandidate(id="mem_a", topics=[], entities=[_entity("ナイキ", confidence=0.9)], created_at=_dt(-999)),
    ]
    suggestions = suggest_links(["nonexistent_topic"], [_entity("ナイキ", confidence=0.2)], _dt(), candidates)
    assert len(suggestions) == 1
    # strength = base(1.0) * count(1) * min(0.9, 0.2) = 0.2
    assert suggestions[0].strength < 0.25


# ---- レビュー対応2: 上限は relation数ではなく target Memory数に対して適用する ----


def test_cap_is_applied_per_memory_not_per_relation():
    """1つのMemoryペアでsame_topic/same_entity/temporal_relationが同時に
    成立しても、それは1件の"関連Memory"として数え、3件消費しない。
    30件の候補それぞれがtopicとtemporal両方で一致する状況でも、
    上位10"Memory"ぶんのrelationがすべて返るはず(10 relationではなく)。"""
    candidates = [
        MemoryCandidate(id=f"mem_{i}", topics=["work"], entities=[], created_at=_dt(-1)) for i in range(30)
    ]
    suggestions = suggest_links(["work"], [], _dt(), candidates)

    target_ids = {s.target_memory_id for s in suggestions}
    assert len(target_ids) == 10  # 関連Memoryとしては10件に制限される
    # ただし各Memoryにつきsame_topicとtemporal_relationの2種類が成立しているため、
    # relation行数としては10件を超えてよい。
    assert len(suggestions) == 20


def test_max_links_per_memory_cap_single_relation_type():
    # 単一種類の関連しか発生しない場合は、以前と同じ「上位10件」の挙動になる。
    candidates = [
        MemoryCandidate(id=f"mem_{i}", topics=["work"], entities=[], created_at=_dt(-999)) for i in range(30)
    ]
    suggestions = suggest_links(["work"], [], _dt(), candidates)
    assert len(suggestions) == 10
