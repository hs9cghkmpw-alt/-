from __future__ import annotations

from brain_twin_eval.blind import (
    BlindPackageError,
    FORBIDDEN_PUBLIC_QUERY_KEYS,
    create_blind_packages,
    payload_sha256,
    reconstruct_held_out_dataset,
    validate_runner_payload,
)
from brain_twin_eval.dataset import (
    REQUIRED_SLICE_TAGS,
    EvaluationDataset,
    EvaluationMemory,
    EvaluationQuery,
    dataset_sha256,
)


def _dataset(*, visibility: str = "held_out") -> EvaluationDataset:
    return EvaluationDataset(
        version="heldout-v1",
        judgement_visibility=visibility,
        memories=(
            EvaluationMemory(
                memory_id="mem-1",
                title="架空の記憶",
                content="完全に合成された評価用の記憶です。",
                language_tags=("ja",),
                length_bucket="short",
                active=True,
            ),
        ),
        queries=(
            EvaluationQuery(
                query_id="q-1",
                text="あの架空の記憶",
                slice_tags=tuple(sorted(REQUIRED_SLICE_TAGS)),
                relevance={"mem-1": 3},
                must_hit_ids=("mem-1",),
                lexical_sufficient=False,
                adjudication_note="synthetic held-out test judgement",
                split="blind",
            ),
        ),
    )


def test_public_blind_package_contains_no_judgement_fields() -> None:
    packages = create_blind_packages(_dataset())
    query = packages.runner["queries"][0]
    assert FORBIDDEN_PUBLIC_QUERY_KEYS.isdisjoint(query)
    assert query == {"query_id": "q-1", "text": "あの架空の記憶", "split": "blind"}
    validate_runner_payload(packages.runner)


def test_private_package_reconstructs_identical_committed_dataset() -> None:
    original = _dataset()
    packages = create_blind_packages(original)
    rebuilt = reconstruct_held_out_dataset(packages.runner, packages.private_judgements)
    assert dataset_sha256(rebuilt) == dataset_sha256(original)
    assert rebuilt.judgement_visibility == "held_out"


def test_tampered_public_runner_is_rejected_by_private_commitment() -> None:
    packages = create_blind_packages(_dataset())
    tampered = dict(packages.runner)
    tampered["version"] = "tampered"
    try:
        reconstruct_held_out_dataset(tampered, packages.private_judgements)
    except BlindPackageError as exc:
        assert "do not match" in str(exc)
    else:
        raise AssertionError("expected BlindPackageError")


def test_open_dataset_cannot_be_packaged_as_formal_blind() -> None:
    try:
        create_blind_packages(_dataset(visibility="open"))
    except BlindPackageError as exc:
        assert "held_out" in str(exc)
    else:
        raise AssertionError("expected BlindPackageError")


def test_public_package_hash_is_deterministic() -> None:
    packages = create_blind_packages(_dataset())
    assert payload_sha256(packages.runner) == payload_sha256(packages.runner)
