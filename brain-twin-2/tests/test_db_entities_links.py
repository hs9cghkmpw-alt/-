from brain_twin import db


def test_get_or_create_entity_is_idempotent(config):
    with db.connect(config) as conn:
        id1 = db.get_or_create_entity(conn, "ナイキ")
        id2 = db.get_or_create_entity(conn, "ナイキ")
        assert id1 == id2
        count = conn.execute("SELECT COUNT(*) FROM entities WHERE name = ?", ("ナイキ",)).fetchone()[0]
        assert count == 1


def _insert_bare_memory(conn, memory_id: str, created_at: str = "2026-08-24T00:00:00+00:00") -> None:
    db.upsert_memory(
        conn, id=memory_id, type="thought", created_at=created_at, event_date="2026-08-24",
        importance=2, confidence=1.0, source="cli", status="active", title="t", content="c",
        raw_log_id=None, file_path="x.md", topics_json="[]",
    )


def test_set_memory_entities_replaces_previous_set(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        db.set_memory_entities(conn, "mem_1", ["ナイキ", "アディダス"])
        assert set(db.entities_for_memories(conn, ["mem_1"])["mem_1"]) == {"ナイキ", "アディダス"}

        db.set_memory_entities(conn, "mem_1", ["ナイキ"])
        assert db.entities_for_memories(conn, ["mem_1"])["mem_1"] == ["ナイキ"]


def test_entities_for_memories_batches_multiple_ids(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        _insert_bare_memory(conn, "mem_2")
        db.set_memory_entities(conn, "mem_1", ["ナイキ"])
        db.set_memory_entities(conn, "mem_2", ["クラルティ"])

        result = db.entities_for_memories(conn, ["mem_1", "mem_2", "mem_missing"])
        assert result["mem_1"] == ["ナイキ"]
        assert result["mem_2"] == ["クラルティ"]
        assert result["mem_missing"] == []


def test_list_active_memory_signals_excludes_given_id(config):
    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        _insert_bare_memory(conn, "mem_2")

        signals = db.list_active_memory_signals(conn, exclude_id="mem_1")
        ids = {s.id for s in signals}
        assert ids == {"mem_2"}


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
    import sqlite3

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


def test_links_table_rejects_dangling_reference(config):
    """外部キー制約により、存在しないmemoryを指すlinkは拒否される(reindexの2周目分割が
    必要な理由そのものを保証するテスト)。"""
    import sqlite3

    import pytest

    with db.connect(config) as conn:
        _insert_bare_memory(conn, "mem_1")
        with pytest.raises(sqlite3.IntegrityError):
            db.upsert_link(conn, source_memory_id="mem_1", target_memory_id="mem_does_not_exist", relation_type="same_topic", reason="x", created_at="2026-08-24T00:00:00+00:00")
            conn.commit()
