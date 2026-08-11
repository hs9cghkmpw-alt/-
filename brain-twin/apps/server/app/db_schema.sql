-- Brain Twin データベーススキーマ (仕様書11「データモデル」対応)
--
-- SQLite上で直接実行できる生SQLとして管理する(alembicのマイグレーション本体からも
-- このファイルをそのまま実行する)。FTS5(trigramトークナイザ)や外部キーの
-- カスケード削除など、SQLAlchemyのdeclarativeだけでは表現しづらい部分を
-- ここで明示的に定義し、verification/db_schema_check.py で意味論を検証する。
--
-- 日時列はすべてISO8601文字列(UTC, "...Z"終わり)をTEXTとして保存する
-- (SQLiteにネイティブなdatetime型は無いため、アプリ層のシリアライズと合わせる)。

PRAGMA foreign_keys = ON;

-- ==================================================================
-- captures: 預けられた入力そのもの(未整理の原文)
-- ==================================================================
CREATE TABLE IF NOT EXISTS captures (
    id                 TEXT PRIMARY KEY,
    client_id          TEXT NOT NULL UNIQUE,
    raw_text           TEXT NOT NULL,
    input_type         TEXT NOT NULL DEFAULT 'text',
    captured_at        TEXT NOT NULL,
    received_at        TEXT NOT NULL,
    sync_status        TEXT NOT NULL DEFAULT 'synced',
    processing_status  TEXT NOT NULL DEFAULT 'not_started',
    source_device      TEXT,
    client_version     TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    deleted_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_captures_updated_at ON captures (updated_at);
CREATE INDEX IF NOT EXISTS idx_captures_processing_status ON captures (processing_status);

-- ==================================================================
-- thoughts: captureをAIが意味のまとまりへ分割した個々の思考
-- ==================================================================
CREATE TABLE IF NOT EXISTS thoughts (
    id                     TEXT PRIMARY KEY,
    capture_id             TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    content                TEXT NOT NULL,
    summary                TEXT,
    types_json             TEXT NOT NULL DEFAULT '[]',
    action_intent          REAL,
    resurface_need         REAL,
    emotional_weight       REAL,
    sentiment              TEXT,
    user_notes             TEXT,
    certainty              REAL,
    importance             REAL,
    urgency                REAL,
    mental_load            REAL,
    forget_safely_score    REAL,
    possible_dates_json    TEXT NOT NULL DEFAULT '[]',
    project_names_json     TEXT NOT NULL DEFAULT '[]',
    people_json            TEXT NOT NULL DEFAULT '[]',
    places_json            TEXT NOT NULL DEFAULT '[]',
    ai_model               TEXT,
    ai_prompt_version      TEXT,
    analysis_version       TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    deleted_at             TEXT,
    done_at                TEXT
);

CREATE INDEX IF NOT EXISTS idx_thoughts_capture_id ON thoughts (capture_id);
CREATE INDEX IF NOT EXISTS idx_thoughts_updated_at ON thoughts (updated_at);
CREATE INDEX IF NOT EXISTS idx_thoughts_deleted_at ON thoughts (deleted_at);
CREATE INDEX IF NOT EXISTS idx_thoughts_done_at ON thoughts (done_at);

-- ==================================================================
-- entities: 動的ラベル(人物/場所/プロジェクト/感情/話題等)の正規化辞書
-- ==================================================================
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    aliases_json    TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (entity_type, canonical_name)
);

