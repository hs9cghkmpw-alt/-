import pytest

from brain_twin import classify, db, memory_io, pipeline, raw_log_io, reconcile, vault


def test_reconcile_is_noop_when_nothing_processed(config):
    pipeline.add_capture(config, "まだ処理していない入力です")

    with db.connect(config) as conn:
        result = reconcile.reconcile_processed_raw_logs(config, conn)
        conn.commit()

    assert result.checked == 0
    assert result.repaired == 0
    assert result.repaired_raw_log_ids == []


def test_reconcile_is_noop_when_already_consistent(config):
    pipeline.add_capture(config, "十分に長い、通常どおり最後まで処理される入力文です")
    pipeline.process_all(config)

    with db.connect(config) as conn:
        result = reconcile.reconcile_processed_raw_logs(config, conn)
        conn.commit()

    assert result.checked == 1
    assert result.repaired == 0


def test_reconcile_repairs_raw_log_row_missing_from_sqlite(config):
    """SQLite側のraw_logs行そのものが無い(commitされなかった)状態を、
    reindexを使わずreconcileだけで直せることを確認する。Memory Markdownは
    (実際のクラッシュ窓と同じく)先に書き込まれている想定で用意しておく。"""
    vault.ensure_vault(config)
    raw_log = raw_log_io.write_raw_log(config, "十分に長い、reconcileの単体テスト用の入力文です", "cli")
    classification = classify.classify(raw_log.text)
    assert classification.is_memory_worthy
    memory_io.write_memory(config, memory_io.build_memory(raw_log, classification))

    # add_capture相当: raw_logs行自体はprocessed_at=NULLの状態で先にSQLiteへ入っている
    # (実際のクラッシュ窓でも、captureした時点でこの行は既に存在する)。
    with db.connect(config) as conn:
        db.upsert_raw_log(
            conn, id=raw_log.id, text=raw_log.text, source=raw_log.source,
            created_at=raw_log.created_at, file_path=raw_log.file_path, processed_at=None,
        )
        conn.commit()

    raw_log_io.mark_processed(config, raw_log)  # Markdown上はprocessed_at済みにする

    with db.connect(config) as conn:
        # processed_atの更新だけがcommitされなかった状態を再現する。
        assert db.get_raw_log_processed_at(conn, raw_log.id) is None

        result = reconcile.reconcile_processed_raw_logs(config, conn)
        conn.commit()

    assert result.repaired == 1
    assert result.repaired_raw_log_ids == [raw_log.id]

    memories = memory_io.list_all_memories(config)
    assert len(memories) == 1
    assert memories[0].raw_log_id == raw_log.id

    with db.connect(config) as conn:
        assert db.get_raw_log_processed_at(conn, raw_log.id) == raw_log.processed_at
        assert conn.execute("SELECT COUNT(*) FROM memories WHERE raw_log_id = ?", (raw_log.id,)).fetchone()[0] == 1


# ---- レビュー対応(3回目): reconcileはclassifierを再実行せず、raw_log自身の
# ---- processing_outcomeメタデータとMemory Markdownの実在だけで判断する ----


def test_reconcile_raises_when_processing_outcome_memory_but_memory_file_missing(config):
    """raw_log自身が「当時Memory化された」(processing_outcome="memory")と
    記録しているのに、対応するMemoryファイルがVault中のどこにも存在しない異常な
    状態(自動修復の対象外)では、黙って何もしない/でっち上げるのではなく、
    明示的にReconcileErrorを送出すること。"""
    vault.ensure_vault(config)
    raw_log = raw_log_io.write_raw_log(config, "決めた、これは絶対にDECISIONに分類される入力文です", "cli")
    raw_log_io.mark_processed(
        config, raw_log,
        processing_outcome=raw_log_io.PROCESSING_OUTCOME_MEMORY,
        memory_id="mem_20260824_999",
    )

    with db.connect(config) as conn:
        with pytest.raises(reconcile.ReconcileError):
            reconcile.reconcile_processed_raw_logs(config, conn)


def test_reconcile_does_not_raise_for_legacy_raw_log_without_outcome_metadata_and_no_memory(config):
    """processing_outcomeメタデータが存在しない旧形式のraw log(このフィールドが
    導入される前に処理されたもの)で、かつ対応するMemoryファイルも無い場合は、
    「当時chatだった可能性」を考慮して安全側で受け入れ、ReconcileErrorを出したり
    Memoryを勝手に生成したりしないこと。"""
    vault.ensure_vault(config)
    raw_log = raw_log_io.write_raw_log(config, "十分に長いが、あえてMemoryを用意しない入力文です", "cli")
    raw_log_io.mark_processed(config, raw_log)  # processing_outcomeを指定しない = 旧形式を模す
    assert raw_log.processing_outcome is None

    with db.connect(config) as conn:
        result = reconcile.reconcile_processed_raw_logs(config, conn)
        conn.commit()

    assert result.repaired == 1
    assert memory_io.list_all_memories(config) == []
    with db.connect(config) as conn:
        assert db.get_raw_log_processed_at(conn, raw_log.id) == raw_log.processed_at
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_reconcile_does_not_raise_when_processing_outcome_is_chat(config):
    """processing_outcome="chat"(当時Memory化されなかったことが明示的に記録されて
    いる)場合も、Memoryが存在しないのは正常な状態としてReconcileErrorを出さない
    こと。"""
    vault.ensure_vault(config)
    raw_log = raw_log_io.write_raw_log(config, "みじかい", "cli")
    raw_log_io.mark_processed(config, raw_log, processing_outcome=raw_log_io.PROCESSING_OUTCOME_CHAT)

    with db.connect(config) as conn:
        result = reconcile.reconcile_processed_raw_logs(config, conn)
        conn.commit()

    assert result.repaired == 1
    assert memory_io.list_all_memories(config) == []
