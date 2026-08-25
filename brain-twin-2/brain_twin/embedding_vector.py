"""Canonical float32 vector encoding shared by every vector backend."""
from __future__ import annotations

import math
import struct
from collections.abc import Sequence

from brain_twin.embedding_provider import EmbeddingDimensionError, EmbeddingValidationError


def validate_vector(vector: Sequence[float], dimension: int) -> tuple[float, ...]:
    if len(vector) != dimension:
        raise EmbeddingDimensionError(f"expected dimension {dimension}, got {len(vector)}")
    values = tuple(float(value) for value in vector)
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingValidationError("embedding values must be finite")
    return values


def encode_embedding(vector: Sequence[float], dimension: int) -> bytes:
    values = validate_vector(vector, dimension)
    return struct.pack(f"<{dimension}f", *values)


def decode_embedding(blob: bytes, dimension: int) -> tuple[float, ...]:
    if not isinstance(blob, bytes):
        raise EmbeddingValidationError("embedding BLOB must be bytes")
    expected = dimension * 4
    if len(blob) != expected:
        raise EmbeddingValidationError(
            f"embedding BLOB must be {expected} bytes, got {len(blob)}"
        )
    return validate_vector(struct.unpack(f"<{dimension}f", blob), dimension)
