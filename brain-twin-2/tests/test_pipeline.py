import contextlib
import dataclasses
from datetime import datetime

import pytest

from brain_twin import classify, db, memory_io, pipeline, raw_log_io, search, vault
from brain_twin.models import MemoryType


def test_add_writes_raw_log_and_db_row(config):
    raw_id = pipeline.add_capture(config, "今日はBrain Twinの設計について考えた")

    raw_path = config.inbox_dir / f"{raw_id}.md"
    assert raw_path.exists()

    with db.connect(config) as conn:
        row = conn.execute("SELECT id, text, processed_at FROM raw_logs WHERE id=?", (raw_id,)).fetchone()
    assert row is not None
    assert row[1] == "今日はBrain Twinの設計について考えた"
    assert row[2] is None  # まだprocessしていない


def test_add_rejects_empty_input(config):
    import pytest

    with pytest.raises(ValueError):
        pipeline.add_capture(config, "   ")


def test_process_creates_daily_log_and_memory(config):
    pipeline.add_capture(config, "今日はBrain Twinの設計について考えた")
    summary = pipeline.process_all(config)

    assert summary.total_inputs == 1
    assert summary.daily_log_saved == 1
    assert summary.memories_created == 1

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    daily_path = config.daily_dir / f"{today}.md"
    assert daily_path.exists()
    assert "Brain Twinの設計について考えた" in daily_path.read_text(encoding="utf-8")

    memories = memory_io.list_all_memories(config)
    assert len(memories) == 1
    assert memories[0].content == "今日はBrain Twinの設計について考えた"
    assert memories[0].raw_log_id is not None


def test_process_keeps_casual_input_out_of_memory(config):
    pipeline.add_capture(config, "ナイキのカバンだ")
    summary = pipeline.process_all(config)

    assert summary.memories_created == 0
    assert summary.kept_as_chat == 1
    assert memory_io.list_all_memories(config) == []

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    daily_path = config.daily_dir / f"{today}.md"
    assert "ナイキのカバンだ" in daily_path.read_text(encoding="utf-8")  # Daily Logには残る


def test_process_is_idempotent(config):
    pipeline.add_capture(config, "今日はBrain Twinの設計について考えた")
    pipeline.process_all(config)
    second_summary = pipeline.process_all(config)

    assert second_summary.total_inputs == 0  # 既に処理済みなので対象なし
    assert len(memory_io.list_all_memories(config)) == 1  # 重複生成されない


def test_multiple_captures_same_day_share_one_daily_log(config):
    pipeline.add_capture(config, "1件目の入力です、それなりの長さがある文章")
    pipeline.add_capture(config, "2件目の入力です、それなりの長さがある文章")
    pipeline.process_all(config)

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    daily_files = list(config.daily_dir.glob("*.md"))
    assert len(daily_files) == 1
    text = daily_files[0].read_text(encoding="utf-8")
    assert "1件目の入力です" in text
    assert "2件目の入力です" in text


def test_search_finds_processed_memory(config):
    pipeline.add_capture(config, "病院いったら診断書お願いしなきゃ")
    pipeline.process_all(config)

    results = search.search_with_config(config, "診断書")
    assert len(results) == 1
    assert results[0].content == "病院いったら診断書お願いしなきゃ"


def test_search_below_min_length_returns_empty(config):
    pipeline.add_capture(config, "病院いったら診断書お願いしなきゃ")
    pipeline.process_all(config)

    assert search.search_with_config(config, "病院") == []  # 2文字はtrigramの実用下限未満


def test_search_excludes_unrelated_memory(config):
    pipeline.add_capture(config, "病院いったら診断書お願いしなきゃ")
    pipeline.add_capture(config, "クラルティに応募することにした")
    pipeline.process_all(config)

    results = search.search_with_config(config, "診断書")
    assert len(results) == 1
    assert all("クラルティ" not in r.content for r in results)


def test_reindex_rebuilds_identical_data_from_markdown(config):
    pipeline.add_capture(config, "今日はBrain Twinの設計について考えた")
    pipeline.add_capture(config, "ナイキのカバンだ")
    pipeline.process_all(config)

    before = memory_io.list_all_memories(config)
    raw_logs_before = raw_log_io.list_raw_logs(config)

    # SQLite indexを完全に消してから再構築する(指示書25・34章)。
    config.db_path.unlink()
    counts = pipeline.reindex(config)

    assert counts["raw_logs"] == len(raw_logs_before)
    assert counts["memories"] == len(before)

    results = search.search_with_config(config, "設計について")
    assert len(results) == 1
    assert results[0].content == "今日はBrain Twinの設計について考えた"


