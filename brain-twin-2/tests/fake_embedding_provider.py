"""Deterministic, offline provider used only by tests."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

from brain_twin.embedding_provider import EmbeddingError, EmbeddingProfile


class FakeEmbeddingProvider:
    def __init__(
        self, dimension: int = 4, *, error: EmbeddingError | None = None,
        profile_epoch: str = "test-generation-1", profile: EmbeddingProfile | None = None,
    ) -> None:
        self._profile = profile or EmbeddingProfile(
            provider_id="fake", model_name="deterministic-test", model_revision=None,
            profile_epoch=profile_epoch, embedding_contract_version=1,
            dimension=dimension, normalized=False, document_template_version=1,
        )
        self.error = error
        self.calls = 0

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    def _embed(self, text: str) -> list[float]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [((digest[index] / 255.0) * 2.0) - 1.0 for index in range(self.profile.dimension)]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
