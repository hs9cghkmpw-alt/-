"""Fail-closed formal acceptance policy for organizer LLM selection."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from brain_twin_eval.organizer import OrganizerEvaluationResult
from brain_twin_eval.organizer_blind import (
    OrganizerBlindEvidence,
    OrganizerPrivateCommitment,
    OrganizerPrivateScore,
)


class OrganizerAcceptanceError(ValueError):
    pass


QUALITY_GATES: tuple[tuple[str, str, str], ...] = (
    ("min_schema_valid_rate", "schema_valid_rate", "min"),
    ("min_strict_record_accuracy", "strict_record_accuracy", "min"),
    ("min_memory_worthy_f1", "memory_worthy_f1", "min"),
    ("min_memory_type_accuracy", "memory_type_accuracy", "min"),
    ("min_topics_f1", "topics_f1", "min"),
    ("min_entities_f1", "entities_f1", "min"),
    ("max_entity_hallucination_rate", "entity_hallucination_rate", "max"),
    ("min_event_date_exact_rate", "event_date_exact_rate", "min"),
    ("min_event_date_null_accuracy", "event_date_null_accuracy", "min"),
    ("max_importance_mae", "importance_mae", "max"),
    ("min_importance_within_one_rate", "importance_within_one_rate", "min"),
    ("min_links_f1", "links_f1", "min"),
    ("max_confidence_brier", "confidence_brier", "max"),
)

RUNTIME_GATE_NAMES = (
    "max_determinism_mismatch_count",
    "max_warm_p95_ms",
    "max_peak_rss_bytes",
    "max_artifact_disk_bytes",
)

REQUIRED_THRESHOLD_NAMES = tuple(name for name, _, _ in QUALITY_GATES) + RUNTIME_GATE_NAMES


@dataclass(frozen=True)
class OrganizerCriticalSliceRule:
    slice_name: str
    metric: str
    comparator: str
    threshold: float

    def __post_init__(self) -> None:
        if not self.slice_name.strip():
            raise OrganizerAcceptanceError("critical slice name must not be blank")
        allowed_metrics = {metric for _, metric, _ in QUALITY_GATES}
        if self.metric not in allowed_metrics:
            raise OrganizerAcceptanceError(f"unsupported critical slice metric: {self.metric}")
        if self.comparator not in {"min", "max"}:
            raise OrganizerAcceptanceError("critical slice comparator must be min or max")
        _finite_number(self.threshold, "critical slice threshold")

    def canonical(self) -> dict[str, Any]:
        return {
            "slice_name": self.slice_name,
            "metric": self.metric,
            "comparator": self.comparator,
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class OrganizerAcceptancePolicy:
    status: str
    policy_version: str
    evaluator_commit: str
    organizer_config_sha256: str
    thresholds: Mapping[str, float | int | None]
    critical_slice_rules: tuple[OrganizerCriticalSliceRule, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"draft", "frozen"}:
            raise OrganizerAcceptanceError("policy status must be draft or frozen")
        if not self.policy_version.strip():
            raise OrganizerAcceptanceError("policy_version must not be blank")
        if not re.fullmatch(r"[0-9a-f]{40}", self.evaluator_commit):
            raise OrganizerAcceptanceError("evaluator_commit must be a full immutable 40-character SHA")
        _require_sha256(self.organizer_config_sha256, "organizer_config_sha256")
        if set(self.thresholds) != set(REQUIRED_THRESHOLD_NAMES):
            missing = sorted(set(REQUIRED_THRESHOLD_NAMES) - set(self.thresholds))
            extra = sorted(set(self.thresholds) - set(REQUIRED_THRESHOLD_NAMES))
            raise OrganizerAcceptanceError(f"policy threshold keys mismatch; missing={missing}, extra={extra}")
        for name, value in self.thresholds.items():
            if value is not None:
                _validate_threshold(name, value)
        if self.status == "frozen":
            missing_values = sorted(name for name, value in self.thresholds.items() if value is None)
            if missing_values:
                raise OrganizerAcceptanceError(f"frozen policy has unresolved thresholds: {missing_values}")
            if not self.critical_slice_rules:
                raise OrganizerAcceptanceError("frozen policy requires at least one critical slice rule")

    @property
    def is_complete(self) -> bool:
        return (
            self.status == "frozen"
            and all(value is not None for value in self.thresholds.values())
            and bool(self.critical_slice_rules)
        )

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy_version": self.policy_version,
            "evaluator_commit": self.evaluator_commit,
            "organizer_config_sha256": self.organizer_config_sha256,
            "thresholds": {key: self.thresholds[key] for key in sorted(self.thresholds)},
            "critical_slice_rules": [rule.canonical() for rule in self.critical_slice_rules],
        }

    @property
    def sha256(self) -> str:
        return _sha256_json(self.canonical_payload)


@dataclass(frozen=True)
class OrganizerLaunchEnvelope:
    cycle_id: str
    private_commitment_sha256: str
    private_dataset_sha256: str
    public_package_sha256: str
    organizer_config_sha256: str
    policy_sha256: str
    evaluator_commit: str
    sample_count: int

    @classmethod
    def create(
        cls,
        *,
        cycle_id: str,
        commitment: OrganizerPrivateCommitment,
        policy: OrganizerAcceptancePolicy,
        organizer_config_sha256: str,
    ) -> "OrganizerLaunchEnvelope":
        if not policy.is_complete:
            raise OrganizerAcceptanceError("formal launch requires a complete frozen organizer policy")
        if organizer_config_sha256 != policy.organizer_config_sha256:
            raise OrganizerAcceptanceError("launch organizer config does not match frozen policy")
        if not cycle_id.strip():
            raise OrganizerAcceptanceError("cycle_id must not be blank")
        return cls(
            cycle_id=cycle_id,
            private_commitment_sha256=commitment.sha256,
            private_dataset_sha256=commitment.private_dataset_sha256,
            public_package_sha256=commitment.public_package_sha256,
            organizer_config_sha256=organizer_config_sha256,
            policy_sha256=policy.sha256,
            evaluator_commit=policy.evaluator_commit,
            sample_count=commitment.sample_count,
        )

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "private_commitment_sha256": self.private_commitment_sha256,
            "private_dataset_sha256": self.private_dataset_sha256,
            "public_package_sha256": self.public_package_sha256,
            "organizer_config_sha256": self.organizer_config_sha256,
            "policy_sha256": self.policy_sha256,
            "evaluator_commit": self.evaluator_commit,
            "sample_count": self.sample_count,
        }

    @property
    def sha256(self) -> str:
        return _sha256_json(self.canonical_payload)


@dataclass(frozen=True)
class OrganizerAcceptanceDecision:
    verdict: str
    policy_sha256: str
    launch_envelope_sha256: str
    gates: Mapping[str, bool]
    critical_slice_gate: bool

    def to_public_dict(self) -> dict[str, Any]:
        """Redacted formal outcome: no sample IDs, slice names, predictions or scores."""
        return {
            "verdict": self.verdict,
            "policy_sha256": self.policy_sha256,
            "launch_envelope_sha256": self.launch_envelope_sha256,
            "gates": dict(self.gates),
            "critical_slice_gate": self.critical_slice_gate,
        }


def evaluate_organizer_formal_acceptance(
    *,
    policy: OrganizerAcceptancePolicy,
    envelope: OrganizerLaunchEnvelope,
    score: OrganizerPrivateScore,
    artifact_disk_bytes: int,
) -> OrganizerAcceptanceDecision:
    if not policy.is_complete:
        raise OrganizerAcceptanceError("formal acceptance requires complete frozen policy")
    if envelope.policy_sha256 != policy.sha256:
        raise OrganizerAcceptanceError("launch envelope policy hash mismatch")
    if envelope.organizer_config_sha256 != policy.organizer_config_sha256:
        raise OrganizerAcceptanceError("launch envelope config hash mismatch")
    if envelope.evaluator_commit != policy.evaluator_commit:
        raise OrganizerAcceptanceError("launch envelope evaluator commit mismatch")
    if isinstance(artifact_disk_bytes, bool) or not isinstance(artifact_disk_bytes, int) or artifact_disk_bytes < 0:
        raise OrganizerAcceptanceError("artifact_disk_bytes must be a non-negative integer")

    result = score.result
    evidence = score.evidence
    if result.judgement_visibility != "held_out":
        raise OrganizerAcceptanceError("formal acceptance requires held_out result")
    if result.dataset_sha256 != envelope.private_dataset_sha256:
        raise OrganizerAcceptanceError("held-out result dataset identity mismatch")
    if evidence.launch_envelope_sha256 != envelope.sha256:
        raise OrganizerAcceptanceError("blind evidence launch envelope mismatch")
    if evidence.public_package_sha256 != envelope.public_package_sha256:
        raise OrganizerAcceptanceError("blind evidence public package mismatch")
    if evidence.organizer_config_sha256 != envelope.organizer_config_sha256:
        raise OrganizerAcceptanceError("blind evidence organizer config mismatch")
    if evidence.sample_count != envelope.sample_count:
        raise OrganizerAcceptanceError("blind evidence sample count mismatch")

    gates: dict[str, bool] = {}
    for threshold_name, metric_name, direction in QUALITY_GATES:
        threshold = _resolved(policy, threshold_name)
        observed = _metric(result.overall, metric_name)
        gates[threshold_name] = observed >= threshold if direction == "min" else observed <= threshold

    gates["max_determinism_mismatch_count"] = (
        evidence.determinism_mismatch_count <= int(_resolved(policy, "max_determinism_mismatch_count"))
    )
    gates["max_warm_p95_ms"] = evidence.warm_latency_p95_ms <= _resolved(policy, "max_warm_p95_ms")
    peak_rss = evidence.peak_rss_after_bytes
    gates["max_peak_rss_bytes"] = peak_rss is not None and peak_rss <= _resolved(policy, "max_peak_rss_bytes")
    gates["max_artifact_disk_bytes"] = artifact_disk_bytes <= _resolved(policy, "max_artifact_disk_bytes")

    critical_ok = True
    for rule in policy.critical_slice_rules:
        slice_metrics = result.per_slice.get(rule.slice_name)
        if slice_metrics is None:
            critical_ok = False
            continue
        observed = _metric(slice_metrics, rule.metric)
        if rule.comparator == "min":
            critical_ok = critical_ok and observed >= rule.threshold
        else:
            critical_ok = critical_ok and observed <= rule.threshold

    verdict = "PASS" if all(gates.values()) and critical_ok else "FAIL"
    return OrganizerAcceptanceDecision(
        verdict=verdict,
        policy_sha256=policy.sha256,
        launch_envelope_sha256=envelope.sha256,
        gates=gates,
        critical_slice_gate=critical_ok,
    )


def draft_thresholds() -> dict[str, None]:
    """Explicit unresolved template. Do not substitute guessed thresholds."""
    return {name: None for name in REQUIRED_THRESHOLD_NAMES}


def _resolved(policy: OrganizerAcceptancePolicy, name: str) -> float:
    value = policy.thresholds[name]
    if value is None:  # should be impossible for a complete policy
        raise OrganizerAcceptanceError(f"unresolved threshold: {name}")
    return float(value)


def _metric(metrics: Mapping[str, Any], name: str) -> float:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrganizerAcceptanceError(f"formal metric is missing or non-numeric: {name}")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise OrganizerAcceptanceError(f"formal metric is non-finite: {name}")
    return number


def _validate_threshold(name: str, value: float | int) -> None:
    number = _finite_number(value, name)
    if name.startswith("min_") and name != "min_importance_within_one_rate":
        # min metrics in this policy are rates/F1/accuracy in [0,1].
        if not 0 <= number <= 1:
            raise OrganizerAcceptanceError(f"{name} must be in [0,1]")
    if name == "min_importance_within_one_rate" and not 0 <= number <= 1:
        raise OrganizerAcceptanceError(f"{name} must be in [0,1]")
    if name in {"max_entity_hallucination_rate", "max_confidence_brier"} and not 0 <= number <= 1:
        raise OrganizerAcceptanceError(f"{name} must be in [0,1]")
    if name == "max_importance_mae" and not 0 <= number <= 4:
        raise OrganizerAcceptanceError(f"{name} must be in [0,4]")
    if name in {"max_warm_p95_ms", "max_peak_rss_bytes", "max_artifact_disk_bytes"} and number <= 0:
        raise OrganizerAcceptanceError(f"{name} must be > 0")
    if name == "max_determinism_mismatch_count":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OrganizerAcceptanceError(f"{name} must be a non-negative integer")


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrganizerAcceptanceError(f"{field} must be numeric")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise OrganizerAcceptanceError(f"{field} must be finite")
    return number


def _require_sha256(value: str, field: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise OrganizerAcceptanceError(f"{field} must be a lowercase SHA-256 digest")


def _sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
