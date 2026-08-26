"""Sprint 4D item 8: legacy migration validation against a single combined old-DB fixture.

Individual self-heal contracts (links missing reason/strength, memory_entities missing
confidence/method, memory_embeddings missing is_valid, embedding tables absent entirely) are
already each covered in isolation by test_db_entities_links.py and test_vector_storage.py.
This file combines all of those gaps into one realistic "genuinely old" database -- the kind
that would exist if a Vault had been running since before Phase 2/Sprint 4A -- to confirm the
self-heal steps do not interfere with each other and an unrelated table survives untouched.
"""
from __future__ import annotations

import sqlite3

from brain_twin import db
from brain_twin.pipeline import reindex


def test_connect_self_heals_a_fully_legacy_database_without_touching_unrelated_data(config):
    config.data_dir.mkdir(parents=True)
    old = sqlite3.connect(config.db_path)
    old.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, created_at TEXT NOT NULL,
            event_date TEXT NOT NULL, importance INTEGER NOT NULL, confidence REAL NOT NULL,
            source TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
            raw_log_id TEXT, file_path TEXT NOT NULL, topics_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE memory_entities (
            memory_id TEXT NOT NULL, entity_id INTEGER NOT NULL,
            PRIMARY KEY (memory_id, entity_id)
        );
        CREATE TABLE links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_memory_id TEXT NOT NULL, target_memory_id TEXT NOT NULL,
            relation_type TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE (source_memory_id, target_memory_id, relation_type)
        );
        CREATE TABLE operator_notes (note TEXT NOT NULL);
        INSERT INTO operator_notes VALUES ('do not delete me');
        INSERT INTO memories VALUES (
            'legacy_1', 'thought', '2020-01-01T00:00:00+00:00', '2020-01-01', 3, 1.0,
            'legacy', 'active', 'old title', 'old content', NULL, 'legacy_1.md', '[]'
        );
        INSERT INTO memories VALUES (
            'legacy_2', 'thought', '2020-01-02T00:00:00+00:00', '2020-01-02', 3, 1.0,
            'legacy', 'active', 'other title', 'other content', NULL, 'legacy_2.md', '[]'
        );
        INSERT INTO entities VALUES (1, 'LegacyEntity');
        INSERT INTO memory_entities VALUES ('legacy_1', 1);
        INSERT INTO links VALUES (1, 'legacy_1', 'legacy_2', 'same_topic', '2020-01-01T00:00:00+00:00');
        CREATE TABLE memory_embeddings(
            memory_id TEXT NOT NULL, profile_fingerprint TEXT NOT NULL,
            content_hash TEXT NOT NULL, embedding_blob BLOB NOT NULL, embedded_at TEXT NOT NULL,
            PRIMARY KEY(memory_id, profile_fingerprint)
        );
        INSERT INTO memory_embeddings VALUES ('legacy_1', 'old-profile', 'hash', X'00000000', '2020-01-01T00:00:00+00:00');
        """
        # No embedding_profiles / active_embedding_state / vector_backend_state tables at all
        # (this DB predates Sprint 4A entirely), and no memories_fts (predates FTS trigger sync).
    )
    old.commit()
    old.close()

    with db.connect(config) as conn:
        # 1. Unrelated table/data is not destroyed.
        assert conn.execute("SELECT note FROM operator_notes").fetchone()[0] == "do not delete me"
        assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 2

        # 2. All missing embedding-related tables were created.
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"embedding_profiles", "active_embedding_state", "vector_backend_state"} <= names

        # 3. Legacy embedding rows self-heal to the safe side: invalid, not silently trusted.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_embeddings)")}
        assert "is_valid" in columns
        assert conn.execute(
            "SELECT is_valid FROM memory_embeddings WHERE memory_id = 'legacy_1'"
        ).fetchone()[0] == 0

        # 4. Legacy links/entities tables self-healed their missing columns too.
        link_columns = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
        assert {"reason", "strength"} <= link_columns
        entity_columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_entities)")}
        assert {"confidence", "method"} <= entity_columns

        # 5. Legacy strength (introduced after this DB's links row was written) restores to the
        # conservative fallback, not some invented high-confidence value.
        assert conn.execute(
            "SELECT strength FROM links WHERE source_memory_id = 'legacy_1'"
        ).fetchone()[0] == db.LEGACY_LINK_STRENGTH

        # 6. FTS still usable after self-heal (memories_fts is rebuilt/kept in sync).
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")
        rows = conn.execute(
            "SELECT memory_id FROM memories_fts WHERE memories_fts MATCH 'old' "
        ).fetchall()
        # Not asserting exact content here (FTS backfill for pre-existing rows on legacy
        # migration is a separate, already-covered concern) -- only that the query executes
        # without raising, proving the table exists and is queryable post self-heal.
        assert isinstance(rows, list)

    # 7. A full `reindex` from an (empty, in this fixture) Vault still works cleanly afterward
    # -- self-healing a legacy DB must never leave it in a state reindex can't recover from.
    counts = reindex(config)
    assert counts["memories"] == 0
