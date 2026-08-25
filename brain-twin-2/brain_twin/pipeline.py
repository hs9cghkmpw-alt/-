"""Raw Log -> Daily Log -> (Memory) の一連の処理(指示書3・20章)。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from brain_twin import classify, db, ids, linking, memory_io, memory_persistence, raw_log_io, reconcile, vault
from brain_twin.config import Config
from brain_twin.models import ExtractedEntity, Memory, RawLog


@dataclass
class ProcessSummary:
    total_inputs: int = 0
    daily_log_saved: int = 0
    memories_created: int = 0
    kept_as_chat: int = 0
    links_created: int = 0
    memory_ids: list[str] = field(default_factory=list)
    reconciled_raw_log_ids: list[str] = field(default_factory=list)


def _suggest_links(
    conn: sqlite3.Connection, topics: list[str], entities: list[ExtractedEntity], created_at_iso: str
) -> list[linking.LinkSuggestion]:
    """既存のactiveなMemoryの中から、このMemoryとリンクすべき候補を探す(指示書17・28章)。

    候補探索そのものはSQLite側で絞り込む(同トピック/同エンティティ/時間範囲、それぞれを
    db.find_candidates_by_* へ問い合わせて和集合を取る)。件数ベースの打ち切り
    (「直近500件」等)は行わないため、古いMemoryであっても条件に一致すれば候補になれる
    (過去のレビュー指摘: 全件Python走査+直近500件という設計は、長期記憶システムとして
    古い(しかし重要な)Memoryを候補から除外してしまう問題があった)。

    呼び出しは、このMemory自身をDBへ挿入する前に行うこと(自己参照を避けるため、
    exclude_idではなく「まだ存在しない」ことそのもので自然に除外している)。"""
    target_created_at = datetime.fromisoformat(created_at_iso)
    window = linking.TEMPORAL_CLOSE_WINDOW

    candidate_ids: set[str] = set()
    candidate_ids |= db.find_candidates_by_topics(conn, topics)
    candidate_ids |= db.find_candidates_by_entities(conn, [e.name for e in entities])
    if window.total_seconds() > 0:
        window_start = (target_created_at - window).isoformat()
        window_end = (target_created_at + window).isoformat()
        candidate_ids |= db.find_candidates_by_time_range(conn, window_start, window_end)

    if not candidate_ids:
        return []

    signals = db.list_memory_signals_by_ids(conn, list(candidate_ids))
    candidates = [
        linking.MemoryCandidate(id=s.id, topics=s.topics, entities=s.entities, created_at=datetime.fromisoformat(s.created_at))
        for s in signals
    ]
    return linking.suggest_links(topics, entities, target_created_at, candidates)


def _apply_link_suggestions(memory: Memory, suggestions: list[linking.LinkSuggestion], created_at_iso: str) -> None:
    """frontmatter用の links(Obsidian向け、重複targetは1つにまとめる)と、
    reindexや再実行時の復元に使う link_details(target/relation_type/reason/strength/created_at)
    の両方をMemoryへセットする。

    created_atをここで固定して各link_detailsへ埋め込むのは、reindexが
    Memory.created_at(=Memoryの作成時刻)をlinkの生成時刻として代用してしまい、
    SQLite再構築のたびにlink.created_atが変わってしまう問題を防ぐため
    (過去のレビュー指摘)。"""
    seen: list[str] = []
    for s in suggestions:
        if s.target_memory_id not in seen:
            seen.append(s.target_memory_id)
    memory.links = [linking.to_wikilink(tid) for tid in seen]
    memory.link_details = [
        {
            "target": s.target_memory_id,
            "relation_type": s.relation_type,
            "reason": s.reason,
            "strength": s.strength,
            "created_at": created_at_iso,
        }
        for s in suggestions
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


def _process_one(config: Config, conn: sqlite3.Connection, raw_log: RawLog) -> tuple[Memory | None, int]:
    """1件のRaw Logを分類し、Memory昇格が必要なら書き込む。
    戻り値は (作成/再利用したMemory or None, そのMemoryのlink件数)。

    Memory IDはraw_log_idから決定的に導出される(ids.derive_memory_id)ため、
    このraw_logに対応するMemoryファイルが既に存在する場合(前回のprocessがMemory
    書き込み後・SQLite反映/raw_log processed前にクラッシュしたケース)は、それを
    正としてそのまま再利用し、新しいMemoryを作らない(二重生成防止。過去のレビュー
    指摘、最優先の修正項目)。このとき、links/entitiesもファイルに書かれている
    内容をそのまま使い、再計算はしない(再計算すると、クラッシュ前後で候補となる
    他のMemoryの状況が変わっている可能性があり、結果が変わって一貫性が崩れうる
    ため)。

    【4回目のレビュー対応・Phase 2最後の修正】既存Memoryの有無は、classifierを実行する**前**に
    確認する。以前はclassify.classify()を先に呼び、not is_memory_worthyなら
    既存Memoryの確認すらせずreturnしていた。これだと次のクラッシュ復旧シナリオで
    MarkdownとSQLite/processing_outcomeが矛盾する: (1)旧classifierが
    memory-worthyと判定してMemory Markdownを書いた直後、raw_logのmark_processed
    より前にクラッシュする(raw_logはまだunprocessedのまま)、(2)classifierが
    更新されnot-memory-worthyになる、(3)同じraw_logを再processすると、
    新classifierの判定だけでchatとして処理済みになってしまい、既に存在する
    Memory Markdownが見捨てられる(SQLiteにも反映されず、processing_outcomeは
    "chat"なのにMemory Markdownは実在する、という矛盾状態が生まれる)。
    reconcile.pyと同じ原則(過去に確定したMarkdownを現在のclassifierで再解釈
    しない)を、unprocessedなraw_logの通常処理経路にも適用し、既存Memoryが
    見つかった場合はclassifierを一切呼ばない。"""
    memory_id = ids.derive_memory_id(raw_log.id)
    existing = memory_io.find_existing(config, memory_id)

    if existing is not None:
        memory = existing
    else:
        result = classify.classify(raw_log.text)
        if not result.is_memory_worthy:
            return None, 0

        memory = memory_io.build_memory(raw_log, result)
        suggestions = _suggest_links(conn, result.topics, result.entities, memory.created_at)
        _apply_link_suggestions(memory, suggestions, datetime.now().astimezone().isoformat())
        memory = memory_io.write_memory(config, memory)

    memory_persistence.persist_memory(conn, memory)
    memory_persistence.persist_links(conn, memory.id, memory.link_details, fallback_created_at=memory.created_at)

    return memory, len(memory.link_details)


def process_all(config: Config) -> ProcessSummary:
    """未処理のRaw LogをDaily Logへ保存し、ダミー分類器でMemory候補を判定して
    Long-term Memoryを生成する(指示書3・20章)。

    本体の処理に入る前に、必ず reconcile.reconcile_processed_raw_logs() を実行する
    (レビュー対応・最優先項目)。Markdown上はprocessed_at済みなのにSQLite側が
    未反映のまま残っているraw_logがあれば、ここで検出して自己修復する。
    「未処理のraw_logが0件だから何もしない」という早期returnをこのreconcileより
    前に置いてしまうと、そもそもreconcileが実行されなくなってしまう
    (不整合があるraw_log自体はMarkdown上「処理済み」なので unprocessed_only=True
    には含まれず、"何もすることがない"と誤認してしまうため)。そのためreconcileは
    DB接続を開いた直後、unprocessedの判定より先に行う。"""
    vault.ensure_vault(config)
    summary = ProcessSummary()

    with db.connect(config) as conn:
        reconcile_result = reconcile.reconcile_processed_raw_logs(config, conn)
        conn.commit()
        summary.reconciled_raw_log_ids = reconcile_result.repaired_raw_log_ids

        unprocessed = raw_log_io.list_raw_logs(config, unprocessed_only=True)
        summary.total_inputs = len(unprocessed)
        if not unprocessed:
            return summary

        touched_dates: set[str] = set()

        for raw_log in unprocessed:
            raw_log_io.append_to_daily_log(config, raw_log)
            date_str = datetime.fromisoformat(raw_log.created_at).strftime("%Y-%m-%d")
            touched_dates.add(date_str)
            summary.daily_log_saved += 1

            memory, link_count = _process_one(config, conn, raw_log)
            if memory is not None:
                summary.memories_created += 1
                summary.memory_ids.append(memory.id)
                summary.links_created += link_count
                outcome = raw_log_io.PROCESSING_OUTCOME_MEMORY
                outcome_memory_id = memory.id
            else:
                summary.kept_as_chat += 1
                outcome = raw_log_io.PROCESSING_OUTCOME_CHAT
                outcome_memory_id = None

            raw_log_io.mark_processed(config, raw_log, processing_outcome=outcome, memory_id=outcome_memory_id)
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
            memory_persistence.persist_memory(conn, memory)
            counts["memories"] += 1

        # linksは全Memoryを挿入し終えてから2周目でまとめて登録する。target側のMemoryが
        # 先に存在している必要がある(外部キー制約)ため、1周目と同じループでは行えない。
        for memory in memories:
            memory_persistence.persist_links(conn, memory.id, memory.link_details, fallback_created_at=memory.created_at)
            counts["links"] += len(memory.link_details)

        conn.commit()

    return counts
