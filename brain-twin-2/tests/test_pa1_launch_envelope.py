from __future__ import annotations

from brain_twin_eval.acceptance import (
    policy_from_mapping,
    retrieval_config_sha256,
)
from brain_twin_eval.blind import create_blind_packages, payload_sha256
from brain_twin_eval.dataset import (
    REQUIRED_SLICE_TAGS,
    EvaluationDataset,
    EvaluationMemory,
    EvaluationQuery,
)
from brain_twin_eval.launch_envelope import (
    LaunchEnvelopeError,
    build_launch_envelope,
    envelope_sha256,
    verify_envelope_context,
    verify_evidence_against_envelope,
    verify_manifest_against_envelope,
)
from brain_twin_eval.manifest import (
    ExperimentManifest,
    instruction_sha256,
)


def _runner():
    dataset = EvaluationDataset(
        version="heldout-v1",
        judgement_visibility="held_out",
        memories=(
            EvaluationMemory(
                "mem-1",
                "架空",
                "合成記憶",
                ("ja",),
                "short",
                True,
            ),
        ),
        queries=(
            EvaluationQuery(
                "q-1",
                "架空？",
                tuple(sorted(REQUIRED_SLICE_TAGS)),
                {"mem-1": 3},
                ("mem-1",),
                False,
                "private",
                "blind",
            ),
        ),
    )
    return create_blind_packages(dataset).runner


def _manifest():
    return {
        "experiment_id": "candidate",
        "timestamp_utc": "2026-08-29T00:00:00+00:00",
        "dataset_version": "heldout-v1",
        "dataset_sha256": "SOURCE",
        "dataset_judgement_visibility": "held_out",
        "git_commit": "b" * 40,
        "provider_label": "local-eval",
        "model_name": "org/model",
        "model_revision": "c" * 40,
        "instruction_id": "instruction-v1",
        "instruction_text_sha256": instruction_sha256(
            "query {query}"
        ),
        "dimension": 1024,
        "normalized": True,
        "document_template_version": "1",
        "backend_label": "evaluation_exact_dense",
        "backend_params": {
            "query_template_sha256": "d" * 64,
            "document_template_sha256": "e" * 64,
            "evaluation_k": 10,
            "warm_repeats": 30,
            "corpus_memory_count": 1,
        },
        "python_version": "3.12.10",
        "platform": "Windows",
        "random_seed": 0,
    }


def _policy(runner, manifest, *, warm=1.0, rss=2_000_000_000):
    manifest = dict(manifest)
    manifest["dataset_sha256"] = runner["source_dataset_sha256"]
    return policy_from_mapping(
        {
            "policy_id": "formal-v1",
            "dataset_version": runner["version"],
            "dataset_sha256": runner["source_dataset_sha256"],
            "evaluator_git_commit": "b" * 40,
            "expected_retrieval_config_sha256": retrieval_config_sha256(
                manifest
            ),
            "minimum_query_count": 1,
            "expected_warm_repeats": 30,
            "min_recall_at_5": 0.0,
            "min_mrr_at_10": 0.0,
            "min_ndcg_at_10": 0.0,
            "min_must_hit_at_5": 0.0,
            "max_false_positive_at_5": 1.0,
            "max_warm_p95_seconds": warm,
            "max_peak_rss_after_bytes": rss,
            "critical_slice_rules": [
                {
                    "slice_tag": "semantic_only",
                    "metric": "ndcg_at_10",
                    "comparator": "min",
                    "threshold": 0.0,
                }
            ],
        }
    )


def test_launch_envelope_binds_runner_policy_evaluator_and_retrieval_config() -> None:
    runner = _runner()
    manifest = _manifest()
    manifest["dataset_sha256"] = runner["source_dataset_sha256"]
    policy = _policy(runner, manifest)
    envelope = build_launch_envelope(
        runner,
        policy,
        cycle_id="cycle-001",
        created_utc="2026-08-29T00:00:00+00:00",
    )
    verify_envelope_context(
        envelope, runner_raw=runner, policy=policy
    )
    typed_manifest = ExperimentManifest(**manifest)
    verify_manifest_against_envelope(typed_manifest, envelope)
    assert envelope.evaluation_k == 10
    assert envelope.expected_warm_repeats == 30
    assert len(envelope_sha256(envelope)) == 64


def test_launch_envelope_rejects_model_config_change_before_blind_query_execution() -> None:
    runner = _runner()
    manifest = _manifest()
    manifest["dataset_sha256"] = runner["source_dataset_sha256"]
    policy = _policy(runner, manifest)
    envelope = build_launch_envelope(
        runner,
        policy,
        cycle_id="cycle-001",
        created_utc="2026-08-29T00:00:00+00:00",
    )
    changed = dict(manifest)
    changed["dimension"] = 768
    try:
        verify_manifest_against_envelope(changed, envelope)
    except LaunchEnvelopeError as exc:
        assert "retrieval configuration" in str(exc)
    else:
        raise AssertionError("expected LaunchEnvelopeError")


def test_ranking_evidence_must_carry_exact_launch_and_repository_commitments() -> None:
    runner = _runner()
    manifest = _manifest()
    manifest["dataset_sha256"] = runner["source_dataset_sha256"]
    policy = _policy(runner, manifest)
    envelope = build_launch_envelope(
        runner,
        policy,
        cycle_id="cycle-001",
        created_utc="2026-08-29T00:00:00+00:00",
    )
    evidence = {
        "launch_envelope_sha256": envelope_sha256(envelope),
        "runner_sha256": payload_sha256(runner),
        "source_dataset_sha256": runner["source_dataset_sha256"],
        "k": 10,
        "warm_repeats": 30,
        "repository_identity": {
            "head_sha": "b" * 40,
            "tracked_worktree_clean": True,
        },
        "manifest": manifest,
    }
    verify_evidence_against_envelope(evidence, envelope)

    evidence["repository_identity"]["tracked_worktree_clean"] = False
    try:
        verify_evidence_against_envelope(evidence, envelope)
    except LaunchEnvelopeError as exc:
        assert "clean tracked worktree" in str(exc)
    else:
        raise AssertionError("expected LaunchEnvelopeError")


def test_launch_envelope_cannot_be_created_from_incomplete_formal_policy() -> None:
    runner = _runner()
    manifest = _manifest()
    manifest["dataset_sha256"] = runner["source_dataset_sha256"]
    policy = _policy(runner, manifest, warm=None, rss=None)
    try:
        build_launch_envelope(runner, policy, cycle_id="cycle-001")
    except LaunchEnvelopeError as exc:
        assert "formal-ready" in str(exc)
    else:
        raise AssertionError("expected LaunchEnvelopeError")
