"""Raw LogのprocessedフラグがMarkdown上では書き込み済みなのに、SQLiteの raw_logs
テーブル(および対応するMemory/daily_logs)には未反映のままになっている状態を検出し、
自動的に修復する(2回目のレビュー対応・最優先項目。3回目のレビューでさらに補強)。

--- 発生しうるタイミング ---

pipeline.process_all() は1件のraw_logについて、おおまかに次の順で処理する:

  1. Daily Log Markdownへの追記(raw_log_io.append_to_daily_log、atomic write)
  2. Memory Markdownの書き込み(memory_io.write_memory、atomic write。
     Memory化対象の場合のみ)
  3. Raw Log の processed_at + processing_outcome 書き込み(raw_log_io.mark_processed、
     atomic write)
  4. SQLiteへの反映(upsert_memory / set_memory_entities / upsert_link /
     upsert_raw_log / upsert_daily_log) + conn.commit()

3の直後・4の `conn.commit()` より前でプロセスが落ちると、Markdown上は
「処理済み」なのに、SQLiteには全く反映されていない(コミットされていないので、
そのトランザクションの変更はロールバックされる)状態が残る。raw_logsだけでなく、
1で書かれたDaily Log Markdownに対応するdaily_logs行、2で書かれたMemory
Markdownに対応するmemories/memory_entities/links行も同様に失われる。

この状態のraw_logは、raw_log_io.list_raw_logs(unprocessed_only=True) では
二度と拾われない(Markdownが「処理済み」と言っていること自体は正しいので、
これは正しい挙動)。そのため、何もしなければ `python brain.py reindex` を
手動実行するまでSQLiteの不整合が残り続けてしまう。

--- classifierを再実行しない(3回目のレビュー対応) ---

以前は不整合を見つけたraw_logについて classify.classify(raw_log.text) を
再実行し、「現在の」分類結果でMemory化対象だったかどうかを判断していた。
これは、将来classifierの実装が変わった場合に過去の処理結果を誤って
再解釈してしまう(指示書25章: 過去に確定した処理結果はMarkdownが正本であり、
現在の実装で再解釈しない、という原則に反する)。例えば旧classifierが
memory-worthyと判定してMemory Markdownを書いた直後にクラッシュした場合、
新classifierがnot-memory-worthyと判定するようになっていると、既存の
Memory Markdownを復元し損なう。逆に旧classifierがnot-memory-worthyと判定して
正常にchat扱いで処理済みになったraw_logを、新classifierがmemory-worthyだと
判定するようになっていると、「Memoryが存在しない異常事態」と誤検出しうる。

そこでこのモジュールはclassifierを一切呼ばない。代わりに:

  1. raw_log_idから決定的に導出されるmemory_id(ids.derive_memory_id)で
     Vault全体を検索し(memory_io.find_existing)、既存Memory Markdownが
     見つかれば、それが「当時Memory化された」ことの動かぬ証拠なので、
     現在のclassifierの判断に関係なくそれを正としてSQLiteへ復元する。
  2. Memoryが見つからない場合は、raw_log自身のfrontmatterに記録されている
     processing_outcome(raw_log_io.mark_processedが書き込む、当時の実際の
     処理結果)を見る。"memory"と記録されているのにMemoryが見つからないのは
     矛盾しており、自動修復できない異常事態としてReconcileErrorを送出する。
     "chat"、またはこのメタデータ自体が無い(このフィールドが導入される前に
     処理された旧形式のraw log)場合は、Memoryが存在しないことをそのまま
     正常な状態として受け入れる(安全側のフォールバック。旧形式のraw logは
     当時chatだった可能性を考慮し、勝手にMemoryを生成することも
     ReconcileErrorにすることもしない)。

--- この修復の位置づけ ---

pipeline.process_all() の冒頭で毎回この reconcile_processed_raw_logs() を実行し、
上記の不整合を検出したら、そのraw_logについてだけSQLiteへの反映をやり直すことで、
次回のprocess_all()実行時に自動的に自己修復させる(指示書25章: Markdownが正本、
SQLiteはいつでも再構築できるindexという原則を、reindex全体を再実行しなくても
保てるようにする)。

pipeline.pyから独立したモジュールにしているのは、「不整合の検出」と「1件の
raw_logをSQLiteへ反映し直す処理」という2つの責務を、process_all()の通常フロー
本体から分離するため(pipeline.pyへ全部書き込むと、通常経路と復旧経路が混在して
読みにくくなる)。1件のMemoryをSQLiteへ反映する共通処理そのものはpipeline.pyとの
循環importを避けるため memory_persistence.py に切り出してあり、reconcile.pyと
pipeline.pyはともにそれを利用する側(pipeline.py → reconcile.py という依存の
向きのみで、reconcile.py → pipeline.py という逆向きの依存は作らない)。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from brain_twin import db, ids, memory_io, memory_persistence, raw_log_io, vault
from brain_twin.config import Config
from brain_twin.models import RawLog


class ReconcileError(RuntimeError):
    """raw_logのfrontmatterはprocessing_outcome="memory"(当時Memory化された)と
    記録しているのに、対応するMemoryファイルがVault中のどこにも見つからない、
    という自動修復では扱えない異常な状態を検出した場合に送出する。

    自動的にMemoryを再生成する(=現在のclassifierの結果をそのままMarkdownとして
    書き込み直す)ことは、"Memory書き込みが原本"という前提(find_existingが常に
    既存ファイルを優先する設計)を壊しかねないため行わない。ここに来るのは基本的に
    手動でのVault編集など、通常のクラッシュ・再試行では起こり得ないケースであり、
    自動修復せず人間の確認を求めるほうが安全。"""


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
    """1件のraw_logについて、SQLiteへの反映をやり直す。classifierは呼ばない
    (モジュールdocstring参照)。"""
    memory_id = ids.derive_memory_id(raw_log.id)
    memory = memory_io.find_existing(config, memory_id)

    if memory is not None:
        # Memory Markdownが実在する = 当時Memory化されたことの動かぬ証拠。
        # 現在のclassifierがどう判断するかに関わらず、これを正として復元する。
        memory_persistence.persist_memory(conn, memory)
        memory_persistence.persist_links(conn, memory.id, memory.link_details, fallback_created_at=memory.created_at)
    elif raw_log.processing_outcome == raw_log_io.PROCESSING_OUTCOME_MEMORY:
        raise ReconcileError(
            f"raw_log '{raw_log.id}' はMarkdown上processing_outcome='memory'として"
            f"処理済みだが、対応するMemory '{memory_id}' がVault中のどこにも"
            "見つからない。自動修復の対象外(手動確認が必要)。"
        )
    # else: processing_outcomeが"chat"、またはこのメタデータが無い旧形式のraw log。
    # どちらの場合もMemoryが存在しないのは正常(または安全側のフォールバック)なので、
    # 何もしない。

    db.upsert_raw_log(
        conn, id=raw_log.id, text=raw_log.text, source=raw_log.source,
        created_at=raw_log.created_at, file_path=raw_log.file_path,
        processed_at=raw_log.processed_at,
    )
    _reconcile_daily_log(config, conn, raw_log)


def _reconcile_daily_log(config: Config, conn: sqlite3.Connection, raw_log: RawLog) -> None:
    """raw_logの日付に対応するDaily MarkdownがVaultに存在すれば、SQLite側の
    daily_logs行も復元する(無ければ挿入、有ればfile_path/updated_atを最新化)。

    通常processではraw_logごとにDaily Log Markdownへの追記がSQLite反映より先に
    行われるため、raw_logs/memoriesと同じ理由でdaily_logs行だけが欠落しうる。
    daily_logsへのupsertは日付単位で冪等なので、同じ日付のraw_logが複数
    修復されても安全に繰り返し呼べる。"""
    date_str = datetime.fromisoformat(raw_log.created_at).strftime("%Y-%m-%d")
    daily_path = config.daily_dir / f"{date_str}.md"
    if not daily_path.exists():
        return
    db.upsert_daily_log(
        conn, date=date_str,
        file_path=vault.relative_to_vault(daily_path, config),
        updated_at=datetime.fromtimestamp(daily_path.stat().st_mtime).astimezone().isoformat(),
    )
