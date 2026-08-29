from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .acceptance import AcceptancePolicy, policy_sha256, retrieval_config_sha256
from .blind import payload_sha256, validate_runner_payload
from .manifest import ExperimentManifest, manifest_to_dict


class LaunchEnvelopeError(ValueError):
    pass


@dataclass(frozen=True)
class BlindLaunchEnvelope:
    schema: int
    cycle_id: str
    runner_sha256: str
    source_dataset_sha256: str
    dataset_version: str
    policy_sha256: str
    expected_retrieval_config_sha256: str
    evaluator_git_commit: str
    evaluation_k: int
    expected_warm_repeats: int
    model_artifact_manifest_sha256: str | None
    created_utc: str


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LaunchEnvelopeError(f"{field} must be a non-empty string")
    return value


def _hex(value: Any, length: int, field: str) -> str:
    text = _nonempty(value, field).lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise LaunchEnvelopeError(
            f"{field} must be a {length}-character hexadecimal SHA"
        )
    return text


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LaunchEnvelopeError(f"{field} must be a positive integer")
    return value


def envelope_sha256(envelope: BlindLaunchEnvelope) -> str:
    canonical = json.dumps(
        asdict(envelope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_launch_envelope(
    runner_raw: Mapping[str, Any],
    policy: AcceptancePolicy,
    *,
    cycle_id: str,
    model_artifact_manifest_sha256: str | None = None,
    created_utc: str | None = None,
) -> BlindLaunchEnvelope:
    if not policy.formal_ready:
        raise LaunchEnvelopeError(
            "acceptance policy is not formal-ready; freeze runtime budgets, "
            "warm-repeat count and at least one critical-slice rule first"
        )

    validate_runner_payload(runner_raw)
    runner_sha = payload_sha256(runner_raw)
    source_sha = _hex(
        runner_raw.get("source_dataset_sha256"),
        64,
        "runner.source_dataset_sha256",
    )
    version = _nonempty(runner_raw.get("version"), "runner.version")
    if source_sha != policy.dataset_sha256:
        raise LaunchEnvelopeError(
            "acceptance policy dataset SHA does not match blind runner source commitment"
        )
    if version != policy.dataset_version:
        raise LaunchEnvelopeError(
            "acceptance policy dataset version does not match blind runner"
        )

    artifact_sha = None
    if model_artifact_manifest_sha256 is not None:
        artifact_sha = _hex(
            model_artifact_manifest_sha256,
            64,
            "model_artifact_manifest_sha256",
        )

    return BlindLaunchEnvelope(
        schema=1,
        cycle_id=_nonempty(cycle_id, "cycle_id"),
        runner_sha256=runner_sha,
        source_dataset_sha256=source_sha,
        dataset_version=version,
        policy_sha256=policy_sha256(policy),
        expected_retrieval_config_sha256=policy.expected_retrieval_config_sha256,
        evaluator_git_commit=policy.evaluator_git_commit,
        evaluation_k=10,
        expected_warm_repeats=policy.expected_warm_repeats,
        model_artifact_manifest_sha256=artifact_sha,
        created_utc=created_utc or datetime.now(timezone.utc).isoformat(),
    )


def envelope_from_mapping(raw: Mapping[str, Any]) -> BlindLaunchEnvelope:
    if not isinstance(raw, Mapping) or raw.get("schema") != 1:
        raise LaunchEnvelopeError(
            "unsupported blind launch envelope schema"
        )

    artifact = raw.get("model_artifact_manifest_sha256")
    if artifact is not None:
        artifact = _hex(
            artifact, 64, "model_artifact_manifest_sha256"
        )

    return BlindLaunchEnvelope(
        schema=1,
        cycle_id=_nonempty(raw.get("cycle_id"), "cycle_id"),
        runner_sha256=_hex(
            raw.get("runner_sha256"), 64, "runner_sha256"
        ),
        source_dataset_sha256=_hex(
            raw.get("source_dataset_sha256"),
            64,
            "source_dataset_sha256",
        ),
        dataset_version=_nonempty(
            raw.get("dataset_version"), "dataset_version"
        ),
        policy_sha256=_hex(
            raw.get("policy_sha256"), 64, "policy_sha256"
        ),
        expected_retrieval_config_sha256=_hex(
            raw.get("expected_retrieval_config_sha256"),
            64,
            "expected_retrieval_config_sha256",
        ),
        evaluator_git_commit=_hex(
            raw.get("evaluator_git_commit"),
            40,
            "evaluator_git_commit",
        ),
        evaluation_k=_positive_int(
            raw.get("evaluation_k"), "evaluation_k"
        ),
        expected_warm_repeats=_positive_int(
            raw.get("expected_warm_repeats"),
            "expected_warm_repeats",
        ),
        model_artifact_manifest_sha256=artifact,
        created_utc=_nonempty(raw.get("created_utc"), "created_utc"),
    )


def envelope_to_dict(
    envelope: BlindLaunchEnvelope,
) -> dict[str, Any]:
    return asdict(envelope)


def verify_envelope_context(
    envelope: BlindLaunchEnvelope,
    *,
    runner_raw: Mapping[str, Any],
    policy: AcceptancePolicy,
) -> None:
    validate_runner_payload(runner_raw)
    if envelope.runner_sha256 != payload_sha256(runner_raw):
        raise LaunchEnvelopeError(
            "launch envelope does not match this blind runner package"
        )
    if (
        envelope.source_dataset_sha256 != policy.dataset_sha256
        or envelope.dataset_version != policy.dataset_version
    ):
        raise LaunchEnvelopeError(
            "launch envelope dataset identity does not match acceptance policy"
        )
    if envelope.policy_sha256 != policy_sha256(policy):
        raise LaunchEnvelopeError(
            "launch envelope policy commitment mismatch"
        )
    if (
        envelope.expected_retrieval_config_sha256
        != policy.expected_retrieval_config_sha256
    ):
        raise LaunchEnvelopeError(
            "launch envelope retrieval-config commitment mismatch"
        )
    if envelope.evaluator_git_commit != policy.evaluator_git_commit:
        raise LaunchEnvelopeError(
            "launch envelope evaluator Git commitment mismatch"
        )
    if envelope.evaluation_k != 10:
        raise LaunchEnvelopeError(
            "formal blind launch envelope must use evaluation_k=10"
        )
    if envelope.expected_warm_repeats != policy.expected_warm_repeats:
        raise LaunchEnvelopeError(
            "launch envelope warm-repeat commitment mismatch"
        )


def verify_manifest_against_envelope(
    manifest: ExperimentManifest | Mapping[str, Any],
    envelope: BlindLaunchEnvelope,
) -> None:
    manifest_raw = (
        manifest_to_dict(manifest)
        if isinstance(manifest, ExperimentManifest)
        else dict(manifest)
    )
    if manifest_raw.get("git_commit") != envelope.evaluator_git_commit:
        raise LaunchEnvelopeError(
            "candidate manifest Git commit does not match launch envelope"
        )
    if (
        manifest_raw.get("dataset_sha256")
        != envelope.source_dataset_sha256
    ):
        raise LaunchEnvelopeError(
            "candidate manifest dataset SHA does not match launch envelope"
        )
    if manifest_raw.get("dataset_version") != envelope.dataset_version:
        raise LaunchEnvelopeError(
            "candidate manifest dataset version does not match launch envelope"
        )
    actual_config = retrieval_config_sha256(manifest_raw)
    if actual_config != envelope.expected_retrieval_config_sha256:
        raise LaunchEnvelopeError(
            "candidate retrieval configuration does not match frozen launch envelope"
        )


def verify_evidence_against_envelope(
    raw: Mapping[str, Any],
    envelope: BlindLaunchEnvelope,
) -> None:
    if not isinstance(raw, Mapping):
        raise LaunchEnvelopeError(
            "ranking evidence root must be an object"
        )
    if raw.get("launch_envelope_sha256") != envelope_sha256(envelope):
        raise LaunchEnvelopeError(
            "ranking evidence launch-envelope commitment mismatch"
        )
    if raw.get("runner_sha256") != envelope.runner_sha256:
        raise LaunchEnvelopeError(
            "ranking evidence runner commitment mismatch"
        )
    if (
        raw.get("source_dataset_sha256")
        != envelope.source_dataset_sha256
    ):
        raise LaunchEnvelopeError(
            "ranking evidence dataset commitment mismatch"
        )
    if raw.get("k") != envelope.evaluation_k:
        raise LaunchEnvelopeError(
            "ranking evidence evaluation-k commitment mismatch"
        )
    if raw.get("warm_repeats") != envelope.expected_warm_repeats:
        raise LaunchEnvelopeError(
            "ranking evidence warm-repeat commitment mismatch"
        )

    identity = raw.get("repository_identity")
    if not isinstance(identity, Mapping):
        raise LaunchEnvelopeError(
            "ranking evidence repository identity is missing"
        )
    if identity.get("head_sha") != envelope.evaluator_git_commit:
        raise LaunchEnvelopeError(
            "ranking evidence repository HEAD mismatch"
        )
    if identity.get("tracked_worktree_clean") is not True:
        raise LaunchEnvelopeError(
            "ranking evidence was not produced from a clean tracked worktree"
        )

    manifest = raw.get("manifest")
    if not isinstance(manifest, Mapping):
        raise LaunchEnvelopeError(
            "ranking evidence manifest must be an object"
        )
    verify_manifest_against_envelope(manifest, envelope)