def test_ensure_vault_is_idempotent(config):
    vault.ensure_vault(config)
    vault.ensure_vault(config)  # 2回目もエラーにならない
    assert config.memory_dir.exists()
    assert (config.system_dir / "README.md").exists()


# ---- Phase 2: Entity Extraction / Link generation ----


def test_process_extracts_entities_into_memory_frontmatter(config):
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")
    pipeline.process_all(config)

    memories = memory_io.list_all_memories(config)
    assert len(memories) == 1
    assert "ナイキ" in memories[0].entities


def test_process_links_memories_sharing_an_entity(config):
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")
    pipeline.process_all(config)
    pipeline.add_capture(config, "今日はナイキの本社について調べていた、面白い会社だと思う")
    summary = pipeline.process_all(config)

    assert summary.links_created >= 1

    memories = {m.title: m for m in memory_io.list_all_memories(config)}
    second = [m for m in memories.values() if "本社" in m.content][0]
    first = [m for m in memories.values() if "ランニングシューズ" in m.content][0]

    assert f"[[{first.id}]]" in second.links
    relation_types = {d["relation_type"] for d in second.link_details if d["target"] == first.id}
    assert "same_entity" in relation_types
    assert all("strength" in d for d in second.link_details)

    with db.connect(config) as conn:
        stored = conn.execute(
            "SELECT strength FROM links WHERE source_memory_id = ?", (second.id,)
        ).fetchall()
    assert sorted(row[0] for row in stored) == sorted(d["strength"] for d in second.link_details)


def test_process_does_not_link_unrelated_memories(config):
    pipeline.add_capture(config, "病院いったら診断書お願いしなきゃ")
    pipeline.process_all(config)

    with db.connect(config) as conn:
        memory_count_before = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert memory_count_before == 1

    # 2件目はトピック・エンティティともに無関係。時間差も指示書上「近い」とは扱われない
    # (linking.TEMPORAL_CLOSE_WINDOW=30分)ため、リンクは作られないはず。テスト実行は
    # 一瞬で終わるため、窓を意図的に負の値にして「常に窓の外」を再現する。
    from datetime import timedelta

    from brain_twin import linking

    original_window = linking.TEMPORAL_CLOSE_WINDOW
    linking.TEMPORAL_CLOSE_WINDOW = timedelta(seconds=-1)
    try:
        pipeline.add_capture(config, "クラルティに応募することにした")
        summary = pipeline.process_all(config)
    finally:
        linking.TEMPORAL_CLOSE_WINDOW = original_window

    assert summary.links_created == 0


def test_entities_persisted_in_sqlite_after_process(config):
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")
    pipeline.process_all(config)

    memories = memory_io.list_all_memories(config)
    memory_id = memories[0].id

    with db.connect(config) as conn:
        entities = db.entities_for_memories(conn, [memory_id])[memory_id]
    assert "ナイキ" in [e.name for e in entities]


_LINKS_QUERY = (
    "SELECT source_memory_id, target_memory_id, relation_type, reason, strength, created_at "
    "FROM links ORDER BY 1, 2, 3"
)
_ENTITIES_QUERY = (
    "SELECT me.memory_id, e.name, me.confidence, me.method FROM memory_entities me "
    "JOIN entities e ON e.id = me.entity_id ORDER BY 1, 2"
)


def test_reindex_reproduces_links_and_entities_from_markdown(config):
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")
    pipeline.process_all(config)
    pipeline.add_capture(config, "今日はナイキの本社について調べていた、面白い会社だと思う")
    pipeline.process_all(config)

    with db.connect(config) as conn:
        links_before = sorted(conn.execute(_LINKS_QUERY).fetchall())
        entities_before = sorted(conn.execute(_ENTITIES_QUERY).fetchall())

    assert links_before  # このテストの前提(実際にリンクが生成されていること)を明示する

    config.db_path.unlink()
    counts = pipeline.reindex(config)
    assert counts["links"] == len(links_before)

    with db.connect(config) as conn:
        links_after = sorted(conn.execute(_LINKS_QUERY).fetchall())
        entities_after = sorted(conn.execute(_ENTITIES_QUERY).fetchall())

    # source/target/relation_type/reason/strength/created_atが完全一致することを確認する
    # (レビュー対応: 以前はreindexがMemory.created_atで代用し、link自体の生成時刻を
    # 失っていた)。
    assert links_after == links_before
    assert entities_after == entities_before


