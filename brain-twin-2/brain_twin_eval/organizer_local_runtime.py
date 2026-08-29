"""Local-files-only runtime for organizer model evaluation.

Evaluation-only: never writes the Vault and never imports production pipeline code.
Model acquisition is a separate, explicit network step.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
import math
import platform
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Mapping, Protocol

from .organizer_candidates import (
    OrganizerCandidate,
    OrganizerCandidateError,
    OrganizerRunConfig,
    sha256_file,
)
from .resources import peak_rss_reading


PIN_MANIFEST = "brain_twin_organizer_pin.json"


class OrganizerTextGenerator(Protocol):
    chat_template_sha256: str
    runtime_revision: str
    quantization: str

    def generate(self, sample: Mapping[str, Any]) -> str:
        ...


@dataclass(frozen=True)
class OrganizerRuntimeEvidence:
    candidate_id: str
    organizer_config_sha256: str
    sample_count: int
    latency_ms_median: float
    latency_ms_p95: float
    latency_ms_max: float
    peak_rss_before_bytes: int | None
    peak_rss_after_bytes: int | None
    peak_rss_growth_bytes: int | None
    peak_rss_method: str
    model_disk_bytes: int
    determinism_checked_samples: int
    determinism_repeats: int
    deterministic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "organizer_config_sha256": self.organizer_config_sha256,
            "sample_count": self.sample_count,
            "latency_ms": {
                "median": self.latency_ms_median,
                "p95": self.latency_ms_p95,
                "max": self.latency_ms_max,
            },
            "peak_rss": {
                "before_bytes": self.peak_rss_before_bytes,
                "after_bytes": self.peak_rss_after_bytes,
                "growth_bytes": self.peak_rss_growth_bytes,
                "method": self.peak_rss_method,
            },
            "model_disk_bytes": self.model_disk_bytes,
            "determinism": {
                "checked_samples": self.determinism_checked_samples,
                "repeats": self.determinism_repeats,
                "deterministic": self.deterministic,
            },
        }


def load_and_verify_pin(model_dir: Path, candidate: OrganizerCandidate) -> dict[str, Any]:
    if candidate.revision is None:
        raise OrganizerCandidateError(f"organizer candidate is not pinned: {candidate.candidate_id}")
    manifest_path = model_dir / PIN_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrganizerCandidateError(f"missing or invalid organizer pin manifest: {manifest_path}") from exc
    required = {
        "schema",
        "candidate_id",
        "repo_id",
        "revision",
        "runtime_status",
        "trust_remote_code",
        "runtime_policy",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise OrganizerCandidateError("organizer pin manifest is missing required fields")
    expected = {
        "candidate_id": candidate.candidate_id,
        "repo_id": candidate.model_name,
        "revision": candidate.revision,
        "runtime_status": candidate.runtime_status,
        "trust_remote_code": candidate.trust_remote_code,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise OrganizerCandidateError(
                f"organizer pin manifest mismatch for {key}: expected {value!r}, got {payload.get(key)!r}"
            )
    if payload.get("runtime_policy") != "evaluation-loads-local-files-only":
        raise OrganizerCandidateError("organizer pin manifest does not enforce local-files-only runtime")
    if candidate.trust_remote_code or not candidate.runnable_reference:
        raise OrganizerCandidateError(
            f"candidate is not authorized for direct organizer runtime: {candidate.candidate_id}"
        )
    return payload


def directory_size_bytes(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError as exc:
        raise OrganizerCandidateError(f"cannot measure organizer model directory: {path}") from exc
    return total


def build_organizer_run_config(
    *,
    candidate: OrganizerCandidate,
    generator: OrganizerTextGenerator,
    prompt_path: Path,
    schema_path: Path,
    max_new_tokens: int,
    seed: int,
) -> OrganizerRunConfig:
    if candidate.revision is None:
        raise OrganizerCandidateError(f"candidate is not pinned: {candidate.candidate_id}")
    return OrganizerRunConfig(
        candidate_id=candidate.candidate_id,
        model_name=candidate.model_name,
        model_revision=candidate.revision,
        prompt_sha256=sha256_file(prompt_path),
        schema_sha256=sha256_file(schema_path),
        chat_template_sha256=generator.chat_template_sha256,
        runtime_backend="transformers-cpu-local-only",
        runtime_revision=generator.runtime_revision,
        quantization=generator.quantization,
        temperature=0.0,
        top_p=1.0,
        max_new_tokens=max_new_tokens,
        seed=seed,
        extra_runtime_params=(
            ("apply_chat_template_tokenize", "true"),
            ("enable_thinking", "false"),
            ("do_sample", "false"),
        ),
    )


def run_public_package(
    *,
    public_package: Mapping[str, Any],
    generator: OrganizerTextGenerator,
    candidate: OrganizerCandidate,
    config: OrganizerRunConfig,
    model_dir: Path,
    determinism_checked_samples: int = 8,
    determinism_repeats: int = 2,
) -> tuple[dict[str, str], OrganizerRuntimeEvidence]:
    samples = public_package.get("samples")
    if not isinstance(samples, list) or not samples:
        raise OrganizerCandidateError("organizer public package must contain a non-empty samples array")
    if determinism_checked_samples < 0:
        raise OrganizerCandidateError("determinism_checked_samples must be >= 0")
    if determinism_repeats < 1:
        raise OrganizerCandidateError("determinism_repeats must be >= 1")

    before = peak_rss_reading()
    predictions: dict[str, str] = {}
    latencies_ms: list[float] = []
    ordered_samples: list[Mapping[str, Any]] = []
    for raw in samples:
        if not isinstance(raw, Mapping):
            raise OrganizerCandidateError("organizer public sample must be an object")
        sample_id = raw.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise OrganizerCandidateError("organizer public sample_id must be non-empty")
        if sample_id in predictions:
            raise OrganizerCandidateError(f"duplicate organizer public sample_id: {sample_id}")
        if "gold" in raw or "slices" in raw:
            raise OrganizerCandidateError("model-side organizer package must not contain gold or slices")
        started = perf_counter()
        output = generator.generate(raw)
        elapsed_ms = (perf_counter() - started) * 1000.0
        if not isinstance(output, str):
            raise OrganizerCandidateError("organizer generator must return raw text output")
        predictions[sample_id] = output
        latencies_ms.append(elapsed_ms)
        ordered_samples.append(raw)

    deterministic = True
    check_count = min(determinism_checked_samples, len(ordered_samples))
    if determinism_repeats > 1:
        for sample in ordered_samples[:check_count]:
            sample_id = str(sample["sample_id"])
            expected = predictions[sample_id]
            for _ in range(determinism_repeats - 1):
                if generator.generate(sample) != expected:
                    deterministic = False
                    break
            if not deterministic:
                break

    after = peak_rss_reading()
    growth = None if before.bytes is None or after.bytes is None else max(0, after.bytes - before.bytes)
    method = after.method if after.bytes is not None else before.method
    evidence = OrganizerRuntimeEvidence(
        candidate_id=candidate.candidate_id,
        organizer_config_sha256=config.sha256,
        sample_count=len(predictions),
        latency_ms_median=float(median(latencies_ms)),
        latency_ms_p95=_nearest_rank_percentile(latencies_ms, 0.95),
        latency_ms_max=max(latencies_ms),
        peak_rss_before_bytes=before.bytes,
        peak_rss_after_bytes=after.bytes,
        peak_rss_growth_bytes=growth,
        peak_rss_method=method,
        model_disk_bytes=directory_size_bytes(model_dir),
        determinism_checked_samples=check_count,
        determinism_repeats=determinism_repeats,
        deterministic=deterministic,
    )
    return predictions, evidence


class TransformersLocalOrganizerGenerator:
    """Thin CPU generator around an already acquired immutable local snapshot."""

    def __init__(
        self,
        *,
        candidate: OrganizerCandidate,
        model_dir: Path,
        system_prompt: str,
        max_new_tokens: int,
        seed: int,
        torch_module: Any,
        transformers_module: Any,
        processor: Any,
        model: Any,
    ) -> None:
        self.candidate = candidate
        self.model_dir = model_dir
        self.system_prompt = system_prompt
        self.max_new_tokens = max_new_tokens
        self.seed = seed
        self.torch = torch_module
        self.transformers = transformers_module
        self.processor = processor
        self.model = model
        self.quantization = "none"
        self.runtime_revision = _runtime_revision()
        template = _chat_template(processor)
        self.chat_template_sha256 = hashlib.sha256(template.encode("utf-8")).hexdigest()

    @classmethod
    def load(
        cls,
        *,
        candidate: OrganizerCandidate,
        model_dir: Path,
        system_prompt: str,
        max_new_tokens: int = 512,
        seed: int = 0,
    ) -> "TransformersLocalOrganizerGenerator":
        load_and_verify_pin(model_dir, candidate)
        try:
            import torch
            import transformers
        except ImportError as exc:
            raise OrganizerCandidateError(
                "organizer local runtime requires the isolated evaluation environment with torch and transformers"
            ) from exc

        torch.manual_seed(seed)
        common = {
            "pretrained_model_name_or_path": str(model_dir),
            "local_files_only": True,
            "trust_remote_code": False,
        }
        if candidate.loader == "transformers_causal_lm":
            processor = transformers.AutoTokenizer.from_pretrained(**common)
            model = transformers.AutoModelForCausalLM.from_pretrained(**common, torch_dtype="auto")
        elif candidate.loader == "transformers_multimodal_text_only":
            processor = transformers.AutoProcessor.from_pretrained(**common)
            model = _load_multimodal_model(transformers, common)
        else:
            raise OrganizerCandidateError(
                f"unsupported direct organizer loader: {candidate.loader}; blocked candidates require separate review"
            )
        model.eval()
        model.to("cpu")
        return cls(
            candidate=candidate,
            model_dir=model_dir,
            system_prompt=system_prompt,
            max_new_tokens=max_new_tokens,
            seed=seed,
            torch_module=torch,
            transformers_module=transformers,
            processor=processor,
            model=model,
        )

    def generate(self, sample: Mapping[str, Any]) -> str:
        self.torch.manual_seed(self.seed)
        user_text = json.dumps(
            {
                "task": "organize_raw_capture",
                "input": dict(sample),
                "output_rule": "Return exactly one JSON object matching the supplied organizer schema. No prose or code fences.",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if self.candidate.loader == "transformers_multimodal_text_only":
            messages = [
                {"role": "system", "content": [{"type": "text", "text": self.system_prompt}]},
                {"role": "user", "content": [{"type": "text", "text": user_text}]},
            ]
        else:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text},
            ]

        encoded = _encode_chat(self.processor, messages)
        input_ids = encoded.get("input_ids")
        if input_ids is None:
            raise OrganizerCandidateError("organizer chat template did not return input_ids")
        with self.torch.inference_mode():
            output_ids = self.model.generate(
                **encoded,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                use_cache=True,
            )
        prompt_length = int(input_ids.shape[-1])
        generated = output_ids[:, prompt_length:]
        decoder = getattr(self.processor, "batch_decode", None)
        if decoder is None and hasattr(self.processor, "tokenizer"):
            decoder = getattr(self.processor.tokenizer, "batch_decode", None)
        if decoder is None:
            raise OrganizerCandidateError("organizer processor does not expose batch_decode")
        return str(decoder(generated, skip_special_tokens=True)[0]).strip()


def _encode_chat(processor: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Follow the Qwen3.5 official direct-tokenization chat-template path."""
    try:
        encoded = processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        )
    except TypeError as exc:
        raise OrganizerCandidateError(
            "installed processor/tokenizer does not support the frozen direct-tokenization chat-template contract"
        ) from exc
    if hasattr(encoded, "to"):
        encoded = encoded.to("cpu")
    if not isinstance(encoded, Mapping):
        raise OrganizerCandidateError("organizer apply_chat_template must return a mapping when return_dict=True")
    return {key: value.to("cpu") if hasattr(value, "to") else value for key, value in encoded.items()}


