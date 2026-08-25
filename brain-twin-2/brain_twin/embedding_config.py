"""Non-secret embedding configuration stored outside the rebuildable SQLite cache."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from brain_twin.embedding_provider import EmbeddingConfigurationError, EmbeddingProfile

CONFIG_ENV = "BRAIN_TWIN_CONFIG"
_SECRET_TOKENS = {"token", "secret", "password", "passwd", "credential", "credentials"}


@dataclass(frozen=True)
class EmbeddingSettings:
    profile: EmbeddingProfile
    vector_backend: str


def default_user_config_path(*, environ: dict[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    override = values.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser().resolve()
    appdata = values.get("APPDATA")
    if not appdata:
        raise EmbeddingConfigurationError("APPDATA is unavailable; set BRAIN_TWIN_CONFIG")
    return (Path(appdata) / "BrainTwin" / "config.toml").resolve()


def load_embedding_settings(path: Path) -> EmbeddingSettings:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EmbeddingConfigurationError(f"cannot read embedding config: {path}") from exc
    _reject_secrets(data)
    try:
        embedding = data["embedding"]
        vector = data["vector"]
        profile = EmbeddingProfile(
            provider_id=embedding["provider_id"],
            model_name=embedding["model_name"],
            model_revision=embedding.get("model_revision"),
            profile_epoch=embedding.get("profile_epoch"),
            embedding_contract_version=embedding["embedding_contract_version"],
            dimension=embedding["dimension"],
            normalized=embedding["normalized"],
            document_template_version=embedding["document_template_version"],
        )
        backend = vector["backend"].strip()
    except (KeyError, TypeError, AttributeError) as exc:
        raise EmbeddingConfigurationError("embedding/vector config fields are incomplete") from exc
    if not backend:
        raise EmbeddingConfigurationError("vector.backend must not be empty")
    return EmbeddingSettings(profile=profile, vector_backend=backend)


def _reject_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_credential_key(key):
                raise EmbeddingConfigurationError(
                    f"secret field {key!r} must use environment or an OS credential store"
                )
            _reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secrets(child)


def _is_credential_key(key: str) -> bool:
    """Recognize credential field names without matching words such as tokenizer/secretary."""
    # Split camelCase before treating punctuation (underscore, dash, dot, etc.) uniformly.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).casefold()
    tokens = tuple(token for token in re.split(r"[^a-z0-9]+", separated) if token)
    compact = "".join(tokens)
    if compact in {"apikey", "privatekey"}:
        return True
    if any(token in _SECRET_TOKENS for token in tokens):
        return True
    return any(left == "api" and right == "key" for left, right in zip(tokens, tokens[1:]))
