from datetime import datetime

from brain_twin import ids


def test_new_id_format(config):
    dt = datetime(2026, 8, 14, 6, 30)
    generated = ids.new_id(config.vault_dir, "mem", dt)
    assert generated == "mem_20260814_001"


def test_new_id_increments_within_same_day(config):
    dt = datetime(2026, 8, 14, 6, 30)
    config.vault_dir.mkdir(parents=True)
    (config.vault_dir / "mem_20260814_001.md").write_text("x", encoding="utf-8")
    (config.vault_dir / "mem_20260814_002.md").write_text("x", encoding="utf-8")

    generated = ids.new_id(config.vault_dir, "mem", dt)
    assert generated == "mem_20260814_003"


def test_new_id_resets_for_new_day(config):
    config.vault_dir.mkdir(parents=True)
    (config.vault_dir / "mem_20260813_005.md").write_text("x", encoding="utf-8")

    generated = ids.new_id(config.vault_dir, "mem", datetime(2026, 8, 14, 6, 30))
    assert generated == "mem_20260814_001"


def test_raw_and_mem_sequences_are_independent(config):
    config.vault_dir.mkdir(parents=True)
    (config.vault_dir / "raw_20260814_001.md").write_text("x", encoding="utf-8")
    (config.vault_dir / "raw_20260814_002.md").write_text("x", encoding="utf-8")

    mem_id = ids.new_id(config.vault_dir, "mem", datetime(2026, 8, 14, 6, 30))
    assert mem_id == "mem_20260814_001"
