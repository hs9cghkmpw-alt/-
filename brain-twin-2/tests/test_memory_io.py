import pytest

from brain_twin import memory_io
from brain_twin.models import Memory, MemoryStatus, MemoryType


def _memory(memory_id: str, mem_type: MemoryType) -> Memory:
    return Memory(
        id=memory_id, type=mem_type, created_at="2026-08-24T00:00:00+00:00",
        event_date="2026-08-24", importance=2, confidence=0.5, source="cli",
        status=MemoryStatus.ACTIVE, title="t", content="c", raw_log_id=None,
    )


def test_find_existing_returns_none_when_not_written(config):
    assert memory_io.find_existing(config, "mem_20260824_001") is None


# ---- レビュー対応(2回目): find_existingはVault全体からIDを探す ----


def test_find_existing_finds_memory_regardless_of_type_hint(config):
    """typeが変わっても(前回はTHOUGHT、今回はDECISION等)、既に書き込み済みの
    Memoryを別のtypeフォルダに探しに行かず正しく見つけられること。"""
    written = memory_io.write_memory(config, _memory("mem_20260824_001", MemoryType.THOUGHT))

    found = memory_io.find_existing(config, "mem_20260824_001")
    assert found is not None
    assert found.id == written.id
    assert found.type == MemoryType.THOUGHT


def test_find_existing_raises_on_duplicate_id_in_multiple_folders(config):
    """同じIDのファイルが複数のtypeフォルダに存在する(本来あり得ない)異常な状態を
    検出したら、片方を黙って選ばずに例外を送出すること。"""
    memory_io.write_memory(config, _memory("mem_20260824_001", MemoryType.THOUGHT))
    memory_io.write_memory(config, _memory("mem_20260824_001", MemoryType.DECISION))

    with pytest.raises(memory_io.DuplicateMemoryError):
        memory_io.find_existing(config, "mem_20260824_001")


# ---- レビュー対応(2回目): legacy Entityのconfidenceは1.0ではなく保守的な値にする ----


def test_entity_objects_legacy_fallback_uses_conservative_confidence():
    memory = _memory("mem_1", MemoryType.THOUGHT)
    memory.entities = ["カバン"]
    memory.entity_details = []  # 旧形式(entity_detailsが存在しない)を再現

    objects = memory_io.entity_objects(memory)

    assert len(objects) == 1
    assert objects[0].name == "カバン"
    assert objects[0].method == "legacy"
    assert objects[0].confidence != 1.0
    assert 0.0 < objects[0].confidence < 1.0


def test_entity_objects_prefers_entity_details_when_present():
    memory = _memory("mem_1", MemoryType.THOUGHT)
    memory.entities = ["ナイキ"]
    memory.entity_details = [{"name": "ナイキ", "confidence": 0.8, "method": "katakana_heuristic_v1"}]

    objects = memory_io.entity_objects(memory)

    assert len(objects) == 1
    assert objects[0].confidence == 0.8
    assert objects[0].method == "katakana_heuristic_v1"


def test_legacy_generic_word_match_alone_does_not_produce_strong_link():
    """legacy由来の一般語1件の一致だけでは、strongなsame_entityリンクの根拠に
    ならないこと(confidenceの低さがlinking.py側の判定にちゃんと伝播することの確認)。
    「近い時刻」のtemporal_relationも発生しないよう候補の時刻を大きく離しておき、
    same_entity単独のstrengthだけを見る。"""
    from datetime import datetime, timedelta

    from brain_twin import linking

    legacy_memory = Memory(
        id="mem_new", type=MemoryType.THOUGHT, created_at="2026-08-24T00:00:00+00:00",
        event_date="2026-08-24", importance=2, confidence=0.5, source="cli",
        status=MemoryStatus.ACTIVE, title="t", content="c", raw_log_id=None,
        entities=["カバン"], entity_details=[],
    )
    target_entities = memory_io.entity_objects(legacy_memory)
    assert target_entities[0].confidence == memory_io._LEGACY_ENTITY_CONFIDENCE

    candidate = linking.MemoryCandidate(
        id="mem_old", topics=[], entities=target_entities,
        created_at=datetime.fromisoformat("2026-08-24T00:00:00+00:00") - timedelta(days=365),
    )

    suggestions = linking.suggest_links(
        target_topics=[], target_entities=target_entities,
        target_created_at=datetime.fromisoformat("2026-08-24T00:00:00+00:00"),
        candidates=[candidate],
    )

    same_entity = [s for s in suggestions if s.relation_type == "same_entity"]
    assert len(same_entity) == 1
    # 高confidence同士(1.0)の一致ならsame_topicと同等以上のstrengthになりうるが、
    # legacyの低confidence(0.3)同士の一致では明確に弱いままであること。
    assert same_entity[0].strength < linking._SAME_TOPIC_STRENGTH
