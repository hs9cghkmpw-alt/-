from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .dataset import EvaluationDataset, dataset_sha256

_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "credential",
    "authorization",
    "access_token",
    "refresh_token",
    "bearer_token",
)
_SECRET_VALUE_PREFIXES = ("sk-", "ghp_", "github_pat_", "Bearer ")


class ManifestValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExperimentManifest:
    experiment_id: str
    timestamp_utc: str
    dataset_version: str
    dataset_sha256: str
    git_commit: str
    provider_label: str
    model_name: str
    model_revision: str
    instruction_id: str
    instruction_text_sha256: str
    dimension: int
    normalized: bool
    document_template_version: str
    backend_label: str
    backend_params: Mapping[str, Any]
    python_version: str
    platform: str
    random_seed: int


def instruction_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _walk_for_secrets(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower().replace("-", "_")
            if any(part in key_text for part in _SECRET_KEY_PARTS):
                raise ManifestValidationError(f"secret-like key is not allowed in manifest: {path}.{key}")
            _walk_for_secrets(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _walk_for_secrets(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        stripped = value.strip()
        if any(stripped.startswith(prefix) for prefix in _SECRET_VALUE_PREFIXES):
            raise ManifestValidationError(f"secret-like value is not allowed in manifest: {path}")


def build_manifest(
    *,
    dataset: EvaluationDataset,
    experiment_id: str,
    git_commit: str,
    provider_label: str,
    model_name: str,
    model_revision: str,
    instruction_id: str,
    instruction_text: str,
    dimension: int,
    normalized: bool,
    document_template_version: str,
    backend_label: str,
    backend_params: Mapping[str, Any],
    random_seed: int,
    timestamp_utc: str | None = None,
) -> ExperimentManifest:
    required_strings = {
        "experiment_id": experiment_id,
        "git_commit": git_commit,
        "provider_label": provider_label,
        "model_name": model_name,
        "model_revision": model_revision,
        "instruction_id": instruction_id,
        "document_template_version": document_template_version,
        "backend_label": backend_label,
    }
    for name, value in required_strings.items():
        if not isinstance(value, str) or not value.strip():
            raise ManifestValidationError(f"{name} must be a non-empty string")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise ManifestValidationError("dimension must be a positive integer")
    if not isinstance(normalized, bool):
        raise ManifestValidationError("normalized must be boolean")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ManifestValidationError("random_seed must be an integer")
    if not isinstance(instruction_text, str):
        raise ManifestValidationError("instruction_text must be a string")

    params = dict(backend_params)
    _walk_for_secrets(params)

    timestamp = timestamp_utc or datetime.now(timezone.utc).isoformat()
    manifest = ExperimentManifest(
        experiment_id=experiment_id,
        timestamp_utc=timestamp,
        dataset_version=dataset.version,
        dataset_sha256=dataset_sha256(dataset),
        git_commit=git_commit,
        provider_label=provider_label,
        model_name=model_name,
        model_revision=model_revision,
        instruction_id=instruction_id,
        instruction_text_sha256=instruction_sha256(instruction_text),
        dimension=dimension,
        normalized=normalized,
        document_template_version=document_template_version,
        backend_label=backend_label,
        backend_params=params,
        python_version=platform.python_version(),
        platform=platform.platform(),
        random_seed=random_seed,
    )
    _walk_for_secrets(asdict(manifest))
    return manifest


def manifest_to_dict(manifest: ExperimentManifest) -> dict[str, Any]:
    payload = asdict(manifest)
    _walk_for_secrets(payload)
    return payload


def manifest_json(manifest: ExperimentManifest) -> str:
    return json.dumps(manifest_to_dict(manifest), ensure_ascii=False, sort_keys=True, indent=2)
