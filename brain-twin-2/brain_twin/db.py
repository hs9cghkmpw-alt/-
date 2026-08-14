"""SQLite index/cache (指示書25・26章)。

Markdown(Vault)が正本で、ここは検索用のindexに過ぎない。
このファイルが壊れても `python brain.py reindex` でVaultから再構築できる
(絶対に守るべき設計原則、指示書34章)。

FTS5のtrigramトークナイザ + トリガーによる同期は、brain-twin(FastAPI版)の
apps/server/app/db_schema.sql で実際に動作検証済みの方式をそのまま踏襲している
(指示書38章: 既存構成の再利用可能部分)。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from brain_twin.config import Config

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS raw_logs (
    id            TEXT PRIMARY KEY,
    text          TEXT NOT NULL,
    source        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    processed_at  TEXT
);

CREATE TABLE IF NOT EXISTS daily_logs (
    date        TEXT PRIMARY KEY,
    file_path   TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    event_date    TEXT NOT NULL,
    importance    INTEGER NOT NULL,
    confidence    REAL NOT NULL,
    source        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    title         TEXT NOT NULL,
    content       TEXT NOT NULL,
    raw_log_id    TEXT REFERENCES raw_logs(id),
    file_path     TEXT NOT NULL,
    topics_json   TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_memories_event_date ON memories (event_date);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories (type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories (status);

CREATE TABLE IF NOT EXISTS entities (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id  TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (memory_id, entity_id)
);

CREATE TABLE IF NOT EXISTS links (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    relation_type      TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    UNIQUE (source_memory_id, target_memory_id, relation_type)
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    title,
    content,
    topics,
    tokenize = 'trigram'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (memory_id, title, content, topics)
    VALUES (new.id, new.title, new.content, new.topics_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.id;
    INSERT INTO memories_fts (memory_id, title, content, topics)
    VALUES (new.id, new.title, new.content, new.topics_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.id;
END;
"""


@dataclass(frozen=True)
class SearchHit:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float
    status: str
    topics: list[str]
    rank: float


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


@contextmanager
def connect(config: Config) -> Iterator[sqlite3.Connection]:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _apply_schema(conn)
        yield conn
    finally:
        conn.close()


def reset_schema(db_path: Path) -> None:
    """既存のindexを完全に破棄し、空のスキーマだけを作り直す(reindex用)。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS memories_fts;
            DROP TABLE IF EXISTS memory_entities;
            DROP TABLE IF EXISTS links;
            DROP TABLE IF EXISTS entities;
            DROP TABLE IF EXISTS memories;
            DROP TABLE IF EXISTS daily_logs;
            DROP TABLE IF EXISTS raw_logs;
            """
        )
        _apply_schema(conn)
    finally:
        conn.close()


def upsert_raw_log(conn: sqlite3.Connection, *, id: str, text: str, source: str, created_at: str, file_path: str, processed_at: str | None) -> None:
    conn.execute(
        """
        INSERT INTO raw_logs (id, text, source, created_at, file_path, processed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            text=excluded.text, source=excluded.source, created_at=excluded.created_at,
            file_path=excluded.file_path, processed_at=excluded.processed_at
        """,
        (id, text, source, created_at, file_path, processed_at),
    )


def upsert_daily_log(conn: sqlite3.Connection, *, date: str, file_path: str, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO daily_logs (date, file_path, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET file_path=excluded.file_path, updated_at=excluded.updated_at
        """,
        (date, file_path, updated_at),
    )


def upsert_memory(
    conn: sqlite3.Connection,
    *,
    id: str,
    type: str,
    created_at: str,
    event_date: str,
    importance: int,
    confidence: float,
    source: str,
    status: str,
    title: str,
    content: str,
    raw_log_id: str | None,
    file_path: str,
    topics_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO memories (id, type, created_at, event_date, importance, confidence, source, status, title, content, raw_log_id, file_path, topics_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            type=excluded.type, created_at=excluded.created_at, event_date=excluded.event_date,
            importance=excluded.importance, confidence=excluded.confidence, source=excluded.source,
            status=excluded.status, title=excluded.title, content=excluded.content,
            raw_log_id=excluded.raw_log_id, file_path=excluded.file_path, topics_json=excluded.topics_json
        """,
        (id, type, created_at, event_date, importance, confidence, source, status, title, content, raw_log_id, file_path, topics_json),
    )


def search(conn: sqlite3.Connection, query: str, *, limit: int = 20) -> list[SearchHit]:
    import json as _json

    phrase = '"' + query.replace('"', '""') + '"'
    rows = conn.execute(
        """
        SELECT m.id, m.title, m.content, m.type, m.event_date, m.importance, m.confidence, m.status, m.topics_json,
               bm25(memories_fts) AS rank
        FROM memories_fts
        JOIN memories m ON m.id = memories_fts.memory_id
        WHERE memories_fts MATCH ? AND m.status = 'active'
        ORDER BY rank
        LIMIT ?
        """,
        (phrase, limit),
    ).fetchall()

    return [
        SearchHit(
            memory_id=r[0], title=r[1], content=r[2], type=r[3], event_date=r[4],
            importance=r[5], confidence=r[6], status=r[7], topics=_json.loads(r[8] or "[]"),
            rank=r[9],
        )
        for r in rows
    ]
