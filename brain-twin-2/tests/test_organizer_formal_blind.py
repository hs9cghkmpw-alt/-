from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from brain_twin_eval.organizer import (
    OrganizerContextMemory,
    OrganizerDataset,
    OrganizerSample,
    oracle_predictions,
)
from brain_twin_eval.organizer_blind import (
    OrganizerBlindError,
    assert_private_artifact_outside_repo,
    build_organizer_blind_packages,
    run_organizer_blind_package,
    score_organizer_blind_evidence,
)
from brain_twin_eval.organizer_candidates import OrganizerRunConfig
from brain_twin_eval.organizer_formal import (
    OrganizerAcceptanceError,
    OrganizerAcceptancePolicy,
    OrganizerCriticalSliceRule,
    OrganizerLaunchEnvelope,
    REQUIRED_THRESHOLD_NAMES,
    draft_thresholds,
    evaluate_organizer_formal_acceptance,
)
from brain_twin_eval.organizer_gold_v2 import build_organizer_open_v2


def _held_out_dataset() -> OrganizerDataset:
    open_dataset = build_organizer_open_v2()
    return OrganizerDataset(
        version="organizer-held-out-test",
        judgement_visibility="held_out",
        samples=open_dataset.samples,
    )


def _config(candidate_id: str = "qwen-test") -> OrganizerRunConfig:
    return OrganizerRunConfig(
        candidate_id=candidate_id,
        model_name="example/model",
        model_revision="a" * 40,
        prompt_sha256="b" * 64,
        schema_sha256="c" * 64,
        chat_template_sha256="d" * 64,
        runtime_backend="test-runtime",
        runtime_revision="test-runtime-1",
        quantization="reference",
        temperature=0.0,
        top_p=1.0,
        max_new_tokens=384,
        seed=17,
    )


def _thresholds() -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    for name in REQUIRED_THRESHOLD_NAMES:
        if name == "max_determinism_mismatch_count":
            result[name] = 0
        elif name in {"max_warm_p95_ms", "max_peak_rss_bytes", "max_artifact_disk_bytes"}:
            result[name] = 1_000_000_000
        elif name == "max_importance_mae":
            result[name] = 4.0
        elif name.startswith("max_"):
            result[name] = 1.0
        else:
            result[name] = 0.0
    return result


def _policy(config: OrganizerRunConfig | None = None) -> OrganizerAcceptancePolicy:
    config = config or _config()
    return OrganizerAcceptancePolicy(
        status="frozen",
        policy_version="organizer-formal-test-v1",
        evaluator_commit="e" * 40,
        organizer_config_sha256=config.sha256,
        thresholds=_thresholds(),
        critical_slice_rules=(
            OrganizerCriticalSliceRule(
                slice_name="relative_date",
                metric="schema_valid_rate",
                comparator="min",
                threshold=0.0,
            ),
        ),
    )


class _OracleGenerator:
    def __init__(self, outputs: dict[str, dict[str, object]]) -> None:
        self.outputs = outputs

    def generate(self, sample: dict[str, object]) -> dict[str, object]:
        output = self.outputs[str(sample["sample_id"])]
        return {key: value for key, value in output.items()}


def _perfect_private_score():
    dataset = _held_out_dataset()
    config = _config()
    public, commitment = build_organizer_blind_packages(dataset)
    policy = _policy(config)
    envelope = OrganizerLaunchEnvelope.create(
        cycle_id="cycle-test-001",
        commitment=commitment,
        policy=policy,
        organizer_config_sha256=config.sha256,
    )
    evidence = run_organizer_blind_package(
        public,
        _OracleGenerator(oracle_predictions(dataset)),
        config,
        launch_envelope_sha256=envelope.sha256,
        determinism_sample_count=4,
        determinism_repeats=2,
    )
    evidence = replace(
        evidence,
        warm_latency_p95_ms=1.0,
        peak_rss_after_bytes=100,
        peak_rss_before_bytes=50,
        peak_rss_growth_bytes=50,
        determinism_mismatch_count=0,
    )
    score = score_organizer_blind_evidence(dataset, commitment, evidence)
    return dataset, config, public, commitment, policy, envelope, score


def test_public_blind_package_contains_no_gold_slices_or_private_dataset_hash() -> None:
    dataset = _held_out_dataset()
    public, commitment = build_organizer_blind_packages(dataset)
    serialized = str(public.canonical_payload)
    assert "gold" not in serialized
    assert "slices" not in serialized
    assert commitment.private_dataset_sha256 not in serialized
    assert public.sample_count == len(dataset.samples)


def test_open_dataset_cannot_be_used_for_formal_blind_package() -> None:
    with pytest.raises(OrganizerBlindError, match="held_out"):
        build_organizer_blind_packages(build_organizer_open_v2())


