import math

import pytest

from brain_twin.embedding_provider import EmbeddingDimensionError, EmbeddingValidationError
from brain_twin.embedding_vector import decode_embedding, encode_embedding


def test_float32_blob_round_trip():
    decoded = decode_embedding(encode_embedding([0.25, -0.5], 2), 2)
    assert decoded == pytest.approx((0.25, -0.5))


def test_dimension_mismatch_is_rejected():
    with pytest.raises(EmbeddingDimensionError):
        encode_embedding([1.0], 2)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_value_is_rejected(value):
    with pytest.raises(EmbeddingValidationError):
        encode_embedding([value], 1)


def test_malformed_blob_is_rejected():
    with pytest.raises(EmbeddingValidationError):
        decode_embedding(b"bad", 2)
