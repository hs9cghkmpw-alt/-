from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

VALID_GRADES = {0, 1, 2, 3}
VALID_SPLITS = {"dev", "blind"}

REQUIRED_SLICE_TAGS = {
    "japanese_to_japanese",
    "paraphrase",
    "synonym",
    "omission_context",
    "proper_noun",
    "katakana_transliteration",
    "kanji_hiragana_variation",
    "japanese_english_mixed",
    "semantic_only",
    "lexical_sufficient",
    "hard_negative",
    "short_query",
    "long_memory",
}


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationMemory:
    memory_id: str
    title: str
    content: str
    language_tags: tuple[str, ...]
    length_bucket: str
    active: bool = True


@dataclass(frozen=True)
class EvaluationQuery:
    query_id: str
    text: str
    slice_tags: tuple[str, ...]
    relevance: Mapping[str, int]
    must_hit_ids: tuple[str, ...]
    lexical_sufficient: bool
    adjudication_note: str
    split: str


@dataclass(frozen=True)
class EvaluationDataset:
    version: str
    memories: tuple[EvaluationMemory, ...]
    queries: tuple[EvaluationQuery, ...]

    @property
    def memory_ids(self) -> frozenset[str]:
        return frozenset(memory.memory_id for memory in self.memories)

    @property
    def query_ids(self) -> frozenset[str]:
        return frozenset(query.query_id for query in self.queries)

    def queries_for_split(self, split: str | None) -> tuple[EvaluationQuery, ...]:
        if split is None:
            return self.queries
        if split not in VALID_SPLITS:
            raise DatasetValidationError(f"invalid split: {split!r}")
        return tuple(query for query in self.queries if query.split == split)


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetValidationError(f"{field} must be a non-empty string")
    return value


