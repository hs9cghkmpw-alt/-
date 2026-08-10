#!/usr/bin/env python3
"""
apps/server/app/db_schema.sql を実際のSQLiteファイルに対して実行し、
データモデル(仕様書11)がSQLiteレベルで正しく機能するかを検証する。

このスクリプトは標準ライブラリのみに依存するため、FastAPI/SQLAlchemyが
インストールされていない環境(このサンドボックス)でも実行できる。
Docker環境では別途 apps/server/tests/ 配下のpytestスイートが同じ意味論を
ORM経由で検証する。

実行方法:
    python3 verification/db_schema_check.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL_PATH = REPO_ROOT / "apps" / "server" / "app" / "db_schema.sql"

PASS = []
FAIL = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS.append(name)
        print(f"  [OK] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [NG] {name} -- {detail}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fresh_connection() -> sqlite3.Connection:
    tmp = Path(tempfile.mkstemp(suffix=".sqlite3")[1])
    con = sqlite3.connect(str(tmp))
    con.execute("PRAGMA foreign_keys = ON")
    sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    con.executescript(sql)
    con.commit()
    return con


def section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> int:
    print(f"schema file: {SCHEMA_SQL_PATH}")
    assert SCHEMA_SQL_PATH.exists(), "db_schema.sql が見つかりません"

    con = fresh_connection()

    section("1. テーブル/仮想テーブル生成")
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
    expected = {
        "captures", "thoughts", "entities", "thought_entities", "thought_links",
        "feedback_events", "processing_jobs", "sync_devices", "app_settings",
        "pairing_codes", "thought_embeddings", "captures_fts", "thoughts_fts",
    }
    missing = expected - tables
    check("必要なテーブル/仮想テーブルが全て存在する", not missing, f"missing={missing}")

    section("2. captures: 冪等な同期 (client_id UNIQUE)")
    cap_id = str(uuid.uuid4())
    client_id = str(uuid.uuid4())
    ts = now_iso()
    con.execute(
        "INSERT INTO captures (id, client_id, raw_text, input_type, captured_at, received_at, "
        "sync_status, processing_status, source_device, client_version, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cap_id, client_id, "疲れた、Forgeの画面も気になる", "text", ts, ts, "synced", "not_started", "iphone", "1.0.0", ts, ts),
    )
    con.commit()

    # 同じclient_idで二重送信 -> INSERT OR IGNORE相当の冪等性をアプリ層で実現する前提だが、
    # ここではDB制約自体が二重INSERTを拒否することを確認する。
    dup_rejected = False
    try:
        con.execute(
            "INSERT INTO captures (id, client_id, raw_text, input_type, captured_at, received_at, "
            "sync_status, processing_status, source_device, client_version, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), client_id, "別内容(二重送信のつもり)", "text", ts, ts, "synced", "not_started", "iphone", "1.0.0", ts, ts),
        )
        con.commit()
    except sqlite3.IntegrityError:
        dup_rejected = True
        con.rollback()
    check("同一client_idの二重INSERTがUNIQUE制約で拒否される", dup_rejected)

    count = con.execute("SELECT COUNT(*) FROM captures WHERE client_id = ?", (client_id,)).fetchone()[0]
    check("結果としてcapturesは1件のまま", count == 1, f"count={count}")

    section("3. captures_fts: 日本語全文検索 (trigram)")
    row = con.execute("SELECT capture_id FROM captures_fts WHERE captures_fts MATCH '保育園' ").fetchall()
    check("挿入直後は無関係語でヒットしない", len(row) == 0)

    cap_id2 = str(uuid.uuid4())
    client_id2 = str(uuid.uuid4())
    con.execute(
        "INSERT INTO captures (id, client_id, raw_text, input_type, captured_at, received_at, "
        "sync_status, processing_status, source_device, client_version, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cap_id2, client_id2, "保育園の提出物が明日かもしれない", "text", ts, ts, "synced", "not_started", "iphone", "1.0.0", ts, ts),
    )
    con.commit()
    hits = con.execute("SELECT capture_id FROM captures_fts WHERE captures_fts MATCH '保育園'").fetchall()
    check("INSERTトリガーでFTSに反映され検索できる (3文字クエリ)", [h[0] for h in hits] == [cap_id2], f"hits={hits}")

    con.execute("UPDATE captures SET raw_text = ? WHERE id = ?", ("保育園の話はもう解決済みです", cap_id2))
    con.commit()
    # trigramトークナイザは3文字未満のクエリにはヒットしない仕様のため、3文字以上で検証する。
    hits2 = con.execute("SELECT capture_id FROM captures_fts WHERE captures_fts MATCH '解決済'").fetchall()
    hits2_old = con.execute("SELECT capture_id FROM captures_fts WHERE captures_fts MATCH '提出物'").fetchall()
    check(
        "UPDATEトリガーでFTSも更新される(新内容でヒットし、旧内容ではヒットしない)",
        [h[0] for h in hits2] == [cap_id2] and len(hits2_old) == 0,
        f"hits2={hits2} hits2_old={hits2_old}",
    )

    section("4. thoughts: capture分割・FK・カスケード削除")
    th_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO thoughts (id, capture_id, content, summary, types_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (th_id, cap_id, "疲れている", None, '["thought","body_state"]', ts, ts),
    )
    th_id2 = str(uuid.uuid4())
    con.execute(
        "INSERT INTO thoughts (id, capture_id, content, summary, types_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (th_id2, cap_id, "Forgeの画面が気になっている", None, '["concern"]', ts, ts),
    )
    con.commit()

    orphan_rejected = False
    try:
        con.execute(
            "INSERT INTO thoughts (id, capture_id, content, types_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), "存在しないcapture_id", "孤立思考", "[]", ts, ts),
        )
        con.commit()
    except sqlite3.IntegrityError:
        orphan_rejected = True
        con.rollback()
    check("存在しないcapture_idを指すthoughtはFK制約で拒否される", orphan_rejected)

    con.execute("DELETE FROM captures WHERE id = ?", (cap_id,))
    con.commit()
    remaining = con.execute("SELECT COUNT(*) FROM thoughts WHERE capture_id = ?", (cap_id,)).fetchone()[0]
    check("captureをハード削除するとthoughtsもCASCADE削除される", remaining == 0, f"remaining={remaining}")

    section("5. thoughts_fts 全文検索")
    th_id3 = str(uuid.uuid4())
    con.execute(
        "INSERT INTO thoughts (id, capture_id, content, summary, types_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (th_id3, cap_id2, "牛乳を買い忘れないようにする", "買い物メモ", '["shopping"]', ts, ts),
    )
    con.commit()
    hits3 = con.execute("SELECT thought_id FROM thoughts_fts WHERE thoughts_fts MATCH '買い物'").fetchall()
    check("thoughts_ftsでsummaryも検索対象になる", [h[0] for h in hits3] == [th_id3], f"hits3={hits3}")

    section("6. ソフトデリート (原文は消えない)")
    con.execute("UPDATE thoughts SET deleted_at = ? WHERE id = ?", (ts, th_id3))
    con.commit()
    still_there = con.execute("SELECT content FROM thoughts WHERE id = ?", (th_id3,)).fetchone()
    visible_in_default_view = con.execute(
        "SELECT COUNT(*) FROM thoughts WHERE id = ? AND deleted_at IS NULL", (th_id3,)
    ).fetchone()[0]
    check("ソフトデリート後もレコード自体は残る(原文を失わない)", still_there is not None and still_there[0] == "牛乳を買い忘れないようにする")
    check("通常一覧(deleted_at IS NULL)からは除外される", visible_in_default_view == 0)

    section("7. thought_links: 三つ組ユニーク制約")
    # th_id/th_id2 は section4 で capture ごとCASCADE削除済みなので、生きているcap_id2配下に
    # 新しくthoughtを2つ作ってからリンクを張る。
    link_src = str(uuid.uuid4())
    link_tgt = str(uuid.uuid4())
    con.execute(
        "INSERT INTO thoughts (id, capture_id, content, types_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (link_src, cap_id2, "第二の脳のアプリを作る", '["project"]', ts, ts),
    )
    con.execute(
        "INSERT INTO thoughts (id, capture_id, content, types_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (link_tgt, cap_id2, "第二の脳のUIを考える", '["idea"]', ts, ts),
    )
    con.commit()

    link_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO thought_links (id, source_thought_id, target_thought_id, relation_type, score, reason, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (link_id, link_src, link_tgt, "temporal_relation", 1.0, "同じ入力内", "rule", ts),
    )
    con.commit()
    link_dup_rejected = False
    try:
        con.execute(
            "INSERT INTO thought_links (id, source_thought_id, target_thought_id, relation_type, score, reason, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), link_src, link_tgt, "temporal_relation", 1.0, "重複", "rule", ts),
        )
        con.commit()
    except sqlite3.IntegrityError:
        link_dup_rejected = True
        con.rollback()
    check("同じ(source,target,relation_type)の重複リンクは拒否される", link_dup_rejected)

    section("8. processing_jobs: 再試行フロー")
    job_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO processing_jobs (id, capture_id, job_type, status, attempt_count, scheduled_at, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (job_id, cap_id2, "thought_split", "queued", 0, ts, ts, ts),
    )
    con.commit()
    con.execute(
        "UPDATE processing_jobs SET status='failed', attempt_count=attempt_count+1, last_error=? WHERE id=?",
        ("Ollama接続不可", job_id),
    )
    con.commit()
    job_row = con.execute("SELECT status, attempt_count, last_error FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
    check("ジョブの失敗・再試行回数が記録できる", job_row == ("failed", 1, "Ollama接続不可"), f"job_row={job_row}")

    section("9. app_settings upsert")
    con.execute(
        "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        ("ollama_model", '{"value":"qwen2.5:7b-instruct"}', ts),
    )
    con.execute(
        "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        ("ollama_model", '{"value":"qwen2.5:3b-instruct"}', ts),
    )
    con.commit()
    setting_count = con.execute("SELECT COUNT(*) FROM app_settings WHERE key='ollama_model'").fetchone()[0]
    setting_val = con.execute("SELECT value_json FROM app_settings WHERE key='ollama_model'").fetchone()[0]
    check("app_settingsはUPSERTで1行のまま更新される", setting_count == 1 and "3b" in setting_val, f"count={setting_count} val={setting_val}")

    section("10. sync_devices: 端末失効")
    dev_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO sync_devices (id, device_name, device_token_hash, created_at) VALUES (?,?,?,?)",
        (dev_id, "iPhone 16", "x" * 64, ts),
    )
    con.commit()
    con.execute("UPDATE sync_devices SET revoked_at = ? WHERE id = ?", (ts, dev_id))
    con.commit()
    revoked = con.execute("SELECT revoked_at FROM sync_devices WHERE id=?", (dev_id,)).fetchone()[0]
    check("端末を失効(revoked_at設定)できる", revoked == ts)

    con.close()

    print(f"\n合計: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("失敗:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
