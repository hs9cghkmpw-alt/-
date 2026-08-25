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


@pytest.mark.parametrize("key", [
    "api_key", "api-key", "apiKey", "openai_api_key", "secret_key",
    "access_token", "refresh_token", "auth_token", "bearer_token",
    "password", "passwd", "client_secret", "clientSecret",
    "apikey", "APIKey", "private_key", "privateKey",
])
def test_plaintext_credential_field_is_rejected(tmp_path, key):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG + f'\n[unknown]\n"{key}" = "sensitive-value"\n', encoding="utf-8")
    with pytest.raises(EmbeddingConfigurationError):
        load_embedding_settings(path)


def test_plaintext_credential_is_rejected_in_nested_unknown_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG + '\n[unknown.deep]\naccess_token = "sensitive-value"\n', encoding="utf-8")
    with pytest.raises(EmbeddingConfigurationError):
        load_embedding_settings(path)


@pytest.mark.parametrize("key", ["tokenizer", "secretary"])
def test_unrelated_field_name_is_not_misidentified_as_credential(tmp_path, key):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG + f'\n[unknown]\n{key} = "ordinary-value"\n', encoding="utf-8")
    assert load_embedding_settings(path).profile.provider_id == "local"


def test_credential_error_does_not_include_secret_value(tmp_path):
    secret_value = "do-not-echo-this-value"
    path = tmp_path / "config.toml"
    path.write_text(CONFIG + f'\n[unknown]\naccess_token = "{secret_value}"\n', encoding="utf-8")
    with pytest.raises(EmbeddingConfigurationError) as exc_info:
        load_embedding_settings(path)
    assert secret_value not in str(exc_info.value)
