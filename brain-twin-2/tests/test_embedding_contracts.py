from dataclasses import replace

import pytest

from brain_twin.embedding_provider import (
    EmbeddingConfigurationError, EmbeddingProfile, EmbeddingTransientError,
)
from tests.fake_embedding_provider import FakeEmbeddingProvider


def _profile(**changes) -> EmbeddingProfile:
    values = dict(
        provider_id="fake", model_name="fake-v1", model_revision="immutable-r1",
        profile_epoch=None, embedding_contract_version=1, dimension=3,
        normalized=True, document_template_version=1,
    )
    values.update(changes)
    return EmbeddingProfile(**values)


def test_fingerprint_is_deterministic():
    assert _profile().fingerprint == _profile().fingerprint


@pytest.mark.parametrize("field,value", [
    ("provider_id", "other"), ("model_name", "v2"), ("model_revision", "r2"),
    ("profile_epoch", "epoch2"), ("embedding_contract_version", 2),
    ("dimension", 4), ("normalized", False), ("document_template_version", 2),
])
def test_each_profile_field_changes_fingerprint(field, value):
    assert replace(_profile(), **{field: value}).fingerprint != _profile().fingerprint


def test_backend_choice_does_not_affect_fingerprint():
    profile = _profile()
    choices = {"exact_scan": profile.fingerprint, "sqlite_vec": profile.fingerprint}
    assert len(set(choices.values())) == 1


def test_profile_accepts_epoch_without_revision():
    assert _profile(model_revision=None, profile_epoch="manual-generation-2")


@pytest.mark.parametrize("revision,epoch", [
    (None, None), ("", ""), ("unknown", None), (" UNKNOWN ", ""),
])
def test_profile_rejects_missing_or_unknown_generation_key(revision, epoch):
    with pytest.raises(EmbeddingConfigurationError):
        _profile(model_revision=revision, profile_epoch=epoch)


def test_fake_provider_is_deterministic_and_batches():
    provider = FakeEmbeddingProvider(dimension=5)
    assert provider.embed_documents(["same", "same"])[0] == provider.embed_query("same")
    assert len(provider.embed_query("x")) == 5


def test_fake_provider_supports_error_injection():
    provider = FakeEmbeddingProvider(error=EmbeddingTransientError("offline"))
    with pytest.raises(EmbeddingTransientError):
        provider.embed_query("x")