def _require_string_list(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DatasetValidationError(f"{field} must be a list of strings")
    result: list[str] = []
    for item in value:
        result.append(_require_nonempty_string(item, field))
    if not allow_empty and not result:
        raise DatasetValidationError(f"{field} must not be empty")
    if len(result) != len(set(result)):
        raise DatasetValidationError(f"{field} must not contain duplicates")
    return tuple(result)


def _load_memory(raw: Any) -> EvaluationMemory:
    if not isinstance(raw, dict):
        raise DatasetValidationError("each memory must be an object")
    memory_id = _require_nonempty_string(raw.get("memory_id"), "memory_id")
    title = _require_nonempty_string(raw.get("title"), f"{memory_id}.title")
    content = _require_nonempty_string(raw.get("content"), f"{memory_id}.content")
    language_tags = _require_string_list(raw.get("language_tags"), f"{memory_id}.language_tags")
    length_bucket = _require_nonempty_string(raw.get("length_bucket"), f"{memory_id}.length_bucket")
    active = raw.get("active", True)
    if not isinstance(active, bool):
        raise DatasetValidationError(f"{memory_id}.active must be boolean")
    return EvaluationMemory(
        memory_id=memory_id,
        title=title,
        content=content,
        language_tags=language_tags,
        length_bucket=length_bucket,
        active=active,
    )


def _load_query(raw: Any) -> EvaluationQuery:
    if not isinstance(raw, dict):
        raise DatasetValidationError("each query must be an object")
    query_id = _require_nonempty_string(raw.get("query_id"), "query_id")
    text = _require_nonempty_string(raw.get("text"), f"{query_id}.text")
    slice_tags = _require_string_list(raw.get("slice_tags"), f"{query_id}.slice_tags")

    relevance_raw = raw.get("relevance")
    if not isinstance(relevance_raw, dict) or not relevance_raw:
        raise DatasetValidationError(f"{query_id}.relevance must be a non-empty object")
    relevance: dict[str, int] = {}
    for memory_id, grade in relevance_raw.items():
        _require_nonempty_string(memory_id, f"{query_id}.relevance.memory_id")
        if isinstance(grade, bool) or not isinstance(grade, int) or grade not in VALID_GRADES:
            raise DatasetValidationError(
                f"{query_id}.relevance[{memory_id!r}] must be an integer in 0..3"
            )
        relevance[memory_id] = grade

    must_hit_ids = _require_string_list(
        raw.get("must_hit_ids", []), f"{query_id}.must_hit_ids", allow_empty=True
    )
    lexical_sufficient = raw.get("lexical_sufficient")
    if not isinstance(lexical_sufficient, bool):
        raise DatasetValidationError(f"{query_id}.lexical_sufficient must be boolean")
    adjudication_note = _require_nonempty_string(
        raw.get("adjudication_note"), f"{query_id}.adjudication_note"
    )
    split = _require_nonempty_string(raw.get("split"), f"{query_id}.split")
    if split not in VALID_SPLITS:
        raise DatasetValidationError(f"{query_id}.split must be one of {sorted(VALID_SPLITS)}")

    return EvaluationQuery(
        query_id=query_id,
        text=text,
        slice_tags=slice_tags,
        relevance=relevance,
        must_hit_ids=must_hit_ids,
        lexical_sufficient=lexical_sufficient,
        adjudication_note=adjudication_note,
        split=split,
    )


def dataset_from_mapping(raw: Mapping[str, Any], *, require_all_slices: bool = True) -> EvaluationDataset:
    if not isinstance(raw, Mapping):
        raise DatasetValidationError("dataset root must be an object")
    version = _require_nonempty_string(raw.get("version"), "version")
    memories_raw = raw.get("memories")
    queries_raw = raw.get("queries")
    if not isinstance(memories_raw, list) or not memories_raw:
        raise DatasetValidationError("memories must be a non-empty list")
    if not isinstance(queries_raw, list) or not queries_raw:
        raise DatasetValidationError("queries must be a non-empty list")

    memories = tuple(_load_memory(item) for item in memories_raw)
    queries = tuple(_load_query(item) for item in queries_raw)

    memory_ids = [memory.memory_id for memory in memories]
    query_ids = [query.query_id for query in queries]
    if len(memory_ids) != len(set(memory_ids)):
        raise DatasetValidationError("duplicate memory_id")
    if len(query_ids) != len(set(query_ids)):
        raise DatasetValidationError("duplicate query_id")

    memory_id_set = set(memory_ids)
    active_by_id = {memory.memory_id: memory.active for memory in memories}
    for query in queries:
        for relevant_id, grade in query.relevance.items():
            if relevant_id not in memory_id_set:
                raise DatasetValidationError(
                    f"{query.query_id} references unknown memory {relevant_id!r}"
                )
            if grade > 0 and not active_by_id[relevant_id]:
                raise DatasetValidationError(
                    f"{query.query_id} assigns positive relevance to inactive memory {relevant_id!r}"
                )
        for must_hit_id in query.must_hit_ids:
            if must_hit_id not in memory_id_set:
                raise DatasetValidationError(
                    f"{query.query_id} must_hit references unknown memory {must_hit_id!r}"
                )
            if query.relevance.get(must_hit_id, 0) <= 0:
                raise DatasetValidationError(
                    f"{query.query_id} must_hit {must_hit_id!r} must have positive relevance"
                )

    if require_all_slices:
        present = {tag for query in queries for tag in query.slice_tags}
        missing = REQUIRED_SLICE_TAGS - present
        if missing:
            raise DatasetValidationError(
                "dataset is missing required slice tags: " + ", ".join(sorted(missing))
            )

    return EvaluationDataset(version=version, memories=memories, queries=queries)


def load_dataset(path: str | Path, *, require_all_slices: bool = True) -> EvaluationDataset:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    return dataset_from_mapping(raw, require_all_slices=require_all_slices)


def canonical_dataset_bytes(dataset: EvaluationDataset) -> bytes:
    payload = {
        "version": dataset.version,
        "memories": [
            {
                "memory_id": memory.memory_id,
                "title": memory.title,
                "content": memory.content,
                "language_tags": list(memory.language_tags),
                "length_bucket": memory.length_bucket,
                "active": memory.active,
            }
            for memory in dataset.memories
        ],
        "queries": [
            {
                "query_id": query.query_id,
                "text": query.text,
                "slice_tags": list(query.slice_tags),
                "relevance": dict(sorted(query.relevance.items())),
                "must_hit_ids": list(query.must_hit_ids),
                "lexical_sufficient": query.lexical_sufficient,
                "adjudication_note": query.adjudication_note,
                "split": query.split,
            }
            for query in dataset.queries
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def dataset_sha256(dataset: EvaluationDataset) -> str:
    return hashlib.sha256(canonical_dataset_bytes(dataset)).hexdigest()