def test_public_package_hash_is_deterministic() -> None:
    dataset = _held_out_dataset()
    first, first_commitment = build_organizer_blind_packages(dataset)
    second, second_commitment = build_organizer_blind_packages(dataset)
    assert first.sha256 == second.sha256
    assert first_commitment.sha256 == second_commitment.sha256


def test_formal_blind_rejects_naive_or_timezone_less_created_at() -> None:
    base = _held_out_dataset()
    sample = replace(base.samples[0], created_at="2026-08-10T10:00:00")
    broken = OrganizerDataset(
        version="broken-time",
        judgement_visibility="held_out",
        samples=(sample,),
    )
    with pytest.raises(OrganizerBlindError, match="timezone"):
        build_organizer_blind_packages(broken)


def test_formal_blind_validates_context_memory_shape_even_if_core_dataclass_is_permissive() -> None:
    base = _held_out_dataset()
    source = base.samples[0]
    sample = OrganizerSample(
        sample_id="broken-context",
        raw_text=source.raw_text,
        created_at=source.created_at,
        gold=replace(source.gold, link_candidates=()),
        slices=source.slices,
        context_memories=(OrganizerContextMemory(memory_id="", title="", summary=""),),
    )
    broken = OrganizerDataset(
        version="broken-context",
        judgement_visibility="held_out",
        samples=(sample,),
    )
    with pytest.raises(OrganizerBlindError, match="memory_id"):
        build_organizer_blind_packages(broken)


def test_private_artifacts_are_rejected_inside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "private" / "gold.json"
    assert_private_artifact_outside_repo(repo, outside)
    with pytest.raises(OrganizerBlindError, match="outside repository"):
        assert_private_artifact_outside_repo(repo, repo / "private" / "gold.json")


def test_blind_evidence_is_scored_only_when_exact_sample_set_and_commitment_match() -> None:
    dataset, _, _, commitment, _, _, score = _perfect_private_score()
    evidence = score.evidence
    missing = dict(evidence.predictions)
    missing.pop(next(iter(missing)))
    tampered = replace(evidence, predictions=missing)
    with pytest.raises(OrganizerBlindError, match="exact held-out sample IDs"):
        score_organizer_blind_evidence(dataset, commitment, tampered)


def test_draft_policy_is_explicitly_incomplete_and_cannot_launch() -> None:
    config = _config()
    policy = OrganizerAcceptancePolicy(
        status="draft",
        policy_version="draft-v1",
        evaluator_commit="e" * 40,
        organizer_config_sha256=config.sha256,
        thresholds=draft_thresholds(),
    )
    assert not policy.is_complete
    _, commitment = build_organizer_blind_packages(_held_out_dataset())
    with pytest.raises(OrganizerAcceptanceError, match="complete frozen"):
        OrganizerLaunchEnvelope.create(
            cycle_id="cycle-draft",
            commitment=commitment,
            policy=policy,
            organizer_config_sha256=config.sha256,
        )


def test_frozen_policy_rejects_unresolved_thresholds() -> None:
    config = _config()
    with pytest.raises(OrganizerAcceptanceError, match="unresolved thresholds"):
        OrganizerAcceptancePolicy(
            status="frozen",
            policy_version="bad",
            evaluator_commit="e" * 40,
            organizer_config_sha256=config.sha256,
            thresholds=draft_thresholds(),
            critical_slice_rules=(
                OrganizerCriticalSliceRule("relative_date", "schema_valid_rate", "min", 0.0),
            ),
        )


def test_policy_hash_changes_with_threshold_or_critical_rule() -> None:
    baseline = _policy()
    changed_thresholds = dict(_thresholds())
    changed_thresholds["min_schema_valid_rate"] = 0.5
    changed = OrganizerAcceptancePolicy(
        status="frozen",
        policy_version=baseline.policy_version,
        evaluator_commit=baseline.evaluator_commit,
        organizer_config_sha256=baseline.organizer_config_sha256,
        thresholds=changed_thresholds,
        critical_slice_rules=baseline.critical_slice_rules,
    )
    changed_rule = OrganizerAcceptancePolicy(
        status="frozen",
        policy_version=baseline.policy_version,
        evaluator_commit=baseline.evaluator_commit,
        organizer_config_sha256=baseline.organizer_config_sha256,
        thresholds=baseline.thresholds,
        critical_slice_rules=(
            OrganizerCriticalSliceRule("relative_date", "schema_valid_rate", "min", 0.5),
        ),
    )
    assert changed.sha256 != baseline.sha256
    assert changed_rule.sha256 != baseline.sha256