def test_reindex_falls_back_to_memory_created_at_for_link_details_without_created_at(config):
    """このレビュー修正より前に書かれたMemoryファイル(link_detailsにcreated_atを
    持たない)でも、reindexが壊れずMemory.created_atを代用して復元できること
    (後方互換性)。"""
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")
    pipeline.process_all(config)
    pipeline.add_capture(config, "今日はナイキの本社について調べていた、面白い会社だと思う")
    pipeline.process_all(config)

    memories = memory_io.list_all_memories(config)
    second = [m for m in memories if "本社" in m.content][0]
    assert second.link_details  # 前提: リンクがある

    # 古いバージョンの出力を模して、created_atキーを取り除いた状態でファイルを書き戻す。
    for detail in second.link_details:
        detail.pop("created_at", None)
    memory_io.write_memory(config, second)

    counts = pipeline.reindex(config)
    assert counts["links"] == len(second.link_details)

    with db.connect(config) as conn:
        rows = conn.execute(
            "SELECT created_at FROM links WHERE source_memory_id = ?", (second.id,)
        ).fetchall()
    assert all(r[0] == second.created_at for r in rows)


def test_search_result_includes_entities(config):
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")
    pipeline.process_all(config)

    results = search.search_with_config(config, "ランニングシューズ")
    assert len(results) == 1
    assert "ナイキ" in results[0].entities


def test_old_memory_is_still_a_link_candidate_via_shared_topic(config):
    """レビュー対応3: 「直近500件」のような件数ベースの打ち切りを撤廃したことの
    end-to-end確認。かなり昔のMemoryでも、topicが一致すれば新しいMemoryから
    リンクされる。"""
    pipeline.add_capture(config, "3年前に仕事でとても大変なプロジェクトがあった")
    pipeline.process_all(config)

    old_memory = memory_io.list_all_memories(config)[0]
    old_memory.created_at = "2020-01-01T00:00:00+00:00"
    old_memory.event_date = "2020-01-01"
    memory_io.write_memory(config, old_memory)
    # Markdownを書き換えた後、SQLite側にもその内容を反映させる(Markdownが正本)。
    reindex_counts = pipeline.reindex(config)
    assert reindex_counts["memories"] == 1

    pipeline.add_capture(config, "今日も仕事でプロジェクトの続きをやった")
    summary = pipeline.process_all(config)

    assert summary.links_created >= 1
    memories = memory_io.list_all_memories(config)
    new_memory = [m for m in memories if m.id != old_memory.id][0]
    assert any(d["target"] == old_memory.id for d in new_memory.link_details)


# ---- レビュー対応5(最優先): process途中失敗からの回復と冪等性 ----