-- ==================================================================
-- thought_entities: thought <-> entity の多対多
-- ==================================================================
CREATE TABLE IF NOT EXISTS thought_entities (
    thought_id   TEXT NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
    entity_id    TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence   REAL,
    created_by   TEXT NOT NULL DEFAULT 'ai',
    PRIMARY KEY (thought_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_thought_entities_entity_id ON thought_entities (entity_id);

-- ==================================================================
-- thought_links: thought同士の関連(ルールベース/意味的類似度/ユーザー確認)
-- ==================================================================
CREATE TABLE IF NOT EXISTS thought_links (
    id                  TEXT PRIMARY KEY,
    source_thought_id   TEXT NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
    target_thought_id   TEXT NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL,
    score               REAL,
    reason              TEXT,
    created_by          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (source_thought_id, target_thought_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_thought_links_source ON thought_links (source_thought_id);
CREATE INDEX IF NOT EXISTS idx_thought_links_target ON thought_links (target_thought_id);

-- ==================================================================
-- thought_embeddings: 意味検索/類似リンク用の埋め込みベクトル(JSON配列で保存)
-- ==================================================================
CREATE TABLE IF NOT EXISTS thought_embeddings (
    thought_id   TEXT PRIMARY KEY REFERENCES thoughts(id) ON DELETE CASCADE,
    model        TEXT NOT NULL,
    dim          INTEGER NOT NULL,
    vector_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- ==================================================================
-- feedback_events: ユーザーの操作履歴(仕様書19)。追記のみ、上書きしない。
-- ==================================================================
CREATE TABLE IF NOT EXISTS feedback_events (
    id            TEXT PRIMARY KEY,
    thought_id    TEXT REFERENCES thoughts(id) ON DELETE CASCADE,
    capture_id    TEXT REFERENCES captures(id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,
    event_value   TEXT,
    context_json  TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_thought_id ON feedback_events (thought_id);
CREATE INDEX IF NOT EXISTS idx_feedback_events_capture_id ON feedback_events (capture_id);

-- ==================================================================
-- processing_jobs: AIパイプラインの非同期実行キュー
-- ==================================================================
CREATE TABLE IF NOT EXISTS processing_jobs (
    id              TEXT PRIMARY KEY,
    capture_id      TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    job_type        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    scheduled_at    TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_status_scheduled ON processing_jobs (status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_capture_id ON processing_jobs (capture_id);

-- ==================================================================
-- sync_devices: ペアリング済み端末(iPhone)
-- ==================================================================
CREATE TABLE IF NOT EXISTS sync_devices (
    id                  TEXT PRIMARY KEY,
    device_name         TEXT NOT NULL,
    device_token_hash   TEXT NOT NULL UNIQUE,
    last_seen_at        TEXT,
    revoked_at          TEXT,
    created_at          TEXT NOT NULL
);

-- ==================================================================
-- pairing_codes: 短命なペアリングコード
-- ==================================================================
CREATE TABLE IF NOT EXISTS pairing_codes (
    code          TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    consumed_at   TEXT
);

-- ==================================================================
-- app_settings: key-value設定 (UPSERT運用)
-- ==================================================================
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ==================================================================
-- captures_fts / thoughts_fts: 日本語対応の全文検索 (FTS5, trigramトークナイザ)
--
-- content=方式の外部コンテンツテーブルは、id列がINTEGER rowidと一致しない
-- (captures.id/thoughts.idはTEXTのUUID)ため使わず、独立したFTS5テーブルを
-- トリガーで同期する方式にする。3文字以上のクエリでのマッチを想定
-- (trigramトークナイザの既知の制約)。
-- ==================================================================
CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
    capture_id UNINDEXED,
    raw_text,
    tokenize = 'trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS thoughts_fts USING fts5(
    thought_id UNINDEXED,
    content,
    summary,
    tokenize = 'trigram'
);

CREATE TRIGGER IF NOT EXISTS captures_fts_ai AFTER INSERT ON captures BEGIN
    INSERT INTO captures_fts (capture_id, raw_text) VALUES (new.id, new.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS captures_fts_au AFTER UPDATE ON captures BEGIN
    DELETE FROM captures_fts WHERE capture_id = old.id;
    INSERT INTO captures_fts (capture_id, raw_text) VALUES (new.id, new.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS captures_fts_ad AFTER DELETE ON captures BEGIN
    DELETE FROM captures_fts WHERE capture_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS thoughts_fts_ai AFTER INSERT ON thoughts BEGIN
    INSERT INTO thoughts_fts (thought_id, content, summary) VALUES (new.id, new.content, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS thoughts_fts_au AFTER UPDATE ON thoughts BEGIN
    DELETE FROM thoughts_fts WHERE thought_id = old.id;
    INSERT INTO thoughts_fts (thought_id, content, summary) VALUES (new.id, new.content, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS thoughts_fts_ad AFTER DELETE ON thoughts BEGIN
    DELETE FROM thoughts_fts WHERE thought_id = old.id;
END;
