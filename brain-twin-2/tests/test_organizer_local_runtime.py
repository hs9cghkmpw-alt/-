from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain_twin_eval.organizer_candidates import OrganizerCandidateError, load_organizer_candidate_catalog
from brain_twin_eval.organizer_local_runtime import (
    PIN_MANIFEST,
    build_organizer_run_config,
    load_and_verify_pin,
    run_public_package,
)


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "evaluation_profiles" / "organizer_candidate_catalog_v1.json"
PROMPT = ROOT / "evaluation_profiles" / "organizer_system_prompt_v1.txt"
SCHEMA = ROOT / "evaluation_profiles" / "organizer_output_schema_v1.json"


class _FakeGenerator:
    chat_template_sha256 = "a" * 64
    runtime_revision = "transformers=test;torch=test"
    quantization = "none"

    def __init__(self, *, drift: bool = False) -> None:
        self.drift = drift
        self.calls: dict[str, int] = {}

    def generate(self, sample: dict[str, object]) -> str:
        assert "gold" not in sample
        assert "slices" not in sample
        sample_id = str(sample["sample_id"])
        count = self.calls.get(sample_id, 0)
        self.calls[sample_id] = count + 1
        title = sample_id if not self.drift or count == 0 else sample_id + " drift"
        return json.dumps(
            {
                "memory_worthy": True,
                "memory_type": "thought",
                "title": title[:48],
                "topics": [],
                "entities": [],
                "event_date": None,
                "importance": 1,
                "confidence": 0.5,
                "link_candidates": [],
            },
            ensure_ascii=False,
        )


def _candidate(candidate_id: str = "qwen3.5-0.8b"):
    candidates = load_organizer_candidate_catalog(CATALOG)
    return next(item for item in candidates if item.candidate_id == candidate_id)


def _write_pin(model_dir: Path, candidate) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "weights.bin").write_bytes(b"1234")
    (model_dir / PIN_MANIFEST).write_text(
        json.dumps(
            {
                "schema": 1,
                "candidate_id": candidate.candidate_id,
                "repo_id": candidate.model_name,
                "revision": candidate.revision,
                "runtime_status": candidate.runtime_status,
                "trust_remote_code": candidate.trust_remote_code,
                "runtime_policy": "evaluation-loads-local-files-only",
            }
        ),
        encoding="utf-8",
    )


def test_pin_manifest_must_match_exact_candidate_revision(tmp_path: Path) -> None:
    candidate = _candidate()
    model_dir = tmp_path / "model"
    _write_pin(model_dir, candidate)
    payload = load_and_verify_pin(model_dir, candidate)
    assert payload["revision"] == candidate.revision

    payload["revision"] = "0" * 40
    (model_dir / PIN_MANIFEST).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OrganizerCandidateError, match="revision"):
        load_and_verify_pin(model_dir, candidate)


def test_direct_runtime_rejects_remote_code_candidate_even_with_manifest(tmp_path: Path) -> None:
    candidate = _candidate("phi-4-mini-instruct")
    model_dir = tmp_path / "model"
    _write_pin(model_dir, candidate)
    with pytest.raises(OrganizerCandidateError, match="not authorized"):
        load_and_verify_pin(model_dir, candidate)


def test_run_config_binds_prompt_schema_chat_template_and_runtime() -> None:
    candidate = _candidate()
    generator = _FakeGenerator()
    config = build_organizer_run_config(
        candidate=candidate,
        generator=generator,
        prompt_path=PROMPT,
        schema_path=SCHEMA,
        max_new_tokens=512,
        seed=0,
    )
    assert config.chat_template_sha256 == generator.chat_template_sha256
    assert config.runtime_backend == "transformers-cpu-local-only"
    assert config.runtime_revision == generator.runtime_revision
    assert ("enable_thinking", "false") in config.extra_runtime_params
    assert ("do_sample", "false") in config.extra_runtime_params


def test_public_runner_records_resource_and_determinism_without_gold(tmp_path: Path) -> None:
    candidate = _candidate()
    model_dir = tmp_path / "model"
    _write_pin(model_dir, candidate)
    generator = _FakeGenerator()
    config = build_organizer_run_config(
        candidate=candidate,
        generator=generator,
        prompt_path=PROMPT,
        schema_path=SCHEMA,
        max_new_tokens=64,
        seed=0,
    )
    package = {
        "version": "open-test",
        "samples": [
            {"sample_id": "s1", "raw_text": "メモ", "created_at": "2026-08-29T09:00:00+09:00", "context_memories": []},
            {"sample_id": "s2", "raw_text": "別メモ", "created_at": "2026-08-29T09:01:00+09:00", "context_memories": []},
        ],
    }
    predictions, evidence = run_public_package(
        public_package=package,
        generator=generator,
        candidate=candidate,
        config=config,
        model_dir=model_dir,
        determinism_checked_samples=2,
        determinism_repeats=2,
    )
    assert set(predictions) == {"s1", "s2"}
    assert evidence.sample_count == 2
    assert evidence.deterministic is True
    assert evidence.model_disk_bytes >= 4
    assert evidence.organizer_config_sha256 == config.sha256


def test_public_runner_detects_generation_drift(tmp_path: Path) -> None:
    candidate = _candidate()
    model_dir = tmp_path / "model"
    _write_pin(model_dir, candidate)
    generator = _FakeGenerator(drift=True)
    config = build_organizer_run_config(
        candidate=candidate,
        generator=generator,
        prompt_path=PROMPT,
        schema_path=SCHEMA,
        max_new_tokens=64,
        seed=0,
    )
    _, evidence = run_public_package(
        public_package={
            "samples": [
                {"sample_id": "s1", "raw_text": "メモ", "created_at": "2026-08-29T09:00:00+09:00", "context_memories": []}
            ]
        },
        generator=generator,
        candidate=candidate,
        config=config,
        model_dir=model_dir,
        determinism_checked_samples=1,
        determinism_repeats=2,
    )
    assert evidence.deterministic is False


def test_public_runner_rejects_gold_or_slice_leakage(tmp_path: Path) -> None:
    candidate = _candidate()
    generator = _FakeGenerator()
    config = build_organizer_run_config(
        candidate=candidate,
        generator=generator,
        prompt_path=PROMPT,
        schema_path=SCHEMA,
        max_new_tokens=64,
        seed=0,
    )
    with pytest.raises(OrganizerCandidateError, match="gold or slices"):
        run_public_package(
            public_package={"samples": [{"sample_id": "s1", "gold": {}, "slices": []}]},
            generator=generator,
            candidate=candidate,
            config=config,
            model_dir=tmp_path,
        )
