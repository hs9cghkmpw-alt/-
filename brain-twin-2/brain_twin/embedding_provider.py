"""Embedding provider contracts.  This module intentionally imports no provider SDK."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol, Sequence, runtime_checkable


class EmbeddingError(Exception):
    """Base class for embedding failures."""


class EmbeddingConfigurationError(EmbeddingError):
    """The selected provider/profile configuration is invalid."""


class EmbeddingDimensionError(EmbeddingError):
    """A vector does not match the profile dimension."""


class EmbeddingTransientError(EmbeddingError):
    """A retryable provider failure (timeout, rate limit, temporary outage)."""


class EmbeddingValidationError(EmbeddingError):
    """Provider output or cached data is malformed."""


@dataclass(frozen=True)
class EmbeddingProfile:
    provider_id: str
    model_name: str
    model_revision: str | None
    profile_epoch: str | None
    embedding_contract_version: int
    dimension: int
    normalized: bool
    document_template_version: int

    def __post_init__(self) -> None:
        for name in ("provider_id", "model_name"):
            if not getattr(self, name).strip():
                raise EmbeddingConfigurationError(f"{name} must not be empty")
        if self.dimension <= 0:
            raise EmbeddingConfigurationError("dimension must be positive")
        if self.embedding_contract_version <= 0 or self.document_template_version <= 0:
            raise EmbeddingConfigurationError("contract/template versions must be positive")

        revision = _generation_value(self.model_revision)
        epoch = _generation_value(self.profile_epoch)
        # A mutable alias such as "unknown" cannot detect a provider-side model update.
        if revision is None and epoch is None:
            raise EmbeddingConfigurationError(
                "an immutable model_revision or non-empty profile_epoch is required"
            )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _generation_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value.casefold() == "unknown":
        return None
    return value


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