def test_launch_rejects_different_organizer_config_after_policy_freeze() -> None:
    config = _config()
    policy = _policy(config)
    _, commitment = build_organizer_blind_packages(_held_out_dataset())
    with pytest.raises(OrganizerAcceptanceError, match="config"):
        OrganizerLaunchEnvelope.create(
            cycle_id="cycle-mismatch",
            commitment=commitment,
            policy=policy,
            organizer_config_sha256=_config("different").sha256,
        )


def test_perfect_held_out_evidence_passes_permissive_test_policy() -> None:
    _, _, _, _, policy, envelope, score = _perfect_private_score()
    decision = evaluate_organizer_formal_acceptance(
        policy=policy,
        envelope=envelope,
        score=score,
        artifact_disk_bytes=100,
    )
    assert decision.verdict == "PASS"
    assert all(decision.gates.values())
    assert decision.critical_slice_gate is True


def test_hallucination_gate_can_fail_formal_acceptance() -> None:
    dataset, config, public, commitment, _, _, _ = _perfect_private_score()
    thresholds = _thresholds()
    thresholds["max_entity_hallucination_rate"] = 0.0
    policy = OrganizerAcceptancePolicy(
        status="frozen",
        policy_version="strict-hallucination",
        evaluator_commit="e" * 40,
        organizer_config_sha256=config.sha256,
        thresholds=thresholds,
        critical_slice_rules=(
            OrganizerCriticalSliceRule("relative_date", "schema_valid_rate", "min", 0.0),
        ),
    )
    envelope = OrganizerLaunchEnvelope.create(
        cycle_id="cycle-hallucination",
        commitment=commitment,
        policy=policy,
        organizer_config_sha256=config.sha256,
    )
    predictions = oracle_predictions(dataset)
    target = next(sample for sample in dataset.samples if sample.gold.entities)
    predictions[target.sample_id]["entities"] = list(predictions[target.sample_id]["entities"]) + [
        {"name": "捏造エンティティXYZ", "confidence": 0.99}
    ]
    evidence = run_organizer_blind_package(
        public,
        _OracleGenerator(predictions),
        config,
        launch_envelope_sha256=envelope.sha256,
        determinism_sample_count=2,
    )
    evidence = replace(evidence, peak_rss_after_bytes=100, warm_latency_p95_ms=1.0)
    score = score_organizer_blind_evidence(dataset, commitment, evidence)
    decision = evaluate_organizer_formal_acceptance(
        policy=policy,
        envelope=envelope,
        score=score,
        artifact_disk_bytes=100,
    )
    assert decision.verdict == "FAIL"
    assert decision.gates["max_entity_hallucination_rate"] is False


def test_determinism_and_resource_gates_fail_closed() -> None:
    _, _, _, _, policy, envelope, score = _perfect_private_score()
    bad_evidence = replace(
        score.evidence,
        determinism_mismatch_count=1,
        warm_latency_p95_ms=2_000_000_000.0,
        peak_rss_after_bytes=None,
    )
    bad_score = replace(score, evidence=bad_evidence)
    decision = evaluate_organizer_formal_acceptance(
        policy=policy,
        envelope=envelope,
        score=bad_score,
        artifact_disk_bytes=2_000_000_000,
    )
    assert decision.verdict == "FAIL"
    assert decision.gates["max_determinism_mismatch_count"] is False
    assert decision.gates["max_warm_p95_ms"] is False
    assert decision.gates["max_peak_rss_bytes"] is False
    assert decision.gates["max_artifact_disk_bytes"] is False


def test_public_decision_redacts_scores_slices_samples_and_predictions() -> None:
    _, _, _, _, policy, envelope, score = _perfect_private_score()
    decision = evaluate_organizer_formal_acceptance(
        policy=policy,
        envelope=envelope,
        score=score,
        artifact_disk_bytes=100,
    ).to_public_dict()
    serialized = str(decision)
    assert "predictions" not in serialized
    assert "sample_id" not in serialized
    assert "relative_date" not in serialized
    assert "per_slice" not in serialized
    assert "overall" not in serialized
    assert set(decision) == {
        "verdict",
        "policy_sha256",
        "launch_envelope_sha256",
        "gates",
        "critical_slice_gate",
    }


def test_evidence_from_different_launch_is_rejected() -> None:
    _, _, _, _, policy, envelope, score = _perfect_private_score()
    tampered = replace(score.evidence, launch_envelope_sha256="f" * 64)
    with pytest.raises(OrganizerAcceptanceError, match="launch envelope"):
        evaluate_organizer_formal_acceptance(
            policy=policy,
            envelope=envelope,
            score=replace(score, evidence=tampered),
            artifact_disk_bytes=100,
        )
