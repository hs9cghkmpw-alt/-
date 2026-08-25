import sqlite3

import pytest

from brain_twin import db
from brain_twin.models import ExtractedEntity


def _entity(name: str, confidence: float = 0.7, method: str = "test") -> ExtractedEntity:
    return ExtractedEntity(name=name, confidence=confidence, method=method)


def test_get_or_create_entity_is_idempotent(config):
    with db.connect(config) as conn:
        id1 = db.get_or_create_entity(conn, "ナイキ")
        id2 = db.get_or_create_entity(conn, "ナイキ")
        assert id1 == id2
        count = conn.execute("SELECT COUNT(*) FROM entities WHERE name = ?", ("ナイキ",)).fetchone()[0]
        assert count == 1


def _insert_bare_memory(conn, memory_id: str, created_at: str = "2026-08-24T00:00:00+00:00", topics_json: str = "[]") -> None:
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at=created_at, event_date=created_at[:10],
        importance=2, confidence=1.0, source="cli", status="active", title="t", content="c",
        raw_log_id=None, file_path="x.md", topics_json=topics_json,
    )


def test_set_memory_entities_replaces_previous_set(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        db.set_memory_entities(conn, "mem_1", [_entity("ナイキ"), _entity("アディダス")])
        names = {e.name for e in db.entities_for_memories(conn, ["mem_1"])["mem_1"]}
        assert names == {"ナイキ", "アディダス"}

        db.set_memory_entities(conn, "mem_1", [_entity("ナイキ")])
        result = db.entities_for_memories(conn, ["mem_1"])["mem_1"]
        assert [e.name for e in result] == ["ナイキ"]


def test_set_memory_entities_persists_confidence_and_method(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        db.set_memory_entities(conn, "mem_1", [_entity("ナイキ", confidence=0.42, method="katakana_heuristic_v1")])

        result = db.entities_for_memories(conn, ["mem_1"])["mem_1"]
        assert len(result) == 1
        assert result[0].confidence == 0.42
        assert result[0].method == "katakana_heuristic_v1"


def test_entities_for_memories_batches_multiple_ids(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        _insert_bare_memory(conn, "mem_2")
        db.set_memory_entities(conn, "mem_1", [_entity("ナイキ")])
        db.set_memory_entities(conn, "mem_2", [_entity("クラルティ")])

        result = db.entities_for_memories(conn, ["mem_1", "mem_2", "mem_missing"])
        assert [e.name for e in result["mem_1"]] == ["ナイキ"]
        assert [e.name for e in result["mem_2"]] == ["クラルティ"]
        assert result["mem_missing"] == []


def test_upsert_link_is_idempotent_on_same_triple(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        _insert_bare_memory(conn, "mem_2")

        db.upsert_link(conn, source_memory_id="mem_1", target_memory_id="mem_2", relation_type="same_topic", reason="work", created_at="2026-08-24T00:00:00+00:00")
        db.upsert_link(conn, source_memory_id="mem_1", target_memory_id="mem_2", relation_type="same_topic", reason="work", created_at="2026-08-24T00:00:00+00:00")

        links = db.links_for_memory(conn, "mem_1")
        assert len(links) == 1
        assert links[0].target_memory_id == "mem_2"
        assert links[0].reason == "work"


def test_connect_self_heals_pre_phase2_links_table_missing_reason_column(config):
    """Phase 1時点で作られたlinksテーブル(reason列が無い)を持つ環境でも、
    次回のdb.connect()で自動的に列が追加され、以降のupsert_linkが失敗しないこと。"""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.db_path))
    conn.executescript(
        """
        CREATE TABLE links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_memory_id TEXT NOT NULL,
            target_memory_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (source_memory_id, target_memory_id, relation_type)
        );
        """
    )
    conn.commit()
    conn.close()

    with db.connect(config) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(links)").fetchall()}
        assert "reason" in columns

        _insert_bare_memory(conn, "mem_1")
        _insert_bare_memory(conn, "mem_2")
        db.upsert_link(conn, source_memory_id="mem_1", target_memory_id="mem_2", relation_type="same_topic", reason="ok", created_at="2026-08-24T00:00:00+00:00")
        conn.commit()


def test_connect_self_heals_pre_review_memory_entities_missing_confidence_columns(config):
    """このレビュー修正より前に作られたmemory_entitiesテーブル(confidence/method列が
    無い)を持つ環境でも、次回のdb.connect()で自動的に列が追加されること。"""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.db_path))
    conn.executescript(
        """
        CREATE TABLE entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE memory_entities (
            memory_id TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            PRIMARY KEY (memory_id, entity_id)
        );
        """
    )
    conn.commit()
    conn.close()

    with db.connect(config) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_entities)").fetchall()}
        assert {"confidence", "method"} <= columns

        _insert_bare_memory(conn, "mem_1")
        db.set_memory_entities(conn, "mem_1", [_entity("ナイキ")])
        conn.commit()


