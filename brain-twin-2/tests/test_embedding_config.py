import pytest

from brain_twin.embedding_config import default_user_config_path, load_embedding_settings
from brain_twin.embedding_provider import EmbeddingConfigurationError


CONFIG = """
[embedding]
provider_id = "local"
model_name = "model"
profile_epoch = "generation-1"
embedding_contract_version = 1
dimension = 3
normalized = true
document_template_version = 1

[vector]
backend = "exact_scan"
"""


def test_default_config_is_in_windows_user_config_area(tmp_path):
    assert default_user_config_path(environ={"APPDATA": str(tmp_path)}) == tmp_path / "BrainTwin" / "config.toml"


def test_config_override_and_profile_backend_separation(tmp_path):
    path = tmp_path / "chosen.toml"; path.write_text(CONFIG, encoding="utf-8")
    assert default_user_config_path(environ={"BRAIN_TWIN_CONFIG": str(path)}) == path
    settings = load_embedding_settings(path)
    assert settings.profile.provider_id == "local"
    assert settings.vector_backend == "exact_scan"
    assert settings.profile.fingerprint


def test_plaintext_secret_field_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG + '\napi_key = "must-not-be-here"\n', encoding="utf-8")
    with pytest.raises(EmbeddingConfigurationError):
        load_embedding_settings(path)
