from datetime import datetime

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
