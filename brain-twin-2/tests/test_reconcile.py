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


def test_reconcile_raises_when_markdown_says_processed_but_no_memory_file_exists(config):
    """Markdown上processed_at済み・分類はMemory化対象なのに、対応するMemoryファイルが
    Vault中のどこにも存在しない異常な状態(自動修復の対象外)では、黙って何もしない/
    でっち上げるのではなく、明示的にReconcileErrorを送出すること。"""
    vault.ensure_vault(config)
    raw_log = raw_log_io.write_raw_log(config, "決めた、これは絶対にDECISIONに分類される入力文です", "cli")
    raw_log_io.mark_processed(config, raw_log)

    with db.connect(config) as conn:
        with pytest.raises(reconcile.ReconcileError):
            reconcile.reconcile_processed_raw_logs(config, conn)
