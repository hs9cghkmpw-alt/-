"""Model-agnostic local organizer runtime evidence.

No model framework is imported here. Concrete Transformers/llama.cpp adapters are
separate so evaluator tests remain lightweight and production-independent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from statistics import median
from time import perf_counter_ns
from typing import Any, Protocol

from brain_twin_eval.organizer import OrganizerDataset
from brain_twin_eval.organizer_candidates import OrganizerRunConfig
from brain_twin_eval.resources import peak_rss_reading


class OrganizerGenerator(Protocol):
    def generate(self, sample: dict[str, Any]) -> Any:
        """Generate one schema-shaped output for a public organizer sample."""
        ...


@dataclass(frozen=True)
class OrganizerRuntimeEvidence:
    dataset_version: str
    dataset_sha256: str
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "dataset_sha256": self.dataset_sha256,
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


def run_organizer_candidate(
    dataset: OrganizerDataset,
    generator: OrganizerGenerator,
    config: OrganizerRunConfig,
    *,
    determinism_sample_count: int = 16,
    determinism_repeats: int = 2,
) -> OrganizerRuntimeEvidence:
    if isinstance(determinism_sample_count, bool) or not isinstance(determinism_sample_count, int) or determinism_sample_count < 0:
        raise ValueError("determinism_sample_count must be a non-negative integer")
    if isinstance(determinism_repeats, bool) or not isinstance(determinism_repeats, int) or determinism_repeats < 1:
        raise ValueError("determinism_repeats must be a positive integer")

    public_samples = dataset.public_payload()["samples"]
    assert isinstance(public_samples, list)
    if not public_samples:
        raise ValueError("organizer dataset must not be empty")

    rss_before = peak_rss_reading()
    predictions: dict[str, Any] = {}
    latencies_ms: list[float] = []

    for sample in public_samples:
        assert isinstance(sample, dict)
        sample_id = sample["sample_id"]
        start_ns = perf_counter_ns()
        output = generator.generate(dict(sample))
        elapsed_ms = (perf_counter_ns() - start_ns) / 1_000_000.0
        latencies_ms.append(elapsed_ms)
        predictions[str(sample_id)] = output

    rss_after = peak_rss_reading()
    growth = None
    if rss_before.bytes is not None and rss_after.bytes is not None:
        growth = max(0, rss_after.bytes - rss_before.bytes)

    checked = min(determinism_sample_count, len(public_samples))
    mismatch_count = 0
    if determinism_repeats > 1:
        for sample in public_samples[:checked]:
            assert isinstance(sample, dict)
            baseline = _canonical_output(generator.generate(dict(sample)))
            for _ in range(determinism_repeats - 1):
                candidate = _canonical_output(generator.generate(dict(sample)))
                if candidate != baseline:
                    mismatch_count += 1
                    break

    warm = latencies_ms[1:] or latencies_ms
    return OrganizerRuntimeEvidence(
        dataset_version=dataset.version,
        dataset_sha256=dataset.canonical_sha256,
        organizer_config_sha256=config.sha256,
        candidate_id=config.candidate_id,
        model_name=config.model_name,
        model_revision=config.model_revision,
        sample_count=len(public_samples),
        first_call_ms=latencies_ms[0],
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


def _canonical_output(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return "RAW:" + value
        value = parsed
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "REPR:" + repr(value)


def _nearest_rank(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * quantile + 0.999999999))
    return ordered[min(rank, len(ordered)) - 1]
