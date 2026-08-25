"""Sprint 4C: `search --vector` / `search --hybrid` CLI wiring tests."""
from pathlib import Path

from brain_twin import cli, db, embedding_runtime
from brain_twin.embedding_config import load_embedding_settings
from brain_twin.embedding_service import EmbeddingService
from tests.fake_embedding_provider import FakeEmbeddingProvider


def _write_config(path: Path):
    path.write_text(
        """
[embedding]
provider_id = "fake"
model_name = "fake"
profile_epoch = "search-cli-generation"
embedding_contract_version = 1
dimension = 4
normalized = false
document_template_version = 1
[vector]
backend = "exact_scan"
""",
        encoding="utf-8",
    )


def _environment(monkeypatch, config, settings_path):
    monkeypatch.setenv("BRAIN_TWIN_CONFIG", str(settings_path))
    monkeypatch.setenv("BRAIN_TWIN_VAULT_DIR", str(config.vault_dir))
    monkeypatch.setenv("BRAIN_TWIN_DATA_DIR", str(config.data_dir))


def _insert_memory(config, memory_id, content):
    with db.connect(config) as conn:
        db.upsert_memory(
            conn, id=memory_id, type="thought", created_at="2026-08-25T00:00:00+09:00",
            event_date="2026-08-25", importance=3, confidence=1.0, source="test",
            status="active", title=content, content=content, raw_log_id=None,
            file_path=f"{memory_id}.md", topics_json="[]",
        )
        conn.commit()


def _sync(config, path, monkeypatch):
    provider = FakeEmbeddingProvider(profile=load_embedding_settings(path).profile)
    monkeypatch.setattr(embedding_runtime, "create_provider", lambda settings: provider)
    settings = load_embedding_settings(path)
    backend = embedding_runtime.create_backend(settings)
    EmbeddingService(config, provider, backend).sync()
    return provider


def _ready(config, tmp_path, monkeypatch, *, content="unique cli search phrase"):
    path = tmp_path / "config.toml"
    _write_config(path)
    _environment(monkeypatch, config, path)
    _insert_memory(config, "mem_1", content)
    _sync(config, path, monkeypatch)
    return path


def test_search_vector_cli_wiring_returns_results(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(["search", "unique cli search phrase", "--vector"]) == 0
    out = capsys.readouterr().out
    assert "id=mem_1" in out


def test_search_hybrid_cli_wiring_returns_results(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(["search", "unique cli search phrase", "--hybrid"]) == 0
    out = capsys.readouterr().out
    assert "id=mem_1" in out


def test_search_vector_cli_verbose_shows_similarity(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(["search", "unique cli search phrase", "--vector", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "similarity=" in out and "vector_rank=" in out


def test_search_hybrid_cli_verbose_shows_component_scores(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(["search", "unique cli search phrase", "--hybrid", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "fusion=" in out and "metadata_multiplier=" in out and "final=" in out


def test_search_vector_and_hybrid_are_mutually_exclusive(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    try:
        cli.main(["search", "unique cli search phrase", "--vector", "--hybrid"])
        assert False, "argparse should have exited"
    except SystemExit as exc:
        assert exc.code == 2
    err = capsys.readouterr().err
    assert "not allowed with argument" in err


def test_search_vector_with_related_shows_related_section(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    _insert_memory(config, "mem_2", "some other memory")
    with db.connect(config) as conn:
        db.upsert_link(
            conn, source_memory_id="mem_1", target_memory_id="mem_2",
            relation_type="same_topic", reason="shared topic", strength=0.5,
            created_at="2026-08-25T00:00:00+09:00",
        )
        conn.commit()
    assert cli.main(["search", "unique cli search phrase", "--vector", "--related"]) == 0
    out = capsys.readouterr().out
    assert "id=mem_1" in out
    assert "関連Memory:" in out and "id=mem_2" in out


def test_search_hybrid_with_related_shows_related_section(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    _insert_memory(config, "mem_2", "some other memory")
    with db.connect(config) as conn:
        db.upsert_link(
            conn, source_memory_id="mem_1", target_memory_id="mem_2",
            relation_type="same_topic", reason="shared topic", strength=0.5,
            created_at="2026-08-25T00:00:00+09:00",
        )
        conn.commit()
    assert cli.main(["search", "unique cli search phrase", "--hybrid", "--related"]) == 0
    out = capsys.readouterr().out
    assert "id=mem_1" in out
    assert "関連Memory:" in out and "id=mem_2" in out


def test_search_vector_with_related_and_no_links_omits_related_section(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(["search", "unique cli search phrase", "--vector", "--related"]) == 0
    out = capsys.readouterr().out
    assert "id=mem_1" in out
    assert "関連Memory:" not in out


def test_search_vector_with_negative_related_limit_is_a_clear_error(config, tmp_path, monkeypatch, capsys):
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(
        ["search", "unique cli search phrase", "--vector", "--related", "--related-limit", "-1"]
    ) == 1
    err = capsys.readouterr().err
    assert "[NG]" in err


def test_search_vector_cli_capability_unavailable_is_a_clear_error(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    _write_config(path)
    _environment(monkeypatch, config, path)
    _insert_memory(config, "mem_1", "unique cli search phrase")
    # No embeddings sync at all -> profile/backend never activated.
    monkeypatch.setattr(
        embedding_runtime, "create_provider",
        lambda settings: FakeEmbeddingProvider(profile=load_embedding_settings(path).profile),
    )
    assert cli.main(["search", "unique cli search phrase", "--vector"]) == 1
    err = capsys.readouterr().err
    assert "[NG]" in err


def test_search_hybrid_cli_capability_unavailable_is_a_clear_error(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    _write_config(path)
    _environment(monkeypatch, config, path)
    _insert_memory(config, "mem_1", "unique cli search phrase")
    monkeypatch.setattr(
        embedding_runtime, "create_provider",
        lambda settings: FakeEmbeddingProvider(profile=load_embedding_settings(path).profile),
    )
    assert cli.main(["search", "unique cli search phrase", "--hybrid"]) == 1
    err = capsys.readouterr().err
    assert "[NG]" in err


def test_search_vector_cli_without_provider_installed_is_a_clear_error(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    _write_config(path)
    _environment(monkeypatch, config, path)
    _insert_memory(config, "mem_1", "unique cli search phrase")
    assert cli.main(["search", "unique cli search phrase", "--vector"]) == 1
    err = capsys.readouterr().err
    assert "provider is not installed" in err


def test_plain_search_cli_output_is_unchanged_when_vector_configured(config, tmp_path, monkeypatch, capsys):
    """Sprint 4Cを設定しても、フラグ無しの `search` は従来どおり動く。"""
    _ready(config, tmp_path, monkeypatch)
    assert cli.main(["search", "unique cli search phrase"]) == 0
    out = capsys.readouterr().out
    assert "id=mem_1" in out
    assert "similarity=" not in out
    assert "fusion=" not in out


def test_plain_search_cli_works_with_no_embedding_config_at_all(config, monkeypatch, capsys):
    monkeypatch.delenv("BRAIN_TWIN_CONFIG", raising=False)
    monkeypatch.setenv("BRAIN_TWIN_VAULT_DIR", str(config.vault_dir))
    monkeypatch.setenv("BRAIN_TWIN_DATA_DIR", str(config.data_dir))
    _insert_memory(config, "mem_1", "plain search still works")
    assert cli.main(["search", "plain search still works"]) == 0
    assert "id=mem_1" in capsys.readouterr().out
