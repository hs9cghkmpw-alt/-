from __future__ import annotations

import json
from collections import Counter

from brain_twin_eval.dataset import REQUIRED_SLICE_TAGS, dataset_from_mapping, dataset_sha256
from brain_twin_eval.open_gold_v2 import VERSION, build_open_gold_v2


def test_open_gold_v2_is_deterministic_and_valid():
    first = build_open_gold_v2()
    second = build_open_gold_v2()
    assert first == second
    assert first["version"] == VERSION

    first_dataset = dataset_from_mapping(first)
    second_dataset = dataset_from_mapping(second)
    assert dataset_sha256(first_dataset) == dataset_sha256(second_dataset)


def test_open_gold_v2_contract_counts_and_split():
    dataset = dataset_from_mapping(build_open_gold_v2())

    assert len(dataset.memories) == 360
    assert len(dataset.queries) == 120
    assert len(dataset.queries_for_split("dev")) == 80
    assert len(dataset.queries_for_split("blind")) == 40
    assert dataset.judgement_visibility == "open"
    assert dataset.acceptance_blind_ready is False


def test_open_gold_v2_has_required_slices_and_challenging_negatives():
    dataset = dataset_from_mapping(build_open_gold_v2())
    tags = Counter(tag for query in dataset.queries for tag in query.slice_tags)

    for tag in REQUIRED_SLICE_TAGS:
        assert tags[tag] > 0

    assert tags["hard_negative"] == 10
    assert tags["semantic_only"] >= 50
    assert tags["short_query"] >= 20
    assert tags["japanese_english_mixed"] >= 20
    assert tags["long_memory"] >= 10

    distractors = [memory for memory in dataset.memories if "周辺メモ" in memory.title]
    assert len(distractors) == 300
    assert sum(not memory.active for memory in dataset.memories) == 5


def test_open_gold_v2_long_memories_and_positive_refs_are_safe():
    dataset = dataset_from_mapping(build_open_gold_v2())
    active = {memory.memory_id: memory.active for memory in dataset.memories}
    long_memories = [memory for memory in dataset.memories if memory.length_bucket == "long"]

    assert len(long_memories) == 5
    assert min(len(memory.content) for memory in long_memories) >= 1500

    for query in dataset.queries:
        for memory_id, grade in query.relevance.items():
            if grade > 0:
                assert active[memory_id] is True
        for memory_id in query.must_hit_ids:
            assert query.relevance[memory_id] > 0


def test_open_gold_v2_contains_no_user_vault_paths_or_obvious_personal_identifiers():
    text = json.dumps(build_open_gold_v2(), ensure_ascii=False)
    forbidden = (
        "C:\\Users\\",
        "/Users/",
        "/home/",
        "@gmail.com",
        "@icloud.com",
        "hs9cghkmpw-alt",
    )
    for value in forbidden:
        assert value not in text
