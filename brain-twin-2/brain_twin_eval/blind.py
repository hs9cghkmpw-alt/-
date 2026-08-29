from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .dataset import EvaluationDataset, dataset_from_mapping, dataset_sha256


class BlindPackageError(ValueError):
    pass


FORBIDDEN_PUBLIC_QUERY_KEYS = {
    "slice_tags",
    "relevance",
    "must_hit_ids",
    "lexical_sufficient",
    "adjudication_note",
}


@dataclass(frozen=True)
class BlindPackages:
    runner: Mapping[str, Any]
    private_judgements: Mapping[str, Any]


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def create_blind_packages(dataset: EvaluationDataset) -> BlindPackages:
    if dataset.judgement_visibility != "held_out":
        raise BlindPackageError("formal blind source dataset must use held_out judgements")
    if not dataset.queries or any(query.split != "blind" for query in dataset.queries):
        raise BlindPackageError("formal blind source dataset must contain only blind-split queries")

    source_sha = dataset_sha256(dataset)
    runner: dict[str, Any] = {
        "schema": 1,
        "version": dataset.version,
        "judgement_visibility": "held_out",
        "source_dataset_sha256": source_sha,
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
                "split": query.split,
            }
            for query in dataset.queries
        ],
    }
    runner_sha = payload_sha256(runner)
    private: dict[str, Any] = {
        "schema": 1,
        "version": dataset.version,
        "source_dataset_sha256": source_sha,
        "runner_sha256": runner_sha,
        "queries": [
            {
                "query_id": query.query_id,
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
    validate_runner_payload(runner)
    return BlindPackages(runner=runner, private_judgements=private)


def validate_runner_payload(raw: Mapping[str, Any]) -> None:
    if not isinstance(raw, Mapping):
        raise BlindPackageError("blind runner package root must be an object")
    if raw.get("schema") != 1:
        raise BlindPackageError("unsupported blind runner package schema")
    if raw.get("judgement_visibility") != "held_out":
        raise BlindPackageError("blind runner package must declare held_out visibility")
    memories = raw.get("memories")
    queries = raw.get("queries")
    if not isinstance(memories, list) or not memories:
        raise BlindPackageError("blind runner package must contain memories")
    if not isinstance(queries, list) or not queries:
        raise BlindPackageError("blind runner package must contain queries")
    seen: set[str] = set()
    for query in queries:
        if not isinstance(query, Mapping):
            raise BlindPackageError("blind runner query must be an object")
        leaked = FORBIDDEN_PUBLIC_QUERY_KEYS.intersection(query)
        if leaked:
            raise BlindPackageError("blind runner query leaks judgement fields: " + ", ".join(sorted(leaked)))
        query_id = query.get("query_id")
        text = query.get("text")
        if not isinstance(query_id, str) or not query_id.strip():
            raise BlindPackageError("blind runner query_id must be non-empty")
        if query_id in seen:
            raise BlindPackageError("duplicate blind runner query_id")
        seen.add(query_id)
        if not isinstance(text, str) or not text.strip():
            raise BlindPackageError(f"blind runner query {query_id} has empty text")
        if query.get("split") != "blind":
            raise BlindPackageError(f"blind runner query {query_id} must use blind split")


def reconstruct_held_out_dataset(
    runner: Mapping[str, Any],
    private_judgements: Mapping[str, Any],
) -> EvaluationDataset:
    validate_runner_payload(runner)
    if not isinstance(private_judgements, Mapping):
        raise BlindPackageError("private judgement package root must be an object")
    expected_runner_sha = private_judgements.get("runner_sha256")
    actual_runner_sha = payload_sha256(runner)
    if expected_runner_sha != actual_runner_sha:
        raise BlindPackageError("private judgements do not match this blind runner package")
    if private_judgements.get("version") != runner.get("version"):
        raise BlindPackageError("blind runner/private versions do not match")
    if private_judgements.get("source_dataset_sha256") != runner.get("source_dataset_sha256"):
        raise BlindPackageError("blind runner/private source commitments do not match")

    private_queries = private_judgements.get("queries")
    if not isinstance(private_queries, list):
        raise BlindPackageError("private judgement queries must be a list")
    private_by_id: dict[str, Mapping[str, Any]] = {}
    for item in private_queries:
        if not isinstance(item, Mapping):
            raise BlindPackageError("private judgement query must be an object")
        query_id = item.get("query_id")
        if not isinstance(query_id, str) or not query_id.strip():
            raise BlindPackageError("private judgement query_id must be non-empty")
        if query_id in private_by_id:
            raise BlindPackageError("duplicate private judgement query_id")
        private_by_id[query_id] = item

    combined_queries: list[dict[str, Any]] = []
    public_ids: set[str] = set()
    for public in runner["queries"]:
        query_id = str(public["query_id"])
        public_ids.add(query_id)
        private = private_by_id.get(query_id)
        if private is None:
            raise BlindPackageError(f"missing private judgement for query {query_id}")
        combined_queries.append(
            {
                "query_id": query_id,
                "text": public["text"],
                "slice_tags": private.get("slice_tags"),
                "relevance": private.get("relevance"),
                "must_hit_ids": private.get("must_hit_ids"),
                "lexical_sufficient": private.get("lexical_sufficient"),
                "adjudication_note": private.get("adjudication_note"),
                "split": public["split"],
            }
        )
    extra = set(private_by_id) - public_ids
    if extra:
        raise BlindPackageError("private judgements contain unknown query IDs: " + ", ".join(sorted(extra)))

    dataset = dataset_from_mapping(
        {
            "version": runner["version"],
            "judgement_visibility": "held_out",
            "memories": runner["memories"],
            "queries": combined_queries,
        },
        require_all_slices=True,
    )
    committed = runner.get("source_dataset_sha256")
    if dataset_sha256(dataset) != committed:
        raise BlindPackageError("reconstructed held-out dataset does not match source commitment")
    return dataset
