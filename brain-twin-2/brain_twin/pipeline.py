"""Raw Log -> Daily Log -> (Memory) の一連の処理(指示書3・20章)。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from brain_twin import classify, db, linking, memory_io, raw_log_io, vault
from brain_twin.config import Config
from brain_twin.models import Memory


@dataclass
class ProcessSummary:
    total_inputs: int = 0
    daily_log_saved: int = 0
    memories_created: int = 0
    kept_as_chat: int = 0
    links_created: int = 0
    memory_ids: list[str] = field(default_factory=list)


def _suggest_links(conn: sqlite3.Connection, memory: Memory) -> list[linking.LinkSuggestion]:
    """既存のactiveなMemoryの中から、このMemoryとリンクすべき候補を探す(指示書17・28章)。
    このMemory自身はまだDBへ挿入していない時点で呼ぶこと(自己参照を避けるため、
    exclude_idではなく「まだ存在しない」ことそのもので自然に除外している)。"""
    target_created_at = datetime.fromisoformat(memory.created_at)
    candidates = [
        linking.MemoryCandidate(
            id=sig.id, topics=sig.topics, entities=sig.entities,
            created_at=datetime.fromisoformat(sig.created_at),
        )
        for sig in db.list_active_memory_signals(conn, limit=500)
    ]
    return linking.suggest_links(memory.topics, memory.entities, target_created_at, candidates)


def _apply_link_suggestions(memory: Memory, suggestions: list[linking.LinkSuggestion]) -> None:
    """frontmatter用の links(Obsidian向け、重複targetは1つにまとめる)と、
    reindexで完全に復元するための link_details の両方をMemoryへセットする。"""
    seen: list[str] = []
    for s in suggestions:
        if s.target_memory_id not in seen:
            seen.append(s.target_memory_id)
    memory.links = [linking.to_wikilink(tid) for tid in seen]
    memory.link_details = [
        {"target": s.target_memory_id, "relation_type": s.relation_type, "reason": s.reason} for s in suggestions
    ]


def add_capture(config: Config, text: str, source: str = "cli") -> str:
    """指示書39章: `add` は Raw Log へ保存するだけ(整理はしない)。"""
    vault.ensure_vault(config)
    text = text.strip()
    if not text:
        raise ValueError("空の入力は保存できません。")

    raw_log = raw_log_io.write_raw_log(config, text, source)

    with db.connect(config) as conn:
        db.upsert_raw_log(
            conn, id=raw_log.id, text=raw_log.text, source=raw_log.source,
            created_at=raw_log.created_at, file_path=raw_log.file_path, processed_at=None,
        )
        conn.commit()

    return raw_log.id


def process_all(config: Config) -> ProcessSummary:
    """未処理のRaw LogをDaily Logへ保存し、ダミー分類器でMemory候補を判定して
    Long-term Memoryを生成する(指示書3・20章)。"""
    vault.ensure_vault(config)
    summary = ProcessSummary()

    unprocessed = raw_log_io.list_raw_logs(config, unprocessed_only=True)
    summary.total_inputs = len(unprocessed)
    if not unprocessed:
        return summary

    with db.connect(config) as conn:
        touched_dates: set[str] = set()

        for raw_log in unprocessed:
            raw_log_io.append_to_daily_log(config, raw_log)
            date_str = datetime.fromisoformat(raw_log.created_at).strftime("%Y-%m-%d")
            touched_dates.add(date_str)
            summary.daily_log_saved += 1

            result = classify.classify(raw_log.text)
            if result.is_memory_worthy:
                memory = memory_io.build_memory(raw_log, result)

                # linkの候補探索は、このMemory自身をDBへ挿入する前に行う
                # (自己リンクを避けるため。_suggest_links のdocstring参照)。
                suggestions = _suggest_links(conn, memory)
                _apply_link_suggestions(memory, suggestions)

                memory = memory_io.write_memory(config, memory)
                db.upsert_memory(
                    conn,
                    id=memory.id, type=memory.type.value, created_at=memory.created_at,
                    event_date=memory.event_date, importance=memory.importance,
                    confidence=memory.confidence, source=memory.source, status=memory.status.value,
                    title=memory.title, content=memory.content, raw_log_id=memory.raw_log_id,
                    file_path=memory.file_path, topics_json=json.dumps(memory.topics, ensure_ascii=False),
                )
                db.set_memory_entities(conn, memory.id, memory.entities)

                link_created_at = datetime.now().astimezone().isoformat()
                for s in suggestions:
                    db.upsert_link(
                        conn, source_memory_id=memory.id, target_memory_id=s.target_memory_id,
                        relation_type=s.relation_type, reason=s.reason, created_at=link_created_at,
                    )
                summary.links_created += len(suggestions)

                summary.memories_created += 1
                summary.memory_ids.append(memory.id)
            else:
                summary.kept_as_chat += 1

            raw_log_io.mark_processed(config, raw_log)
            db.upsert_raw_log(
                conn, id=raw_log.id, text=raw_log.text, source=raw_log.source,
                created_at=raw_log.created_at, file_path=raw_log.file_path,
                processed_at=raw_log.processed_at,
            )

        for date_str in touched_dates:
            daily_path = config.daily_dir / f"{date_str}.md"
            db.upsert_daily_log(
                conn, date=date_str, file_path=vault.relative_to_vault(daily_path, config),
                updated_at=datetime.now().astimezone().isoformat(),
            )

        conn.commit()

    return summary


def reindex(config: Config) -> dict[str, int]:
    """VaultのMarkdownをすべて読み直し、SQLite indexを完全に作り直す
    (指示書25・34章: DBが壊れてもMarkdownから再構築できること)。"""
    vault.ensure_vault(config)
    db.reset_schema(config.db_path)

    counts = {"raw_logs": 0, "daily_logs": 0, "memories": 0, "links": 0}

    with db.connect(config) as conn:
        for raw_log in raw_log_io.list_raw_logs(config):
            db.upsert_raw_log(
                conn, id=raw_log.id, text=raw_log.text, source=raw_log.source,
                created_at=raw_log.created_at, file_path=raw_log.file_path,
                processed_at=raw_log.processed_at,
            )
            counts["raw_logs"] += 1

        if config.daily_dir.exists():
            for path in sorted(config.daily_dir.glob("*.md")):
                date_str = path.stem
                db.upsert_daily_log(
                    conn, date=date_str, file_path=vault.relative_to_vault(path, config),
                    updated_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
                )
                counts["daily_logs"] += 1

        memories = memory_io.list_all_memories(config)
        for memory in memories:
            db.upsert_memory(
                conn,
                id=memory.id, type=memory.type.value, created_at=memory.created_at,
                event_date=memory.event_date, importance=memory.importance,
                confidence=memory.confidence, source=memory.source, status=memory.status.value,
                title=memory.title, content=memory.content, raw_log_id=memory.raw_log_id,
                file_path=memory.file_path, topics_json=json.dumps(memory.topics, ensure_ascii=False),
            )
            db.set_memory_entities(conn, memory.id, memory.entities)
            counts["memories"] += 1

        # linksは全Memoryを挿入し終えてから2周目でまとめて登録する。target側のMemoryが
        # 先に存在している必要がある(外部キー制約)ため、1周目と同じループでは行えない。
        for memory in memories:
            for detail in memory.link_details:
                target = detail.get("target")
                if not target:
                    continue
                db.upsert_link(
                    conn, source_memory_id=memory.id, target_memory_id=target,
                    relation_type=detail.get("relation_type", "related"),
                    reason=detail.get("reason", ""), created_at=memory.created_at,
                )
                counts["links"] += 1

        conn.commit()

    return counts
