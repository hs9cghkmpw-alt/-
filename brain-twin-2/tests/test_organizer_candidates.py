from __future__ import annotations

from pathlib import Path

import pytest

from brain_twin_eval.organizer_candidates import (
    OrganizerCandidateError,
    OrganizerRunConfig,
    load_organizer_candidate_catalog,
)
from brain_twin_eval.organizer_gold import build_organizer_open_v1
from brain_twin_eval.organizer_runtime import run_organizer_candidate


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "evaluation_profiles" / "organizer_candidate_catalog_v1.json"


def _config(**overrides: object) -> OrganizerRunConfig:
    values: dict[str, object] = {
        "candidate_id": "candidate-a",
        "model_name": "example/model",
        "model_revision": "a" * 40,
        "prompt_sha256": "b" * 64,
        "schema_sha256": "c" * 64,
        "chat_template_sha256": "d" * 64,
        "runtime_backend": "transformers",
        "runtime_revision": "transformers-5.0.0",
        "quantization": "bf16-reference",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_new_tokens": 384,
        "seed": 17,
    }
    values.update(overrides)
    return OrganizerRunConfig(**values)  # type: ignore[arg-type]


def test_committed_organizer_catalog_is_fail_closed_and_has_expected_roles() -> None:
    candidates = load_organizer_candidate_catalog(CATALOG)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}

    assert {
        "qwen3.5-0.8b",
        "qwen3.5-2b",
        "qwen3.5-4b",
        "qwen3-4b-instruct-2507",
        "phi-4-mini-instruct",
        "gemma-3-4b-it",
    } == set(by_id)
    assert all(
        candidate.revision is None or len(candidate.revision) == 40
        for candidate in candidates
    )
    assert by_id["phi-4-mini-instruct"].runtime_status == "requires_remote_code_smoke"
    assert not by_id["phi-4-mini-instruct"].runnable_reference
    assert by_id["gemma-3-4b-it"].access == "gated"
    assert by_id["gemma-3-4b-it"].runtime_status == "research_only_gated"
    assert by_id["gemma-3-4b-it"].revision is None
    assert by_id["qwen3.5-2b"].runnable_reference


def test_run_config_hash_tracks_every_behavior_or_artifact_field() -> None:
    baseline = _config()
    variants = [
        _config(model_revision="e" * 40),
        _config(prompt_sha256="e" * 64),
        _config(schema_sha256="e" * 64),
        _config(chat_template_sha256="e" * 64),
        _config(runtime_backend="llama.cpp"),
        _config(runtime_revision="llama.cpp-999"),
        _config(quantization="q4_k_m"),
        _config(temperature=0.1),
        _config(top_p=0.95),
        _config(max_new_tokens=256),
        _config(seed=18),
        _config(extra_runtime_params=(("threads", "4"),)),
    ]
    assert all(item.sha256 != baseline.sha256 for item in variants)


def test_run_config_rejects_mutable_model_revision() -> None:
    with pytest.raises(OrganizerCandidateError, match="full immutable"):
        _config(model_revision="main")


def test_catalog_rejects_remote_code_candidate_marked_directly_runnable(tmp_path: Path) -> None:
    source = CATALOG.read_text(encoding="utf-8")
    source = source.replace(
        '"runtime_status": "requires_remote_code_smoke",',
        '"runtime_status": "pinned_reference",',
        1,
    )
    path = tmp_path / "catalog.json"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(OrganizerCandidateError, match="remote-code candidate"):
        load_organizer_candidate_catalog(path)


def test_catalog_rejects_gated_candidate_marked_auto_runnable(tmp_path: Path) -> None:
    source = CATALOG.read_text(encoding="utf-8")
    source = source.replace(
        '"runtime_status": "research_only_gated",',
        '"runtime_status": "pinned_reference",',
        1,
    ).replace(
        '"revision": null,\n      "license_id": "gemma"',
        f'"revision": "{"f" * 40}",\n      "license_id": "gemma"',
        1,
    )
    path = tmp_path / "catalog.json"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(OrganizerCandidateError, match="gated candidate"):
        load_organizer_candidate_catalog(path)


class _DeterministicGenerator:
    def generate(self, sample: dict[str, object]) -> dict[str, object]:
        sample_id = str(sample["sample_id"])
        return {
            "memory_worthy": True,
            "memory_type": "thought",
            "title": sample_id[:48],
            "topics": [],
            "entities": [],
            "event_date": None,
            "importance": 1,
            "confidence": 0.5,
            "link_candidates": [],
        }


class _AlternatingGenerator(_DeterministicGenerator):
    def __init__(self) -> None:
        self.counter = 0

    def generate(self, sample: dict[str, object]) -> dict[str, object]:
        payload = super().generate(sample)
        self.counter += 1
        payload["importance"] = 1 if self.counter % 2 else 2
        return payload


def test_runtime_evidence_records_identity_timing_rss_and_determinism() -> None:
    dataset = build_organizer_open_v1()
    evidence = run_organizer_candidate(
        dataset,
        _DeterministicGenerator(),
        _config(),
        determinism_sample_count=4,
        determinism_repeats=2,
    )

    assert evidence.dataset_sha256 == dataset.canonical_sha256
    assert evidence.organizer_config_sha256 == _config().sha256
    assert evidence.sample_count == 128
    assert len(evidence.predictions) == 128
    assert evidence.first_call_ms >= 0
    assert evidence.warm_latency_p95_ms >= evidence.warm_latency_median_ms or evidence.warm_latency_p95_ms >= 0
    assert evidence.determinism_sample_count == 4
    assert evidence.determinism_mismatch_count == 0
    assert evidence.rss_method_before
    assert evidence.rss_method_after


def test_runtime_evidence_detects_nondeterministic_candidate() -> None:
    dataset = build_organizer_open_v1()
    evidence = run_organizer_candidate(
        dataset,
        _AlternatingGenerator(),
        _config(),
        determinism_sample_count=3,
        determinism_repeats=2,
    )
    assert evidence.determinism_mismatch_count > 0


def test_runtime_determinism_settings_are_validated() -> None:
    dataset = build_organizer_open_v1()
    with pytest.raises(ValueError, match="non-negative"):
        run_organizer_candidate(dataset, _DeterministicGenerator(), _config(), determinism_sample_count=-1)
    with pytest.raises(ValueError, match="positive"):
        run_organizer_candidate(dataset, _DeterministicGenerator(), _config(), determinism_repeats=0)
