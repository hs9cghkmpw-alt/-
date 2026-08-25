"""MemoryをSQLiteへ反映する処理(指示書25章: SQLiteはMarkdownの写しにすぎない)。

pipeline.py の process_all/_process_one/reindex と、reconcile.py の両方が
同じ「Markdownに書かれているMemoryをSQLiteへ反映する」処理を必要とする
(reconcileはMarkdown上processed_at済みなのにSQLite未反映のraw_logを見つけて、
対応するMemoryを改めてSQLiteへ反映する)。この共通処理をpipeline.pyから
切り出して独立したモジュールにすることで、reconcile.pyがpipeline.pyに
依存せずに済む(pipeline.py → reconcile.py という依存の向きを保ち、
reconcile.py → pipeline.py という逆向きの依存(循環import)を作らない)。
"""
from __future__ import annotations

import json
import sqlite3

from brain_twin import db, memory_io
from brain_twin.models import Memory


# 公開名は後方互換テストと説明用。値の正本はDB migrationと共有する。
LEGACY_LINK_STRENGTH = db.LEGACY_LINK_STRENGTH


def persist_memory(conn: sqlite3.Connection, memory: Memory) -> None:
    """MemoryのMarkdown内容(本体行 + entities)をSQLiteへ反映する。"""
    db.upsert_memory(
        conn,
        id=memory.id, type=memory.type.value, created_at=memory.created_at,
        event_date=memory.event_date, importance=memory.importance,
        confidence=memory.confidence, source=memory.source, status=memory.status.value,
        title=memory.title, content=memory.content, raw_log_id=memory.raw_log_id,
        file_path=memory.file_path, topics_json=json.dumps(memory.topics, ensure_ascii=False),
    )
    db.set_memory_entities(conn, memory.id, memory_io.entity_objects(memory))


def persist_links(conn: sqlite3.Connection, memory_id: str, link_details: list[dict], fallback_created_at: str) -> None:
    """link_details(Markdownに書かれている内容)をそのままSQLiteへ反映する。
    新規生成時・reindex時・process再実行時(クラッシュからの復旧)・reconcile時の
    すべてでこの関数を通すことで、『SQLiteの内容は常にMarkdownの言っていることの写し』
    という原則を1箇所に集約する。fallback_created_atは、このfix以前に書かれた
    link_details(created_at/strengthを持たない)を読んだ場合の後方互換用。"""
    for detail in link_details:
        target = detail.get("target")
        if not target:
            continue
        stored_strength = detail.get("strength")
        db.upsert_link(
            conn, source_memory_id=memory_id, target_memory_id=target,
            relation_type=detail.get("relation_type", "related"),
            reason=detail.get("reason", ""),
            strength=float(stored_strength) if stored_strength is not None else LEGACY_LINK_STRENGTH,
            created_at=detail.get("created_at") or fallback_created_at,
        )
