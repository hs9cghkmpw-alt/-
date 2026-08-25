"""Canonical text embedded for a Memory and its stable content hash."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

DOCUMENT_TEMPLATE_VERSION = 1


class MemoryDocumentSource(Protocol):
    title: str
    content: str


@dataclass(frozen=True)
class EmbeddingDocument:
    text: str
    content_hash: str
    template_version: int = DOCUMENT_TEMPLATE_VERSION


def build_embedding_document(memory: MemoryDocumentSource) -> EmbeddingDocument:
    text = f"title: {memory.title}\ncontent: {memory.content}"
    return EmbeddingDocument(
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