def test_connect_self_heals_links_table_missing_strength_column(config):
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.db_path))
    conn.executescript(
        """
        CREATE TABLE links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_memory_id TEXT NOT NULL,
            target_memory_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE (source_memory_id, target_memory_id, relation_type)
        );
        """
    )
    conn.commit()
    conn.close()

    with db.connect(config) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(links)").fetchall()}
        assert "strength" in columns
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name='links'").fetchone()


def test_links_table_rejects_dangling_reference(config):
    """外部キー制約により、存在しないmemoryを指すlinkは拒否される(reindexの2周目分割が
    必要な理由そのものを保証するテスト)。"""
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        with pytest.raises(sqlite3.IntegrityError):
            db.upsert_link(conn, source_memory_id="mem_1", target_memory_id="mem_does_not_exist", relation_type="same_topic", reason="x", created_at="2026-08-24T00:00:00+00:00")
            conn.commit()


# ---- レビュー対応3: 候補探索はDB側で絞り込む(件数ベースの打ち切りをしない) ----


def test_find_candidates_by_topics_finds_arbitrarily_old_memory(config):
    """"直近500件"のような打ち切りを撤廃したことの確認: 非常に古いMemoryでも、
    topicが一致すれば候補として見つかる。"""
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_old", created_at="2000-01-01T00:00:00+00:00", topics_json='["work"]')
        _insert_bare_memory(conn, "mem_unrelated", created_at="2026-08-24T00:00:00+00:00", topics_json='["health"]')

        found = db.find_candidates_by_topics(conn, ["work"])
        assert found == {"mem_old"}


def test_find_candidates_by_entities_finds_arbitrarily_old_memory(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_old", created_at="2000-01-01T00:00:00+00:00")
        db.set_memory_entities(conn, "mem_old", [_entity("ナイキ")])
        _insert_bare_memory(conn, "mem_unrelated", created_at="2026-08-24T00:00:00+00:00")
        db.set_memory_entities(conn, "mem_unrelated", [_entity("アディダス")])

        found = db.find_candidates_by_entities(conn, ["ナイキ"])
        assert found == {"mem_old"}


def test_find_candidates_by_topics_excludes_given_id(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1", topics_json='["work"]')
        _insert_bare_memory(conn, "mem_2", topics_json='["work"]')

        found = db.find_candidates_by_topics(conn, ["work"], exclude_id="mem_1")
        assert found == {"mem_2"}


def test_find_candidates_by_time_range_respects_bounds(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_inside", created_at="2026-08-24T12:00:00+00:00")
        _insert_bare_memory(conn, "mem_outside", created_at="2000-01-01T00:00:00+00:00")

        found = db.find_candidates_by_time_range(conn, "2026-08-24T00:00:00+00:00", "2026-08-25T00:00:00+00:00")
        assert found == {"mem_inside"}


def test_list_memory_signals_by_ids_returns_topics_and_entities(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1", topics_json='["work"]')
        db.set_memory_entities(conn, "mem_1", [_entity("ナイキ")])

        signals = db.list_memory_signals_by_ids(conn, ["mem_1"])
        assert len(signals) == 1
        assert signals[0].topics == ["work"]
        assert [e.name for e in signals[0].entities] == ["ナイキ"]


def test_list_memory_signals_by_ids_empty_input_returns_empty(config):
    with db.connect(config) as conn:
        assert db.list_memory_signals_by_ids(conn, []) == []


# ---- レビュー対応(2回目): 「直近500件」の名残だった暗黙の200件上限を撤廃 ----
#
# 「古いMemoryが1件だけ」という設定では、そのMemoryが偶然200件のウィンドウ内に
# 収まってしまい上限撤廃の効果を検証できない。一致する行を201件以上作った上で、
# 最も古い1件(=打ち切りがあれば真っ先に落ちる行)がなお候補に含まれることを見る。


def _old_created_at(i: int) -> str:
    return f"2001-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+00:00"


def test_find_candidates_by_topics_finds_oldest_among_201_matches(config):
    with db.connect(config) as conn:
        for i in range(201):
            _insert_bare_memory(conn, f"mem_{i:03d}", created_at=_old_created_at(i), topics_json='["work"]')

        found = db.find_candidates_by_topics(conn, ["work"])
        assert len(found) == 201
        assert "mem_000" in found  # 最も古い行(created_atが最小)


def test_find_candidates_by_entities_finds_oldest_among_201_matches(config):
    with db.connect(config) as conn:
        for i in range(201):
            memory_id = f"mem_{i:03d}"
            _insert_bare_memory(conn, memory_id, created_at=_old_created_at(i))
            db.set_memory_entities(conn, memory_id, [_entity("ナイキ")])

        found = db.find_candidates_by_entities(conn, ["ナイキ"])
        assert len(found) == 201
        assert "mem_000" in found  # 最も古い行
