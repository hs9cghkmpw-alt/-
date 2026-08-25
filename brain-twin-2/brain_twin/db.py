"""SQLite index/cache (指示書25・26章)。

Markdown(Vault)が正本で、ここは検索用のindexに過ぎない。
このファイルが壊れても `python brain.py reindex` でVaultから再構築できる
(絶対に守るべき設計原則、指示書34章)。

FTS5のtrigramトークナイザ + トリガーによる同期は、brain-twin(FastAPI版)の
apps/server/app/db_schema.sql で実際に動作検証済みの方式をそのまま踏襲している
(指示書38章: 既存構成の再利用可能部分)。

--- Link候補探索について(レビュー対応) ---

以前は「直近500件のMemoryを丸ごとPythonへロードし、Python側で全件比較する」
方式だったが、Brain Twinは長期記憶システムであり、件数が増えるほど古い
(しかし重要な)Memoryが候補から機械的に除外されてしまう問題があった。

代わりに、「同トピック」「同エンティティ」「時間的に近い」という3種類の候補探索
それぞれをSQLite側のクエリで行う(find_candidates_by_*)。これにより、
古いMemoryであっても、実際に関連しうる条件(トピック/エンティティ/時間)を
満たせば候補になれる。Link自体の強さ・順位付け(どのくらい関連が強いか)は
引き続きlinking.py(Python側)の責務のままにしてあり、DB層は「関連しうる
Memoryの絞り込み」だけを担当する(責務分離)。

【2回目のレビュー対応】find_candidates_by_* に付いていた `ORDER BY created_at
DESC LIMIT 200` を撤廃した。これは「直近500件」問題を「条件一致した中の
直近200件」に縮小しただけで、根本的には同じ欠陥(件数だけを理由に古い
Memoryを除外する)を残していた。トピック/エンティティ/時間という条件自体が
既に十分に意味のある絞り込みであるため、その結果をさらに件数で切り詰める
必要はないと判断した。

代わりに、絞り込んだ候補id集合を実際にDBへ問い合わせる側
(list_memory_signals_by_ids / entities_for_memories)を `_chunked()` で
バッチ分割するようにした。理由は、候補が増えた場合に `IN (?, ?, ...)` の
プレースホルダ数がSQLiteの上限(SQLITE_MAX_VARIABLE_NUMBER)に達して
クエリ自体が失敗する事態を避けるため。これにより「件数を理由に古い
Memoryを除外しない」ことと「候補が増えても1回のクエリが破綻しない」ことの
両方を、Python側で全件を毎回スキャンする構造に戻さずに満たす。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from brain_twin.config import Config
from brain_twin.embedding_provider import EmbeddingProfile
from brain_twin.embedding_vector import encode_embedding
from brain_twin.models import ExtractedEntity

# SQLiteの `IN (?, ?, ...)` はプレースホルダ数に上限がある(SQLITE_MAX_VARIABLE_NUMBER。
# ビルドにより999〜32766程度)。候補件数がどれだけ増えても1回のクエリが失敗しないよう、
# id集合をこの単位で分割してから問い合わせる(_chunked参照)。
_ID_QUERY_CHUNK_SIZE = 500

# strength導入前は実値が正本Markdownにも存在しない。旧Entity抽出の誤検出を
# relation_typeだけで強く扱わないよう、全legacy linkを一律の弱い値にする。
LEGACY_LINK_STRENGTH = 0.25


def _chunked(items: list[str], size: int = _ID_QUERY_CHUNK_SIZE) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]

SCHEMA_SQL = f"""
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
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories (created_at);

CREATE TABLE IF NOT EXISTS entities (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence  REAL NOT NULL DEFAULT 1.0,
    method      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (memory_id, entity_id)
);

