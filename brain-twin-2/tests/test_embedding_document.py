from dataclasses import replace

from brain_twin.embedding_document import build_embedding_document
from brain_twin.models import Memory, MemoryStatus, MemoryType


def _memory(**changes):
    values = dict(
        id="mem_1", type=MemoryType.THOUGHT, created_at="2026-08-25T00:00:00+09:00",
        event_date="2026-08-25", importance=3, confidence=0.8, source="test",
        status=MemoryStatus.ACTIVE, title="Title", content="Content", raw_log_id=None,
    )
    values.update(changes)
    return Memory(**values)


def test_canonical_document_and_hash_are_deterministic():
    document = build_embedding_document(_memory())
    assert document.text == "title: Title\ncontent: Content"
    assert document == build_embedding_document(_memory())


def test_title_change_changes_hash():
    assert build_embedding_document(_memory()).content_hash != build_embedding_document(_memory(title="Other")).content_hash


def test_content_change_changes_hash():
    assert build_embedding_document(_memory()).content_hash != build_embedding_document(_memory(content="Other")).content_hash


def test_metadata_change_does_not_change_hash():
    original = _memory()
    changed = replace(original, importance=5, confidence=0.1, topics=["new"], status=MemoryStatus.ARCHIVED)
    assert build_embedding_document(original).content_hash == build_embedding_document(changed).content_hash