def test_process_recovers_from_crash_after_memory_write_without_duplicating(config, monkeypatch):
    """Memory Markdown書き込み後、SQLiteへの反映(db.upsert_memory)前にプロセスが
    落ちたケースを再現する。再実行しても同じMemoryが1件だけ存在し、raw_logは
    正しくprocessedになり、SQLiteとMarkdownの内容が一致することを確認する。

    本番コードに例外注入用のフック等は加えず、db.upsert_memory をmonkeypatchして
    最初の1回だけ例外を送出させる(以降は本来の実装へ委譲する)ことで再現する。
    """
    pipeline.add_capture(config, "十分に長い、意図的にクラッシュさせるテスト用の入力文です")

    real_upsert_memory = db.upsert_memory
    call_state = {"count": 0}

    def flaky_upsert_memory(conn, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError("simulated crash right after the memory markdown file was written")
        return real_upsert_memory(conn, **kwargs)

    monkeypatch.setattr(db, "upsert_memory", flaky_upsert_memory)

    with pytest.raises(RuntimeError):
        pipeline.process_all(config)

    # クラッシュ直後: Markdownファイルは書かれてしまっているが、raw_logは
    # まだ未処理のまま残っている(commitされていない)。
    memories_after_crash = memory_io.list_all_memories(config)
    assert len(memories_after_crash) == 1
    raw_logs_after_crash = raw_log_io.list_raw_logs(config)
    assert raw_logs_after_crash[0].processed_at is None

    # 再実行: 同じraw_logが再度処理対象になっても、既存のMemoryファイルを検出して
    # 再利用し、新しいMemoryを重複生成しない(id生成がraw_log_idから決定的なため)。
    summary = pipeline.process_all(config)

    memories_after_retry = memory_io.list_all_memories(config)
    assert len(memories_after_retry) == 1
    assert memories_after_retry[0].id == memories_after_crash[0].id
    assert summary.memories_created == 1

    raw_logs_after_retry = raw_log_io.list_raw_logs(config)
    assert raw_logs_after_retry[0].processed_at is not None

    with db.connect(config) as conn:
        db_memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        db_memory = conn.execute("SELECT id, content FROM memories").fetchone()
    assert db_memory_count == 1
    assert db_memory[0] == memories_after_retry[0].id
    assert db_memory[1] == memories_after_retry[0].content


def test_process_recovers_from_crash_before_raw_log_marked_processed(config, monkeypatch):
    """SQLite反映まで完了したが、raw_logがprocessedになる直前でクラッシュしたケース。
    再実行時、find_existingが既存Memoryを検出して再利用するため、これも重複生成
    しないことを確認する(_persist_links等が2回目もエラーなく冪等に完了すること)。"""
    pipeline.add_capture(config, "十分に長い、意図的にクラッシュさせるテスト用の入力文です")

    real_mark_processed = raw_log_io.mark_processed
    call_state = {"count": 0}

    def flaky_mark_processed(config_arg, raw_log_arg, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError("simulated crash right before marking the raw log processed")
        return real_mark_processed(config_arg, raw_log_arg, **kwargs)

    monkeypatch.setattr(raw_log_io, "mark_processed", flaky_mark_processed)

    with pytest.raises(RuntimeError):
        pipeline.process_all(config)

    assert len(memory_io.list_all_memories(config)) == 1

    summary = pipeline.process_all(config)
    assert summary.memories_created == 1
    assert len(memory_io.list_all_memories(config)) == 1

    raw_logs = raw_log_io.list_raw_logs(config)
    assert raw_logs[0].processed_at is not None


def test_process_recovers_from_crash_with_classification_change_no_duplicate_across_types(config, monkeypatch):
    """レビュー対応(2回目)最優先事項: 1回目の分類でTHOUGHTと判定されMemory Markdownが
    書き込まれた直後(SQLiteへのdb.upsert_memory反映前)にクラッシュしたケースを再現する。
    再実行時に分類ロジック自体が変わっていて(例: 同じ入力が今度はDECISIONと判定される)
    ても、find_existingがVault全体(type別フォルダすべて)から既存ファイルを見つけて
    再利用するため、新しいtype(Decisions)のフォルダに重複したMemoryを作らないことを
    確認する。元のMarkdown(THOUGHTとして書かれたもの)が正として再利用されること、
    Vault全体でMemoryが1件だけであることの両方を見る。"""
    pipeline.add_capture(config, "十分に長い、意図的にクラッシュさせるテスト用の入力文です")

    real_classify = classify.classify

    def thought_classification(text):
        return dataclasses.replace(real_classify(text), type=MemoryType.THOUGHT, is_memory_worthy=True)

    monkeypatch.setattr(classify, "classify", thought_classification)

    real_upsert_memory = db.upsert_memory
    call_state = {"count": 0}

    def flaky_upsert_memory(conn, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError("simulated crash right after the memory markdown file was written")
        return real_upsert_memory(conn, **kwargs)

    monkeypatch.setattr(db, "upsert_memory", flaky_upsert_memory)

    with pytest.raises(RuntimeError):
        pipeline.process_all(config)

    memories_after_crash = memory_io.list_all_memories(config)
    assert len(memories_after_crash) == 1
    assert memories_after_crash[0].type == MemoryType.THOUGHT
    original_id = memories_after_crash[0].id

    # 「再実行時には分類ロジック自体が変わっていた」を再現する: 同じ入力が今度はDECISIONに
    # 分類される。
    def decision_classification(text):
        return dataclasses.replace(real_classify(text), type=MemoryType.DECISION, is_memory_worthy=True)

    monkeypatch.setattr(classify, "classify", decision_classification)

    summary = pipeline.process_all(config)

    memories_after_retry = memory_io.list_all_memories(config)
    assert len(memories_after_retry) == 1  # Vault全体で重複が作られていない
    assert memories_after_retry[0].id == original_id
    assert memories_after_retry[0].type == MemoryType.THOUGHT  # 元のMarkdownが正として再利用される
    assert summary.memories_created == 1

    decision_folder = config.vault_dir / "20_Memory" / "Decisions"
    assert list(decision_folder.glob("mem_*.md")) == []  # 新typeのフォルダには複製が無い

    with db.connect(config) as conn:
        db_memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert db_memory_count == 1


# ---- レビュー対応(2回目・最優先): processed_atはMarkdownに書けたがSQLite commitが
# ---- 一度も起きなかったraw_logの自動reconcile ----


def test_process_all_auto_reconciles_raw_log_processed_in_markdown_but_never_committed_to_sqlite(config, monkeypatch):
    """再現するクラッシュ窓: Raw Logのprocessed_atはMarkdownへ正常に書き込まれた
    (raw_log_io.mark_processed成功)のに、その同じprocess_all()呼び出しの
    conn.commit()が一度も実行されない(直前でクラッシュした)ケース。

    Markdownは「処理済み」と言っているため、以後 list_raw_logs(unprocessed_only=True)
    はこのraw_logを二度と拾わない。それでもSQLiteには何も反映されていないままなので、
    放置すると reindex を手動実行するまで不整合が残り続けてしまう。次回の
    process_all() 呼び出しの冒頭で自動的にこれを検出・修復できることを、
    以下の手順で確認する。

    1. raw logを追加する
    2. processする(このテストでは意図的にクラッシュさせる)
    3. Memory MarkdownおよびDaily Log Markdownが書き込まれていることを確認する
    4. Raw Logのprocessed_atがMarkdownへ書き込まれていることを確認する
    5. SQLiteへのconn.commit()の直前で例外が発生する(monkeypatchで再現)
    6. processが例外で終了する
    7. 「再起動後の次回実行」を模して、もう一度process_allを呼ぶ
    8. 通常運用の一部として自動的に回復する(reconcileが自動実行される)
    9. Memoryがちょうど1件だけ存在する
    10. Raw Logがprocessed済みとして扱われている
    11. SQLite側にMemory/Entity/Link/daily_logsの行が正しく存在する
        (3回目のレビュー対応: daily_logsもraw_logs/memoriesと同じクラッシュ窓で
        失われうるため、reconcileの対象に含めた)
    12. MarkdownとSQLiteの内容が一致する

    本番コードに例外注入用のフックは加えない。sqlite3.Connection自体はイミュータブルな
    拡張型でメソッドをmonkeypatchできないため、db.connect()が返す接続をそのまま使う
    代わりに、commit()だけを差し替えて残りは実際の接続へ委譲する薄いプロキシを
    monkeypatch.setattr(db, "connect", ...)で被せる。raw_log_io.mark_processedが
    実際に成功した後の最初のcommit()呼び出しだけを狙って例外を送出する
    (以降は本来のcommitへ委譲する)ことで、「processed_atは書けたがcommitはされて
    いない」という狙った状態そのものを再現する。
    """
    pipeline.add_capture(config, "ナイキの新しいランニングシューズを買った、走るのが楽しみ")

    mark_processed_done = {"value": False}
    real_mark_processed = raw_log_io.mark_processed

    def spy_mark_processed(config_arg, raw_log_arg, **kwargs):
        real_mark_processed(config_arg, raw_log_arg, **kwargs)  # 3・4: Markdownへの書き込み自体は成功させる
        mark_processed_done["value"] = True

    monkeypatch.setattr(raw_log_io, "mark_processed", spy_mark_processed)

    crashed = {"value": False}

    class _FlakyCommitConn:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def commit(self):
            if mark_processed_done["value"] and not crashed["value"]:
                crashed["value"] = True
                raise RuntimeError("simulated crash right before the SQLite commit for this process_all() run")
            return self._real_conn.commit()

        def __getattr__(self, name):
            return getattr(self._real_conn, name)

    real_connect = db.connect

    @contextlib.contextmanager
    def flaky_connect(config_arg):
        with real_connect(config_arg) as real_conn:
            yield _FlakyCommitConn(real_conn)

    monkeypatch.setattr(db, "connect", flaky_connect)

    with pytest.raises(RuntimeError):  # 5・6
        pipeline.process_all(config)

    # クラッシュ直後の状態: Markdown上は処理済みなのに、SQLiteには一切反映されていない。
    memories_after_crash = memory_io.list_all_memories(config)
    assert len(memories_after_crash) == 1  # 3
    raw_logs_after_crash = raw_log_io.list_raw_logs(config)
    assert raw_logs_after_crash[0].processed_at is not None  # 4
    date_str = datetime.fromisoformat(raw_logs_after_crash[0].created_at).strftime("%Y-%m-%d")
    daily_path = config.daily_dir / f"{date_str}.md"
    assert daily_path.exists()  # 3: Daily Log Markdownも書かれている
    with db.connect(config) as conn:
        assert db.get_raw_log_processed_at(conn, raw_logs_after_crash[0].id) is None  # 反映されていない
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM daily_logs WHERE date = ?", (date_str,)).fetchone()[0] == 0

    # 7: 「再起動後」を模して、もう一度process_allを呼ぶ(reconcileがこの中で自動的に走る)。
    summary = pipeline.process_all(config)  # 8

    assert raw_logs_after_crash[0].id in summary.reconciled_raw_log_ids

    memories_after_recovery = memory_io.list_all_memories(config)
    assert len(memories_after_recovery) == 1  # 9: 重複生成されていない
    assert memories_after_recovery[0].id == memories_after_crash[0].id

    raw_logs_after_recovery = raw_log_io.list_raw_logs(config)
    assert raw_logs_after_recovery[0].processed_at is not None  # 10

    memory = memories_after_recovery[0]
    with db.connect(config) as conn:  # 11
        assert db.get_raw_log_processed_at(conn, raw_logs_after_recovery[0].id) == raw_logs_after_recovery[0].processed_at
        db_memory = conn.execute(
            "SELECT id, content, raw_log_id FROM memories WHERE id = ?", (memory.id,)
        ).fetchone()
        assert db_memory is not None
        assert db_memory[1] == memory.content
        db_entity_names = {
            row[0] for row in conn.execute(
                "SELECT e.name FROM memory_entities me JOIN entities e ON e.id = me.entity_id "
                "WHERE me.memory_id = ?", (memory.id,)
            ).fetchall()
        }
        db_daily_log = conn.execute(
            "SELECT date, file_path FROM daily_logs WHERE date = ?", (date_str,)
        ).fetchone()
    assert db_entity_names == set(memory.entities)  # 12: MarkdownとSQLiteの内容が一致する

    # 11: daily_logs行もreconcileで復元されている。file_pathはDaily Log Markdownの
    # 実際の場所(vaultルートからの相対パス)と一致すること。
    assert db_daily_log is not None
    assert db_daily_log[0] == date_str
    assert db_daily_log[1] == vault.relative_to_vault(daily_path, config)


# ---- レビュー対応(3回目): reconcileは現在のclassifierに依存しない ----


def test_process_all_reconcile_restores_existing_memory_even_if_classifier_now_disagrees(config, monkeypatch):
    """必須テストA: 旧classifierがmemory-worthyと判定してMemory Markdownを書いた
    直後にcommit前クラッシュした後、classifierが(将来のバージョン変更で)
    not-memory-worthyに変わっていても、reconcileは現在のclassifierを一切再実行
    せず、既に存在するMemory Markdownをそのまま正としてSQLiteへ復元することを
    確認する。

    1. 旧classifierでmemory-worthyと判定される入力をprocessする
    2. Memory Markdownが生成される
    3. SQLite commit直前でクラッシュする(fault injection)
    4. classifierをnot-memory-worthyに差し替える(将来のバージョン変更を模擬。
       差し替え後のclassify.classify自体が一切呼ばれないことも合わせて保証する)
    5. 「再起動後の次回実行」を模してprocess_allをもう一度呼ぶ
    6. その中でreconcileが自動的に走る
    7. 既存のMemory MarkdownがSQLiteへ復元される
    8. Memoryはちょうど1件だけ存在する(重複しない)
    """
    pipeline.add_capture(config, "十分に長い、分類変更をまたぐreconcileのテスト用の入力文です")

    mark_processed_done = {"value": False}
    real_mark_processed = raw_log_io.mark_processed

    def spy_mark_processed(config_arg, raw_log_arg, **kwargs):
        real_mark_processed(config_arg, raw_log_arg, **kwargs)  # 1・2: Markdownへの書き込み自体は成功させる
        mark_processed_done["value"] = True

    monkeypatch.setattr(raw_log_io, "mark_processed", spy_mark_processed)

    crashed = {"value": False}

    class _FlakyCommitConn:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def commit(self):
            if mark_processed_done["value"] and not crashed["value"]:
                crashed["value"] = True
                raise RuntimeError("simulated crash right before the SQLite commit for this process_all() run")
            return self._real_conn.commit()

        def __getattr__(self, name):
            return getattr(self._real_conn, name)

    real_connect = db.connect

    @contextlib.contextmanager
    def flaky_connect(config_arg):
        with real_connect(config_arg) as real_conn:
            yield _FlakyCommitConn(real_conn)

    monkeypatch.setattr(db, "connect", flaky_connect)

    with pytest.raises(RuntimeError):
        pipeline.process_all(config)  # 3

    memories_after_crash = memory_io.list_all_memories(config)
    assert len(memories_after_crash) == 1  # 2
    original_id = memories_after_crash[0].id
    original_raw_log_id = raw_log_io.list_raw_logs(config)[0].id

    # 4: classifierを差し替える。呼ばれたらテスト自体を失敗させることで、
    # reconcileがclassifierを一切呼ばないことも合わせて保証する。
    def classifier_must_not_be_called(text):
        raise AssertionError("reconcile must not call classify.classify() -- it must trust Markdown instead")

    monkeypatch.setattr(classify, "classify", classifier_must_not_be_called)

    summary = pipeline.process_all(config)  # 5・6

    assert original_raw_log_id in summary.reconciled_raw_log_ids
    memories_after_recovery = memory_io.list_all_memories(config)
    assert len(memories_after_recovery) == 1  # 8
    assert memories_after_recovery[0].id == original_id  # 7

    with db.connect(config) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1


def test_process_all_reconcile_does_not_fabricate_memory_when_classifier_now_disagrees(config, monkeypatch):
    """必須テストB(Aの逆方向): 旧classifierがnot-memory-worthyと判定しchatとして
    正常に処理済みになった(processing_outcome="chat"がMarkdownに記録される)後、
    classifierが(将来のバージョン変更で)memory-worthyに変わっていても、
    reconcileは「Memoryが存在しない異常事態」と誤検出してReconcileErrorを出したり、
    存在しないMemoryを勝手に生成したりしないことを確認する。

    1. 短い(かつキーワードに一致しない)入力を通常どおりprocessし、chatとして
       処理済みにする
    2. classifierをmemory-worthyに差し替える(将来のバージョン変更を模擬)
    3. SQLite側のprocessed状態だけを人為的に消し、reconcile対象にする
       (commit前クラッシュと同じ状態を直接再現する)
    4. process_allを呼び、reconcileが動く
    5. 存在しないMemoryを勝手に生成しない
    6. ReconcileErrorにもならない(例外が起きないことそのものが確認になる)
    7. Raw Logは正しくSQLiteへ復元される
    """
    pipeline.add_capture(config, "みじかい")  # 12文字未満・キーワード無し = chat扱い
    summary = pipeline.process_all(config)  # 1
    assert summary.memories_created == 0
    assert summary.kept_as_chat == 1
    assert memory_io.list_all_memories(config) == []

    raw_log = raw_log_io.list_raw_logs(config)[0]
    assert raw_log.processing_outcome == raw_log_io.PROCESSING_OUTCOME_CHAT

    # 3: SQLite側のprocessed状態だけを失わせる(commit前クラッシュ相当)。
    with db.connect(config) as conn:
        conn.execute("UPDATE raw_logs SET processed_at = NULL WHERE id = ?", (raw_log.id,))
        conn.commit()

    # 2: classifierを差し替える。
    real_classify = classify.classify

    def always_memory_worthy(text):
        return dataclasses.replace(real_classify(text), is_memory_worthy=True, type=MemoryType.THOUGHT)

    monkeypatch.setattr(classify, "classify", always_memory_worthy)

    summary2 = pipeline.process_all(config)  # 4

    assert raw_log.id in summary2.reconciled_raw_log_ids
    assert memory_io.list_all_memories(config) == []  # 5

    with db.connect(config) as conn:
        assert db.get_raw_log_processed_at(conn, raw_log.id) == raw_log.processed_at  # 7
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


# ---- レビュー対応(4回目・Phase 2最後の修正): _process_one()も既存Memoryの確認を
# ---- classifier実行より先に行う(reconcileと同じ原則) ----


def test_process_all_does_not_downgrade_existing_memory_to_chat_when_classifier_changes(config, monkeypatch):
    """_process_one()が以前classify.classify()を既存Memory確認より先に実行して
    いたために起きうる矛盾を再現し、修正後は起きないことを確認する。

    1. raw logを追加する(十分に長く、実classifierがmemory-worthyと判定する入力)
    2. classifierはこの時点では実物のまま(memory-worthyに"固定"されている)
    3. processを開始する
    4. Memory Markdown作成後、Raw Logのmark_processed前に意図的にクラッシュさせる
       (db.upsert_memoryを1回だけ失敗させるfault injection)
    5. Memory Markdownが1件存在することを確認する
    6. Raw Logがまだprocessed_at=Noneであることを確認する
    7. classifierをnot-memory-worthyに差し替える(将来のバージョン変更を模擬)。
       既存Memoryがある場合に呼ばれたらテスト自体を失敗させる実装にすることで、
       「classifierが呼ばれないこと」自体を保証する
    8. process_allを再実行する
    9. 8の中で新classifierが既存Memoryに対して呼ばれていないこと(7のガードで保証)
    10. Memory Markdownが1件のみであること
    11. Raw Logのprocessing_outcomeが"memory"であること
    12. Raw Logのmemory_idが既存Memory IDと一致すること
    13. SQLiteにMemoryが1件存在すること
    14. Markdown/Raw Log/SQLiteが同じ処理結果を示すこと
    15. reindex後も状態が変わらないこと
    """
    pipeline.add_capture(config, "十分に長い、classifier変更にまたがるクラッシュのテスト用の入力文です")  # 1

    real_upsert_memory = db.upsert_memory
    call_state = {"count": 0}

    def flaky_upsert_memory(conn, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError("simulated crash right after the memory markdown file was written")
        return real_upsert_memory(conn, **kwargs)

    monkeypatch.setattr(db, "upsert_memory", flaky_upsert_memory)

    with pytest.raises(RuntimeError):
        pipeline.process_all(config)  # 3・4

    memories_after_crash = memory_io.list_all_memories(config)
    assert len(memories_after_crash) == 1  # 5
    original_id = memories_after_crash[0].id

    raw_logs_after_crash = raw_log_io.list_raw_logs(config)
    assert raw_logs_after_crash[0].processed_at is None  # 6

    def classifier_must_not_be_called(text):
        raise AssertionError(
            "classify.classify() must not be called for a raw_log whose Memory "
            "Markdown already exists -- existing Markdown takes priority over "
            "re-classification."
        )

    monkeypatch.setattr(classify, "classify", classifier_must_not_be_called)  # 7

    summary = pipeline.process_all(config)  # 8・9(9はAssertionErrorが起きないことで保証される)

    memories_after_retry = memory_io.list_all_memories(config)
    assert len(memories_after_retry) == 1  # 10
    assert memories_after_retry[0].id == original_id
    assert summary.memories_created == 1

    raw_logs_after_retry = raw_log_io.list_raw_logs(config)
    assert raw_logs_after_retry[0].processed_at is not None
    assert raw_logs_after_retry[0].processing_outcome == raw_log_io.PROCESSING_OUTCOME_MEMORY  # 11
    assert raw_logs_after_retry[0].memory_id == original_id  # 12

    with db.connect(config) as conn:
        db_memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        db_memory = conn.execute("SELECT id, content FROM memories").fetchone()
    assert db_memory_count == 1  # 13
    assert db_memory[0] == original_id
    assert db_memory[1] == memories_after_retry[0].content  # 14: Markdown/SQLiteの内容が一致

    counts = pipeline.reindex(config)  # 15
    assert counts["memories"] == 1
    memories_after_reindex = memory_io.list_all_memories(config)
    assert len(memories_after_reindex) == 1
    assert memories_after_reindex[0].id == original_id
    with db.connect(config) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
