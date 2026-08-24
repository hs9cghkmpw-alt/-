from datetime import datetime

import pytest

from brain_twin import db, memory_io, pipeline, raw_log_io, search, vault


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
    "SELECT source_memory_id, target_memory_id, relation_type, reason, created_at "
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

    # source/target/relation_type/reason に加えcreated_atまで完全一致することを確認する
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
