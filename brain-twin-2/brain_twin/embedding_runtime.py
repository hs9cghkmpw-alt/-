"""Runtime wiring for optional providers/backends; imports no provider SDK."""
from __future__ import annotations

from brain_twin.embedding_config import EmbeddingSettings
from brain_twin.embedding_provider import EmbeddingConfigurationError, EmbeddingProvider
from brain_twin.vector_exact import ExactScanBackend
from brain_twin.vector_index import VectorIndexBackend


def create_backend(settings: EmbeddingSettings) -> VectorIndexBackend:
    if settings.vector_backend == "exact_scan":
        return ExactScanBackend()
    raise EmbeddingConfigurationError(
        f"vector backend is not installed: {settings.vector_backend}"
    )


def create_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    """Sprint 4B ships no production adapter; tests inject an offline fake here."""
    raise EmbeddingConfigurationError(
        f"embedding provider is not installed: {settings.profile.provider_id}"
    )