def _load_multimodal_model(transformers_module: Any, common: dict[str, Any]) -> Any:
    # Qwen3.5 official path is AutoModelForMultimodalLM. Fallbacks exist only for
    # compatible Transformers builds and are still local-only/trust_remote_code=False.
    last_error: Exception | None = None
    for name in (
        "AutoModelForMultimodalLM",
        "AutoModelForImageTextToText",
        "AutoModelForVision2Seq",
        "AutoModelForCausalLM",
    ):
        cls = getattr(transformers_module, name, None)
        if cls is None:
            continue
        try:
            return cls.from_pretrained(**common, torch_dtype="auto")
        except (ValueError, TypeError) as exc:
            last_error = exc
    if last_error is not None:
        raise OrganizerCandidateError("installed transformers cannot load the pinned multimodal organizer model") from last_error
    raise OrganizerCandidateError("installed transformers has no compatible multimodal auto-model class")


def _chat_template(processor: Any) -> str:
    template = getattr(processor, "chat_template", None)
    if not isinstance(template, str) and hasattr(processor, "tokenizer"):
        template = getattr(processor.tokenizer, "chat_template", None)
    if not isinstance(template, str) or not template:
        raise OrganizerCandidateError("organizer processor/tokenizer has no frozen chat template")
    return template


def _runtime_revision() -> str:
    package_names = ("torch", "torchvision", "transformers", "huggingface-hub", "Pillow")
    versions: list[str] = [f"python={platform.python_version()}"]
    for package in package_names:
        try:
            value = metadata.version(package)
        except metadata.PackageNotFoundError:
            value = "missing"
        versions.append(f"{package}={value}")
    return ";".join(versions)


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise OrganizerCandidateError("cannot summarize empty organizer latency samples")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])
