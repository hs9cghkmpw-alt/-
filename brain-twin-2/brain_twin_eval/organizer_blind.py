"""Organizer-specific formal blind packaging and model-side execution.

The model side receives OrganizerPublicPackage only. It never receives an
OrganizerDataset object containing gold judgements or slice labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from typing import Any, Mapping, Protocol

from brain_twin_eval.organizer import (
    OrganizerDataset,
    OrganizerEvaluationError,
    OrganizerEvaluationResult,
    evaluate_organizer,
)
from brain_twin_eval.organizer_candidates import OrganizerRunConfig
from brain_twin_eval.resources import peak_rss_reading


class OrganizerBlindError(ValueError):
    pass


class OrganizerBlindGenerator(Protocol):
    def generate(self, sample: dict[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class OrganizerPublicPackage:
    version: str
    samples: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise OrganizerBlindError("public package version must not be blank")
        if not self.samples:
            raise OrganizerBlindError("public package must contain samples")
        ids: list[str] = []
        for sample in self.samples:
            if not isinstance(sample, dict):
                raise OrganizerBlindError("public sample must be an object")
            required = {"sample_id", "raw_text", "created_at", "context_memories"}
            if set(sample) != required:
                raise OrganizerBlindError("public sample keys do not match blind schema")
            sample_id = sample["sample_id"]
            raw_text = sample["raw_text"]
            created_at = sample["created_at"]
            context = sample["context_memories"]
            if not isinstance(sample_id, str) or not sample_id.strip():
                raise OrganizerBlindError("public sample_id must not be blank")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise OrganizerBlindError(f"public raw_text must not be blank: {sample_id}")
            _validate_created_at(created_at, sample_id)
            _validate_context_memories(context, sample_id)
            ids.append(sample_id)
        if len(ids) != len(set(ids)):
            raise OrganizerBlindError("duplicate public sample_id")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "version": self.version,
            "samples": list(self.samples),
        }

    @property
    def sha256(self) -> str:
        return _sha256_json(self.canonical_payload)

    @property
    def sample_count(self) -> int:
        return len(self.samples)


@dataclass(frozen=True)
class OrganizerPrivateCommitment:
    dataset_version: str
    private_dataset_sha256: str
    public_package_sha256: str
    sample_count: int

    @property
    def sha256(self) -> str:
        return _sha256_json(
            {
                "dataset_version": self.dataset_version,
                "private_dataset_sha256": self.private_dataset_sha256,
                "public_package_sha256": self.public_package_sha256,
                "sample_count": self.sample_count,
            }
        )


@dataclass(frozen=True)
class OrganizerBlindEvidence:
    launch_envelope_sha256: str
    public_package_sha256: str
    organizer_config_sha256: str
    candidate_id: str
    model_name: str
    model_revision: str
    sample_count: int
    first_call_ms: float
    warm_latency_median_ms: float
    warm_latency_p95_ms: float
    warm_latency_max_ms: float
    peak_rss_before_bytes: int | None
    peak_rss_after_bytes: int | None
    peak_rss_growth_bytes: int | None
    rss_method_before: str
    rss_method_after: str
    determinism_sample_count: int
    determinism_repeat_count: int
    determinism_mismatch_count: int
    predictions: dict[str, Any]

    def private_payload(self) -> dict[str, Any]:
        """Private evidence. Never publish this object after formal scoring."""
        return {
            "schema": 1,
            "launch_envelope_sha256": self.launch_envelope_sha256,
            "public_package_sha256": self.public_package_sha256,
            "organizer_config_sha256": self.organizer_config_sha256,
            "candidate_id": self.candidate_id,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "sample_count": self.sample_count,
            "timing": {
                "first_call_ms": self.first_call_ms,
                "warm_latency_median_ms": self.warm_latency_median_ms,
                "warm_latency_p95_ms": self.warm_latency_p95_ms,
                "warm_latency_max_ms": self.warm_latency_max_ms,
            },
            "resources": {
                "peak_rss_before_bytes": self.peak_rss_before_bytes,
                "peak_rss_after_bytes": self.peak_rss_after_bytes,
                "peak_rss_growth_bytes": self.peak_rss_growth_bytes,
                "rss_method_before": self.rss_method_before,
                "rss_method_after": self.rss_method_after,
            },
            "determinism": {
                "sample_count": self.determinism_sample_count,
                "repeat_count": self.determinism_repeat_count,
                "mismatch_count": self.determinism_mismatch_count,
            },
            "predictions": self.predictions,
        }


@dataclass(frozen=True)
class OrganizerPrivateScore:
    result: OrganizerEvaluationResult
    evidence: OrganizerBlindEvidence


def build_organizer_blind_packages(
    dataset: OrganizerDataset,
) -> tuple[OrganizerPublicPackage, OrganizerPrivateCommitment]:
    if dataset.judgement_visibility != "held_out":
        raise OrganizerBlindError("formal blind packages require judgement_visibility='held_out'")
    _validate_private_dataset_shape(dataset)

    samples = tuple(
        {
            "sample_id": sample.sample_id,
            "raw_text": sample.raw_text,
            "created_at": sample.created_at,
            "context_memories": [item.canonical() for item in sample.context_memories],
        }
        for sample in dataset.samples
    )
    public = OrganizerPublicPackage(version=dataset.version, samples=samples)
    private = OrganizerPrivateCommitment(
        dataset_version=dataset.version,
        private_dataset_sha256=dataset.canonical_sha256,
        public_package_sha256=public.sha256,
        sample_count=len(dataset.samples),
    )
    return public, private


def run_organizer_blind_package(
    package: OrganizerPublicPackage,
    generator: OrganizerBlindGenerator,
    config: OrganizerRunConfig,
    *,
    launch_envelope_sha256: str,
    determinism_sample_count: int = 16,
    determinism_repeats: int = 2,
) -> OrganizerBlindEvidence:
    _require_sha256(launch_envelope_sha256, "launch_envelope_sha256")
    if isinstance(determinism_sample_count, bool) or not isinstance(determinism_sample_count, int) or determinism_sample_count < 0:
        raise OrganizerBlindError("determinism_sample_count must be a non-negative integer")
    if isinstance(determinism_repeats, bool) or not isinstance(determinism_repeats, int) or determinism_repeats < 1:
        raise OrganizerBlindError("determinism_repeats must be a positive integer")

    rss_before = peak_rss_reading()
    predictions: dict[str, Any] = {}
    latencies: list[float] = []
    for sample in package.samples:
        model_sample = json.loads(json.dumps(sample, ensure_ascii=False))
        start = perf_counter_ns()
        output = generator.generate(model_sample)
        latencies.append((perf_counter_ns() - start) / 1_000_000.0)
        predictions[str(sample["sample_id"])] = output
    rss_after = peak_rss_reading()

    checked = min(determinism_sample_count, package.sample_count)
    mismatch_count = 0
    if determinism_repeats > 1:
        for sample in package.samples[:checked]:
            model_sample = json.loads(json.dumps(sample, ensure_ascii=False))
            baseline = _canonical_output(generator.generate(model_sample))
            for _ in range(determinism_repeats - 1):
                candidate = _canonical_output(generator.generate(json.loads(json.dumps(sample, ensure_ascii=False))))
                if candidate != baseline:
                    mismatch_count += 1
                    break

    warm = latencies[1:] or latencies
    growth = None
    if rss_before.bytes is not None and rss_after.bytes is not None:
        growth = max(0, rss_after.bytes - rss_before.bytes)
    return OrganizerBlindEvidence(
        launch_envelope_sha256=launch_envelope_sha256,
        public_package_sha256=package.sha256,
        organizer_config_sha256=config.sha256,
        candidate_id=config.candidate_id,
        model_name=config.model_name,
        model_revision=config.model_revision,
        sample_count=package.sample_count,
        first_call_ms=latencies[0],
        warm_latency_median_ms=float(median(warm)),
        warm_latency_p95_ms=_nearest_rank(warm, 0.95),
        warm_latency_max_ms=max(warm),
        peak_rss_before_bytes=rss_before.bytes,
        peak_rss_after_bytes=rss_after.bytes,
        peak_rss_growth_bytes=growth,
        rss_method_before=rss_before.method,
        rss_method_after=rss_after.method,
        determinism_sample_count=checked,
        determinism_repeat_count=determinism_repeats,
        determinism_mismatch_count=mismatch_count,
        predictions=predictions,
    )


def score_organizer_blind_evidence(
    dataset: OrganizerDataset,
    commitment: OrganizerPrivateCommitment,
    evidence: OrganizerBlindEvidence,
) -> OrganizerPrivateScore:
    if dataset.judgement_visibility != "held_out":
        raise OrganizerBlindError("formal blind scoring requires held_out dataset")
    if dataset.version != commitment.dataset_version:
        raise OrganizerBlindError("private dataset version does not match commitment")
    if dataset.canonical_sha256 != commitment.private_dataset_sha256:
        raise OrganizerBlindError("private dataset SHA does not match commitment")
    if evidence.public_package_sha256 != commitment.public_package_sha256:
        raise OrganizerBlindError("evidence public package SHA does not match commitment")
    if evidence.sample_count != commitment.sample_count or evidence.sample_count != len(dataset.samples):
        raise OrganizerBlindError("evidence sample count does not match commitment")
    expected_ids = {sample.sample_id for sample in dataset.samples}
    if set(evidence.predictions) != expected_ids:
        raise OrganizerBlindError("blind evidence predictions must cover the exact held-out sample IDs")
    result = evaluate_organizer(dataset, evidence.predictions)
    return OrganizerPrivateScore(result=result, evidence=evidence)


def assert_private_artifact_outside_repo(repo_root: Path, artifact_path: Path) -> None:
    """Fail closed when a formal-private artifact is placed in the Git workspace."""
    repo = repo_root.resolve()
    artifact = artifact_path.resolve()
    try:
        artifact.relative_to(repo)
    except ValueError:
        return
    raise OrganizerBlindError(f"private organizer artifact must stay outside repository: {artifact}")


def _validate_private_dataset_shape(dataset: OrganizerDataset) -> None:
    for sample in dataset.samples:
        _validate_created_at(sample.created_at, sample.sample_id)
        _validate_context_memories([item.canonical() for item in sample.context_memories], sample.sample_id)


def _validate_created_at(value: Any, sample_id: str) -> None:
    if not isinstance(value, str):
        raise OrganizerBlindError(f"created_at must be an ISO timestamp: {sample_id}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OrganizerBlindError(f"created_at must be an ISO timestamp: {sample_id}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OrganizerBlindError(f"created_at must include an explicit timezone offset: {sample_id}")
    if parsed.isoformat() != value:
        raise OrganizerBlindError(f"created_at must use canonical ISO format: {sample_id}")


def _validate_context_memories(value: Any, sample_id: str) -> None:
    if not isinstance(value, list) or len(value) > 32:
        raise OrganizerBlindError(f"context_memories must be an array of at most 32 items: {sample_id}")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"memory_id", "title", "summary"}:
            raise OrganizerBlindError(f"invalid context Memory object: {sample_id}")
        memory_id = item["memory_id"]
        title = item["title"]
        summary = item["summary"]
        if not isinstance(memory_id, str) or not memory_id.strip() or len(memory_id) > 120:
            raise OrganizerBlindError(f"invalid context memory_id: {sample_id}")
        if memory_id in seen:
            raise OrganizerBlindError(f"duplicate context memory_id: {sample_id}")
        seen.add(memory_id)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise OrganizerBlindError(f"invalid context title: {sample_id}")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
            raise OrganizerBlindError(f"invalid context summary: {sample_id}")


def _canonical_output(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return "RAW:" + value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "REPR:" + repr(value)


def _nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * quantile + 0.999999999))
    return ordered[min(rank, len(ordered)) - 1]


def _sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise OrganizerBlindError(f"{field} must be a lowercase SHA-256 digest")
