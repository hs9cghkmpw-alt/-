"""Raw LogのprocessedフラグがMarkdown上では書き込み済みなのに、SQLiteの raw_logs
テーブルには未反映のままになっている状態を検出し、自動的に修復する
(2回目のレビュー対応・最優先項目)。

--- 発生しうるタイミング ---

pipeline.process_all() は1件のraw_logについて、おおまかに次の順で処理する:

  1. Memory Markdownの書き込み(memory_io.write_memory、atomic write)
  2. Raw Log の processed_at 書き込み(raw_log_io.mark_processed、atomic write)
  3. SQLiteへの反映(upsert_memory / set_memory_entities / upsert_link / upsert_raw_log)
     + conn.commit()

2の直後・3の `conn.commit()` より前でプロセスが落ちると、Markdown上は
「処理済み(processed_at設定済み)」なのに、SQLiteには全く反映されていない
(コミットされていないので、そのトランザクションの変更はロールバックされる)
状態が残る。

この状態のraw_logは、raw_log_io.list_raw_logs(unprocessed_only=True) では
二度と拾われない(Markdownが「処理済み」と言っていること自体は正しいので、
これは正しい挙動)。そのため、何もしなければ `python brain.py reindex` を
手動実行するまでSQLiteの不整合(該当raw_logのMemory/Entity/Linkが一切無い)が
残り続けてしまう。

--- この修復の位置づけ ---

pipeline.process_all() の冒頭で毎回この reconcile_processed_raw_logs() を実行し、
上記の不整合を検出したら、そのraw_logについてだけ通常のprocess相当の処理
(分類の再実行 → 既存Memoryの検出・再利用 → SQLiteへの反映)をやり直すことで、
次回のprocess_all()実行時に自動的に自己修復させる(指示書25章: Markdownが正本、
SQLiteはいつでも再構築できるindexという原則を、reindex全体を再実行しなくても
保てるようにする)。

pipeline.pyから独立したモジュールにしているのは、「不整合の検出」と「1件の
raw_logをMemory化する処理」という2つの責務を、process_all()の通常フロー本体
から分離するため(pipeline.pyへ全部書き込むと、通常経路と復旧経路が混在して
読みにくくなる)。1件をMemory化する共通処理そのものはpipeline.pyとの循環import
を避けるため memory_persistence.py に切り出してあり、reconcile.pyと
pipeline.pyはともにそれを利用する側(pipeline.py → reconcile.py という依存の
向きのみで、reconcile.py → pipeline.py という逆向きの依存は作らない)。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from brain_twin import classify, db, ids, memory_io, memory_persistence, raw_log_io
from brain_twin.config import Config
from brain_twin.models import RawLog


class ReconcileError(RuntimeError):
    """Markdown上は処理済みだが、対応するMemoryファイルがVault中のどこにも
    見つからない等、自動修復では扱えない異常な状態を検出した場合に送出する。

    自動的にMemoryを再生成する(=分類結果をそのままMarkdownとして書き込み直す)
    ことは、"Memory書き込みが原本"という前提(find_existingが常に既存ファイルを
    優先する設計)を壊しかねないため行わない。ここに来るのは基本的に手動でのVault
    編集など、通常のクラッシュ・再試行では起こり得ないケースであり、自動修復せず
    人間の確認を求めるほうが安全。"""


@dataclass
class ReconcileResult:
    checked: int = 0
    repaired: int = 0
    repaired_raw_log_ids: list[str] = field(default_factory=list)


def reconcile_processed_raw_logs(config: Config, conn: sqlite3.Connection) -> ReconcileResult:
    """Markdown上processed_at済みなのにSQLite側raw_logsが未反映のraw_logを探し、
    見つかったものだけ修復する。呼び出し側(pipeline.process_all)がこの関数の
    戻り値を見てから `conn.commit()` すること(この関数自体はcommitしない)。"""
    result = ReconcileResult()

    for raw_log in raw_log_io.list_raw_logs(config):
        if raw_log.processed_at is None:
            continue  # Markdown側もまだ未処理。通常のprocess_allが後で拾う。
        result.checked += 1

        if db.get_raw_log_processed_at(conn, raw_log.id) is not None:
            continue  # 既に整合している

        _repair_one(config, conn, raw_log)
        result.repaired += 1
        result.repaired_raw_log_ids.append(raw_log.id)

    return result


def _repair_one(config: Config, conn: sqlite3.Connection, raw_log: RawLog) -> None:
    """1件のraw_logについて、通常のprocess相当の反映をやり直す。分類は決定的
    (classify.classifyは純粋関数)なので再実行してよいが、Memory本体は
    find_existingで検出した既存ファイルを常に優先し、新規には作らない
    (再計算するとクラッシュ前後で候補Memoryの状況が変わり結果が変わりうるため、
    process側の通常経路と同じ理由でここでも再利用のみを行う)。"""
    classification = classify.classify(raw_log.text)

    if classification.is_memory_worthy:
        memory_id = ids.derive_memory_id(raw_log.id)
        memory = memory_io.find_existing(config, memory_id)
        if memory is None:
            raise ReconcileError(
                f"raw_log '{raw_log.id}' はMarkdown上processed_at済みでMemory化対象だが、"
                f"対応するMemory '{memory_id}' がVault中のどこにも見つからない。"
                "自動修復の対象外(手動確認が必要)。"
            )
        memory_persistence.persist_memory(conn, memory)
        memory_persistence.persist_links(conn, memory.id, memory.link_details, fallback_created_at=memory.created_at)

    db.upsert_raw_log(
        conn, id=raw_log.id, text=raw_log.text, source=raw_log.source,
        created_at=raw_log.created_at, file_path=raw_log.file_path,
        processed_at=raw_log.processed_at,
    )