CREATE TABLE IF NOT EXISTS links (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    relation_type      TEXT NOT NULL,
    reason             TEXT NOT NULL DEFAULT '',
    strength           REAL NOT NULL DEFAULT {LEGACY_LINK_STRENGTH},
    created_at         TEXT NOT NULL,
    UNIQUE (source_memory_id, target_memory_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_links_target_memory ON links (target_memory_id);

CREATE TABLE IF NOT EXISTS embedding_profiles (
    fingerprint                 TEXT PRIMARY KEY,
    provider_id                 TEXT NOT NULL,
    model_name                  TEXT NOT NULL,
    model_revision              TEXT NULL,
    profile_epoch               TEXT NULL,
    embedding_contract_version  INTEGER NOT NULL CHECK (embedding_contract_version > 0),
    dimension                   INTEGER NOT NULL CHECK (dimension > 0),
    normalized                  INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    document_template_version   INTEGER NOT NULL CHECK (document_template_version > 0),
    created_at                  TEXT NOT NULL,
    CHECK (
        (model_revision IS NOT NULL AND trim(model_revision) != '' AND lower(trim(model_revision)) != 'unknown')
        OR (profile_epoch IS NOT NULL AND trim(profile_epoch) != '' AND lower(trim(profile_epoch)) != 'unknown')
    )
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id           TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    profile_fingerprint TEXT NOT NULL REFERENCES embedding_profiles(fingerprint) ON DELETE CASCADE,
    content_hash        TEXT NOT NULL,
    embedding_blob      BLOB NOT NULL,
    is_valid            INTEGER NOT NULL DEFAULT 0 CHECK (is_valid IN (0, 1)),
    embedded_at         TEXT NOT NULL,
    PRIMARY KEY (memory_id, profile_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_profile
ON memory_embeddings(profile_fingerprint);

CREATE TABLE IF NOT EXISTS active_embedding_state (
    singleton                  INTEGER PRIMARY KEY CHECK (singleton = 1),
    active_profile_fingerprint TEXT REFERENCES embedding_profiles(fingerprint)
);

CREATE TABLE IF NOT EXISTS vector_backend_state (
    singleton                   INTEGER PRIMARY KEY CHECK (singleton = 1),
    backend                     TEXT NOT NULL,
    backend_schema_version      INTEGER NOT NULL CHECK (backend_schema_version > 0),
    indexed_profile_fingerprint TEXT REFERENCES embedding_profiles(fingerprint),
    build_status                TEXT NOT NULL,
    built_at                    TEXT
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

EMBEDDING_INVALIDATION_SQL = """
CREATE TRIGGER IF NOT EXISTS memories_embedding_invalidate_au
AFTER UPDATE OF title, content ON memories
WHEN old.title IS NOT new.title OR old.content IS NOT new.content
BEGIN
    UPDATE memory_embeddings SET is_valid = 0 WHERE memory_id = new.id;
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
    entities: list[str]
    rank: float


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """`CREATE TABLE IF NOT EXISTS` は既存テーブルに新しい列を追加してくれないため、
    以前のバージョンで作られた古いindex(reason/confidence/method列が無い状態)を
    持つ環境でも次回実行時に自動で追従できるようにする(指示書34章: データ消失禁止。
    再構築(reindex)を使わなくても壊れないようにする最小限の自己修復)。"""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _ensure_column(conn, "links", "reason", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        conn, "links", "strength", f"REAL NOT NULL DEFAULT {LEGACY_LINK_STRENGTH}"
    )
    _ensure_column(conn, "memory_entities", "confidence", "REAL NOT NULL DEFAULT 1.0")
    _ensure_column(conn, "memory_entities", "method", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        conn, "memory_embeddings", "is_valid",
        "INTEGER NOT NULL DEFAULT 0 CHECK (is_valid IN (0, 1))",
    )
    conn.executescript(EMBEDDING_INVALIDATION_SQL)
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
            DROP TABLE IF EXISTS vector_backend_state;
            DROP TABLE IF EXISTS active_embedding_state;
            DROP TABLE IF EXISTS memory_embeddings;
            DROP TABLE IF EXISTS embedding_profiles;
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


def upsert_embedding_profile(
    conn: sqlite3.Connection, profile: EmbeddingProfile, *, created_at: str
) -> str:
    fingerprint = profile.fingerprint
    conn.execute(
        """
        INSERT INTO embedding_profiles (
            fingerprint, provider_id, model_name, model_revision, profile_epoch,
            embedding_contract_version, dimension, normalized,
            document_template_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO NOTHING
        """,
        (
            fingerprint, profile.provider_id, profile.model_name,
            profile.model_revision, profile.profile_epoch,
            profile.embedding_contract_version, profile.dimension,
            int(profile.normalized), profile.document_template_version, created_at,
        ),
    )
    return fingerprint


def upsert_memory_embedding(
    conn: sqlite3.Connection, *, memory_id: str, profile: EmbeddingProfile,
    content_hash: str, vector: list[float] | tuple[float, ...], embedded_at: str
) -> None:
    blob = encode_embedding(vector, profile.dimension)
    conn.execute(
        """
        INSERT INTO memory_embeddings (
            memory_id, profile_fingerprint, content_hash, embedding_blob, is_valid, embedded_at
        ) VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(memory_id, profile_fingerprint) DO UPDATE SET
            content_hash=excluded.content_hash,
            embedding_blob=excluded.embedding_blob,
            is_valid=1,
            embedded_at=excluded.embedded_at
        """,
        (memory_id, profile.fingerprint, content_hash, blob, embedded_at),
    )


def delete_memory_embedding(
    conn: sqlite3.Connection, *, memory_id: str, profile_fingerprint: str
) -> None:
    """Delete a canonical cache row; VectorIndexBackend mutations never perform this step."""
    conn.execute(
        "DELETE FROM memory_embeddings WHERE memory_id = ? AND profile_fingerprint = ?",
        (memory_id, profile_fingerprint),
    )


def embedding_profile_dimension(conn: sqlite3.Connection, fingerprint: str) -> int:
    row = conn.execute(
        "SELECT dimension FROM embedding_profiles WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown embedding profile: {fingerprint}")
    return int(row[0])


def active_embedding_blobs(
    conn: sqlite3.Connection, fingerprint: str
) -> list[tuple[str, bytes]]:
    """Return only ids/vectors; ExactScan never loads Memory title or content."""
    return [
        (row[0], row[1])
        for row in conn.execute(
            """
            SELECT me.memory_id, me.embedding_blob
            FROM memory_embeddings me
            JOIN memories m ON m.id = me.memory_id
            WHERE me.profile_fingerprint = ? AND me.is_valid = 1 AND m.status = 'active'
            ORDER BY me.memory_id
            """,
            (fingerprint,),
        ).fetchall()
    ]


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


def get_raw_log_processed_at(conn: sqlite3.Connection, raw_log_id: str) -> str | None:
    """指定したraw_logのSQLite側processed_atを返す。行自体が存在しない場合もNoneを
    返す(reconcile.py が「SQLite側にはまだ反映されていない」を判定する際、行の
    不在とprocessed_at NULLを区別する必要が無いため、まとめてNoneにしている)。"""
    row = conn.execute("SELECT processed_at FROM raw_logs WHERE id = ?", (raw_log_id,)).fetchone()
    return row[0] if row else None


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


@dataclass(frozen=True)
class MemorySignal:
    """Link候補選定に必要な最小限のメタデータ(本文は含まない、軽量)。"""

    id: str
    topics: list[str]
    created_at: str  # ISO8601
    entities: list[ExtractedEntity]


def get_or_create_entity(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT INTO entities (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
    row = conn.execute("SELECT id FROM entities WHERE name = ?", (name,)).fetchone()
    return row[0]


def set_memory_entities(conn: sqlite3.Connection, memory_id: str, entities: list[ExtractedEntity]) -> None:
    """このMemoryのentity集合を丸ごと置き換える(reindexや再実行で何度実行しても
    同じ結果になるよう冪等)。confidence/methodも一緒に保存し、link候補探索
    (find_candidates_by_entities)や将来のUIで「どれくらい確からしいentityか」を
    参照できるようにする。"""
    conn.execute("DELETE FROM memory_entities WHERE memory_id = ?", (memory_id,))
    for entity in entities:
        entity_id = get_or_create_entity(conn, entity.name)
        conn.execute(
            "INSERT INTO memory_entities (memory_id, entity_id, confidence, method) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(memory_id, entity_id) DO NOTHING",
            (memory_id, entity_id, entity.confidence, entity.method),
        )


def entities_for_memories(conn: sqlite3.Connection, memory_ids: list[str]) -> dict[str, list[ExtractedEntity]]:
    """複数memory_idのentitiesをまとめて取得する(N+1を避ける)。
    id集合が大きくなっても1回のクエリが破綻しないよう、_chunked()でバッチに分けて
    問い合わせる(プレースホルダ数の上限対策。db.pyモジュールdocstring参照)。"""
    if not memory_ids:
        return {}
    result: dict[str, list[ExtractedEntity]] = {mid: [] for mid in memory_ids}
    for batch in _chunked(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT me.memory_id, e.name, me.confidence, me.method
            FROM memory_entities me
            JOIN entities e ON e.id = me.entity_id
            WHERE me.memory_id IN ({placeholders})
            """,
            batch,
        ).fetchall()
        for memory_id, name, confidence, method in rows:
            result[memory_id].append(ExtractedEntity(name=name, confidence=confidence, method=method))
    return result


def list_memory_signals_by_ids(conn: sqlite3.Connection, memory_ids: list[str]) -> list[MemorySignal]:
    """特定のid集合(find_candidates_by_*で絞り込んだ結果)のMemory軽量メタデータを
    まとめて取得する。id集合が大きくなっても1回のクエリが破綻しないよう、
    _chunked()でバッチに分けて問い合わせる。"""
    if not memory_ids:
        return []
    rows: list[tuple] = []
    for batch in _chunked(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        rows.extend(
            conn.execute(
                f"SELECT id, topics_json, created_at FROM memories WHERE id IN ({placeholders})",
                batch,
            ).fetchall()
        )
    entities_by_id = entities_for_memories(conn, [r[0] for r in rows])
    return [
        MemorySignal(id=r[0], topics=json.loads(r[1] or "[]"), created_at=r[2], entities=entities_by_id.get(r[0], []))
        for r in rows
    ]


def find_candidates_by_topics(conn: sqlite3.Connection, topics: list[str], *, exclude_id: str | None = None) -> set[str]:
    """topics_json(JSON配列)に、指定したtopicのいずれかが含まれるactiveなMemoryを探す。
    件数ベースの打ち切りは行わない(直近N件だけを見る、という絞り込みはしない)。
    条件(topics)そのものが既に意味のある絞り込みであり、それをさらに件数で
    切り詰めると、古いMemoryが機械的に除外されてしまうため(2回目のレビュー対応。
    db.pyモジュールdocstring参照)。"""
    if not topics:
        return set()
    placeholders = ",".join("?" for _ in topics)
    exclude_clause = "AND m.id != ?" if exclude_id else ""
    rows = conn.execute(
        f"""
        SELECT DISTINCT m.id
        FROM memories m, json_each(m.topics_json)
        WHERE json_each.value IN ({placeholders}) AND m.status = 'active' {exclude_clause}
        """,
        [*topics, *([exclude_id] if exclude_id else [])],
    ).fetchall()
    return {r[0] for r in rows}


def find_candidates_by_entities(conn: sqlite3.Connection, entity_names: list[str], *, exclude_id: str | None = None) -> set[str]:
    """指定したentity名のいずれかを持つactiveなMemoryを探す(件数ベースの打ち切りなし)。"""
    if not entity_names:
        return set()
    placeholders = ",".join("?" for _ in entity_names)
    exclude_clause = "AND me.memory_id != ?" if exclude_id else ""
    rows = conn.execute(
        f"""
        SELECT DISTINCT me.memory_id
        FROM memory_entities me
        JOIN entities e ON e.id = me.entity_id
        JOIN memories m ON m.id = me.memory_id
        WHERE e.name IN ({placeholders}) AND m.status = 'active' {exclude_clause}
        """,
        [*entity_names, *([exclude_id] if exclude_id else [])],
    ).fetchall()
    return {r[0] for r in rows}


def find_candidates_by_time_range(conn: sqlite3.Connection, start_iso: str, end_iso: str, *, exclude_id: str | None = None) -> set[str]:
    """created_atが[start_iso, end_iso]の範囲に入るactiveなMemoryを探す
    (ISO8601文字列は同一フォーマットである限り辞書順比較が時系列順と一致するため、
    BETWEENでの範囲検索がそのまま使える)。この検索自体が時間窓で既に絞られているため、
    件数ベースの追加の打ち切りは付けていない。"""
    exclude_clause = "AND id != ?" if exclude_id else ""
    rows = conn.execute(
        f"""
        SELECT id FROM memories
        WHERE status = 'active' AND created_at BETWEEN ? AND ? {exclude_clause}
        """,
        [start_iso, end_iso, *([exclude_id] if exclude_id else [])],
    ).fetchall()
    return {r[0] for r in rows}


def upsert_link(
    conn: sqlite3.Connection,
    *,
    source_memory_id: str,
    target_memory_id: str,
    relation_type: str,
    reason: str,
    strength: float = LEGACY_LINK_STRENGTH,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO links (source_memory_id, target_memory_id, relation_type, reason, strength, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_memory_id, target_memory_id, relation_type) DO UPDATE SET
            reason=excluded.reason, strength=excluded.strength, created_at=excluded.created_at
        """,
        (source_memory_id, target_memory_id, relation_type, reason, strength, created_at),
    )


@dataclass(frozen=True)
class LinkRow:
    target_memory_id: str
    relation_type: str
    reason: str
    strength: float


@dataclass(frozen=True)
class RelatedLinkRow:
    """A one-hop link plus the active memory at its opposite endpoint."""

    primary_memory_id: str
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    relation_type: str
    reason: str
    strength: float
    direction: str


@dataclass(frozen=True)
class RelatedCandidateRow:
    """Ranking用の軽量Link情報。Memory本文は意図的に含めない。"""

    primary_memory_id: str
    memory_id: str
    importance: int
    relation_type: str
    reason: str
    strength: float
    direction: str


@dataclass(frozen=True)
class MemoryDetailRow:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str


def links_for_memory(conn: sqlite3.Connection, memory_id: str) -> list[LinkRow]:
    """source側から見たリンクのみを返す(このMemoryが起点になっているもの)。"""
    rows = conn.execute(
        "SELECT target_memory_id, relation_type, reason, strength FROM links WHERE source_memory_id = ?",
        (memory_id,),
    ).fetchall()
    return [LinkRow(target_memory_id=r[0], relation_type=r[1], reason=r[2], strength=r[3]) for r in rows]


def outgoing_links_for_memory(conn: sqlite3.Connection, memory_id: str) -> list[RelatedLinkRow]:
    """Return outgoing links whose target memory is active."""
    return _related_links(conn, [memory_id], direction="outgoing")


def incoming_links_for_memory(conn: sqlite3.Connection, memory_id: str) -> list[RelatedLinkRow]:
    """Return incoming links whose source memory is active."""
    return _related_links(conn, [memory_id], direction="incoming")


def related_links_for_memories(conn: sqlite3.Connection, memory_ids: list[str]) -> list[RelatedLinkRow]:
    """Return incoming and outgoing one-hop links for a set of primary memories."""
    if not memory_ids:
        return []
    rows: list[RelatedLinkRow] = []
    for batch in _chunked(memory_ids):
        rows.extend(_related_links(conn, batch, direction="outgoing"))
        rows.extend(_related_links(conn, batch, direction="incoming"))
    return rows


def related_link_candidates_for_memories(
    conn: sqlite3.Connection, memory_ids: list[str]
) -> list[RelatedCandidateRow]:
    """Primary集合の1-hop候補を本文なしで取得する。ranking前の全本文ロードを避ける。"""
    if not memory_ids:
        return []
    rows: list[RelatedCandidateRow] = []
    for batch in _chunked(memory_ids):
        rows.extend(_related_link_candidates(conn, batch, direction="outgoing"))
        rows.extend(_related_link_candidates(conn, batch, direction="incoming"))
    return rows


def _related_link_candidates(
    conn: sqlite3.Connection, memory_ids: list[str], *, direction: str
) -> list[RelatedCandidateRow]:
    placeholders = ",".join("?" for _ in memory_ids)
    if direction == "outgoing":
        primary_column = "l.source_memory_id"
        related_column = "l.target_memory_id"
    elif direction == "incoming":
        primary_column = "l.target_memory_id"
        related_column = "l.source_memory_id"
    else:
        raise ValueError(f"unknown link direction: {direction}")
    records = conn.execute(
        f"""
        SELECT {primary_column}, m.id, m.importance, l.relation_type,
               l.reason, l.strength
        FROM links l
        JOIN memories m ON m.id = {related_column}
        WHERE {primary_column} IN ({placeholders}) AND m.status = 'active'
        ORDER BY {primary_column}, m.id, l.relation_type, l.id
        """,
        memory_ids,
    ).fetchall()
    return [RelatedCandidateRow(*row, direction=direction) for row in records]


def memory_details_by_ids(
    conn: sqlite3.Connection, memory_ids: list[str]
) -> dict[str, MemoryDetailRow]:
    """選抜済みMemoryだけの表示詳細を取得する。大きなID集合にもchunkingで対応する。"""
    result: dict[str, MemoryDetailRow] = {}
    for batch in _chunked(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT id, title, content, type, event_date
            FROM memories
            WHERE id IN ({placeholders}) AND status = 'active'
            """,
            batch,
        ).fetchall()
        for row in rows:
            detail = MemoryDetailRow(*row)
            result[detail.memory_id] = detail
    return result


def _related_links(
    conn: sqlite3.Connection, memory_ids: list[str], *, direction: str
) -> list[RelatedLinkRow]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    if direction == "outgoing":
        primary_column = "l.source_memory_id"
        related_column = "l.target_memory_id"
    elif direction == "incoming":
        primary_column = "l.target_memory_id"
        related_column = "l.source_memory_id"
    else:
        raise ValueError(f"unknown link direction: {direction}")
    records = conn.execute(
        f"""
        SELECT {primary_column}, m.id, m.title, m.content, m.type,
               m.event_date, m.importance, l.relation_type, l.reason, l.strength
        FROM links l
        JOIN memories m ON m.id = {related_column}
        WHERE {primary_column} IN ({placeholders}) AND m.status = 'active'
        ORDER BY {primary_column}, m.id, l.relation_type, l.id
        """,
        memory_ids,
    ).fetchall()
    return [RelatedLinkRow(*row, direction=direction) for row in records]


@dataclass(frozen=True)
class TimelineRow:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float


def timeline_memories(
    conn: sqlite3.Connection,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
) -> list[TimelineRow]:
    """Filter active long-term memories by inclusive event-date bounds in SQL."""
    clauses = ["status = 'active'"]
    params: list[str | int] = []
    if from_date is not None:
        clauses.append("event_date >= ?")
        params.append(from_date)
    if to_date is not None:
        clauses.append("event_date <= ?")
        params.append(to_date)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, title, content, type, event_date, importance, confidence
        FROM memories
        WHERE {' AND '.join(clauses)}
        ORDER BY event_date ASC, created_at ASC, id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [TimelineRow(*row) for row in rows]


@dataclass(frozen=True)
class LexicalCandidate:
    """Pure BM25 relevance for one Memory; no metadata weighting, no body/entities.

    This is the API Hybrid ranking (Sprint 4C) must use instead of `search()`, which already
    has importance/confidence/recency baked into its ordering."""

    memory_id: str
    bm25_score: float
    lexical_rank: int


def search_lexical_candidates(
    conn: sqlite3.Connection, query: str, *, limit: int
) -> list[LexicalCandidate]:
    """Hybrid-only candidate API (Sprint 4C final hardening: deterministic tie-break).

    `bm25()` scores can legitimately tie (short/duplicate content, identical term
    frequencies). `lexical_rank` feeds directly into Weighted RRF and into Hybrid's
    best-channel-rank tie-break, so an unordered tie there would make Hybrid results
    non-deterministic across otherwise-identical calls. `m.id ASC` breaks ties explicitly
    and stably, independent of SQLite's incidental physical row order (which `reindex`'s
    file-listing order does not guarantee to reproduce).

    `db.search()` (used by `search.search()`) is unaffected -- it keeps its own `ORDER BY
    rank` unchanged for backward compatibility; this function is Hybrid-only."""
    if limit <= 0:
        return []
    phrase = '"' + query.replace('"', '""') + '"'
    rows = conn.execute(
        """
        SELECT m.id, bm25(memories_fts) AS score
        FROM memories_fts
        JOIN memories m ON m.id = memories_fts.memory_id
        WHERE memories_fts MATCH ? AND m.status = 'active'
        ORDER BY score ASC, m.id ASC
        LIMIT ?
        """,
        (phrase, limit),
    ).fetchall()
    return [
        LexicalCandidate(memory_id=r[0], bm25_score=r[1], lexical_rank=rank)
        for rank, r in enumerate(rows, start=1)
    ]


@dataclass(frozen=True)
class MemoryRankingSignal:
    """Lightweight metadata for scoring a Hybrid candidate; no title/content/topics/entities."""

    memory_id: str
    importance: int
    confidence: float
    event_date: str


def memory_ranking_signals_by_ids(
    conn: sqlite3.Connection, memory_ids: list[str]
) -> dict[str, MemoryRankingSignal]:
    """Fetch just enough to compute `metadata_multiplier()` for the full Hybrid candidate
    union, before any dedupe/ranking/limit trims it to the final top N."""
    if not memory_ids:
        return {}
    result: dict[str, MemoryRankingSignal] = {}
    for batch in _chunked(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT id, importance, confidence, event_date FROM memories
            WHERE id IN ({placeholders}) AND status = 'active'
            """,
            batch,
        ).fetchall()
        for r in rows:
            result[r[0]] = MemoryRankingSignal(
                memory_id=r[0], importance=r[1], confidence=r[2], event_date=r[3]
            )
    return result


@dataclass(frozen=True)
class MemoryResultDetail:
    """Full display detail for a Vector/Hybrid result; fetched only for the final top N ids."""

    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float
    topics: list[str]
    entities: list[str]


def memory_result_details_by_ids(
    conn: sqlite3.Connection, memory_ids: list[str]
) -> dict[str, MemoryResultDetail]:
    if not memory_ids:
        return {}
    raw: dict[str, tuple] = {}
    for batch in _chunked(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT id, title, content, type, event_date, importance, confidence, topics_json
            FROM memories WHERE id IN ({placeholders}) AND status = 'active'
            """,
            batch,
        ).fetchall()
        raw.update({r[0]: r for r in rows})
    entities_by_id = entities_for_memories(conn, list(raw.keys()))
    return {
        memory_id: MemoryResultDetail(
            memory_id=memory_id, title=r[1], content=r[2], type=r[3], event_date=r[4],
            importance=r[5], confidence=r[6], topics=json.loads(r[7] or "[]"),
            entities=[e.name for e in entities_by_id.get(memory_id, [])],
        )
        for memory_id, r in raw.items()
    }


def search(conn: sqlite3.Connection, query: str, *, limit: int = 20) -> list[SearchHit]:
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

    entities_by_id = entities_for_memories(conn, [r[0] for r in rows])

    return [
        SearchHit(
            memory_id=r[0], title=r[1], content=r[2], type=r[3], event_date=r[4],
            importance=r[5], confidence=r[6], status=r[7], topics=json.loads(r[8] or "[]"),
            entities=[e.name for e in entities_by_id.get(r[0], [])], rank=r[9],
        )
        for r in rows
    ]
