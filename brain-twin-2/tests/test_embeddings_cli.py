from pathlib import Path

from brain_twin import cli, db, embedding_runtime
from brain_twin.embedding_config import load_embedding_settings
from tests.fake_embedding_provider import FakeEmbeddingProvider


def _write_config(path: Path, *, secret_line=""):
    path.write_text(
        """
[embedding]
provider_id = "fake"
model_name = "fake"
profile_epoch = "cli-generation"
embedding_contract_version = 1
dimension = 4
normalized = false
document_template_version = 1
[vector]
backend = "exact_scan"
""" + secret_line,
        encoding="utf-8",
    )


def _environment(monkeypatch, config, settings_path):
    monkeypatch.setenv("BRAIN_TWIN_CONFIG", str(settings_path))
    monkeypatch.setenv("BRAIN_TWIN_VAULT_DIR", str(config.vault_dir))
    monkeypatch.setenv("BRAIN_TWIN_DATA_DIR", str(config.data_dir))


def _insert_memory(config):
    with db.connect(config) as conn:
        db.upsert_memory(
            conn, id="mem_1", type="thought", created_at="2026-08-25T00:00:00+09:00",
            event_date="2026-08-25", importance=3, confidence=1.0, source="test",
            status="active", title="title", content="content", raw_log_id=None,
            file_path="x.md", topics_json="[]",
        )
        conn.commit()


def test_embeddings_status_cli(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"; _write_config(path); _environment(monkeypatch, config, path)
    _insert_memory(config)
    assert cli.main(["embeddings", "status"]) == 0
    output = capsys.readouterr().out
    assert "Total active Memories: 1" in output and "Missing: 1" in output


def test_embeddings_sync_and_rebuild_cli(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"; _write_config(path); _environment(monkeypatch, config, path)
    _insert_memory(config)
    provider = FakeEmbeddingProvider(profile=load_embedding_settings(path).profile)
    monkeypatch.setattr(embedding_runtime, "create_provider", lambda settings: provider)
    assert cli.main(["embeddings", "sync"]) == 0
    assert "Embedded: 1" in capsys.readouterr().out
    assert cli.main(["embeddings", "status"]) == 0
    status_output = capsys.readouterr().out
    assert "Ready: 1" in status_output and "Missing: 0" in status_output
    assert cli.main(["embeddings", "rebuild"]) == 0
    assert "Embedded: 1" in capsys.readouterr().out


def test_embeddings_sync_without_provider_is_clear_error(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"; _write_config(path); _environment(monkeypatch, config, path)
    assert cli.main(["embeddings", "sync"]) == 1
    assert "provider is not installed" in capsys.readouterr().err


def test_embeddings_sync_rejects_provider_profile_mismatch(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"; _write_config(path); _environment(monkeypatch, config, path)
    monkeypatch.setattr(
        embedding_runtime, "create_provider", lambda settings: FakeEmbeddingProvider()
    )
    assert cli.main(["embeddings", "sync"]) == 1
    assert "does not match" in capsys.readouterr().err


def test_embeddings_cli_does_not_echo_secret(config, tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    secret = "never-print-this"
    _write_config(path, secret_line=f'\n[unknown]\naccess_token = "{secret}"\n')
    _environment(monkeypatch, config, path)
    assert cli.main(["embeddings", "status"]) == 1
    assert secret not in capsys.readouterr().err
