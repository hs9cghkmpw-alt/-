from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .candidate_catalog import CandidateSpec
from .resources import peak_rss_reading


class RemoteCodeSmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteCodeSmokeResult:
    schema: int
    candidate_id: str
    model_name: str
    model_revision: str
    code_repo_id: str
    code_revision: str
    observed_dimension: int
    normalized: bool
    elapsed_seconds: float
    peak_rss_bytes: int | None
    local_files_only: bool
    catalog_status_after_smoke: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=2)


def expected_model_dir(candidate: CandidateSpec, model_root: Path) -> Path:
    if candidate.revision is None:
        raise RemoteCodeSmokeError("candidate model revision is not pinned")
    return model_root / f"{candidate.candidate_id}_{candidate.revision[:8]}"


def validate_pin_manifest(candidate: CandidateSpec, model_dir: Path) -> dict[str, Any]:
    if not candidate.trust_remote_code or candidate.code_dependency is None:
        raise RemoteCodeSmokeError("candidate does not declare an external custom-code dependency")
    if candidate.runtime_status != "requires_remote_code_smoke":
        raise RemoteCodeSmokeError("candidate is not waiting for a remote-code smoke")
    if candidate.revision is None:
        raise RemoteCodeSmokeError("candidate model revision is not pinned")

    manifest_path = model_dir / "brain_twin_model_pin.json"
    if not manifest_path.is_file():
        raise RemoteCodeSmokeError(
            "pinned model manifest is missing; run explicit candidate acquisition first"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemoteCodeSmokeError("pinned model manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise RemoteCodeSmokeError("pinned model manifest root must be an object")

    expected = {
        "candidate_id": candidate.candidate_id,
        "repo_id": candidate.model_name,
        "revision": candidate.revision,
        "runtime_status": candidate.runtime_status,
        "trust_remote_code": True,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise RemoteCodeSmokeError(f"pin manifest mismatch: {field}")

    code = manifest.get("code_dependency")
    if not isinstance(code, dict):
        raise RemoteCodeSmokeError("pin manifest lacks code_dependency")
    if code.get("repo_id") != candidate.code_dependency.repo_id:
        raise RemoteCodeSmokeError("pin manifest mismatch: code_dependency.repo_id")
    if code.get("revision") != candidate.code_dependency.revision:
        raise RemoteCodeSmokeError("pin manifest mismatch: code_dependency.revision")
    return manifest


def _default_model_factory(model_dir: Path, code_revision: str):
    # Environment is forced offline by run_remote_code_smoke before this import.
    from sentence_transformers import SentenceTransformer

    code_kwargs = {"code_revision": code_revision}
    return SentenceTransformer(
        str(model_dir),
        device="cpu",
        local_files_only=True,
        trust_remote_code=True,
        model_kwargs=dict(code_kwargs),
        config_kwargs=dict(code_kwargs),
        processor_kwargs=dict(code_kwargs),
    )


def _first_vector(values: Any) -> list[float]:
    try:
        row = values[0]
    except (IndexError, KeyError, TypeError) as exc:
        raise RemoteCodeSmokeError("model returned no embedding rows") from exc
    if hasattr(row, "tolist"):
        row = row.tolist()
    if not isinstance(row, (list, tuple)):
        raise RemoteCodeSmokeError("model returned a malformed embedding row")
    try:
        vector = [float(value) for value in row]
    except (TypeError, ValueError) as exc:
        raise RemoteCodeSmokeError("embedding row contains non-numeric values") from exc
    if not vector or any(not math.isfinite(value) for value in vector):
        raise RemoteCodeSmokeError("embedding row is empty or non-finite")
    return vector


def run_remote_code_smoke(
    candidate: CandidateSpec,
    *,
    model_root: Path,
    model_factory: Callable[[Path, str], Any] | None = None,
) -> RemoteCodeSmokeResult:
    if candidate.native_dimension is None:
        raise RemoteCodeSmokeError("candidate native dimension is unknown")
    model_dir = expected_model_dir(candidate, model_root)
    validate_pin_manifest(candidate, model_dir)
    assert candidate.code_dependency is not None

    old_hf_offline = os.environ.get("HF_HUB_OFFLINE")
    old_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        factory = model_factory or _default_model_factory
        started = time.perf_counter()
        model = factory(model_dir, candidate.code_dependency.revision)
        embeddings = model.encode(
            ["札幌で以前話していた予定を思い出したい"],
            batch_size=1,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        elapsed = time.perf_counter() - started
    finally:
        if old_hf_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_hf_offline
        if old_transformers_offline is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline

    vector = _first_vector(embeddings)
    if len(vector) != candidate.native_dimension:
        raise RemoteCodeSmokeError(
            f"native dimension mismatch: expected {candidate.native_dimension}, observed {len(vector)}"
        )
    norm = math.sqrt(sum(value * value for value in vector))
    normalized = abs(norm - 1.0) <= 1e-3
    if not normalized:
        raise RemoteCodeSmokeError(f"normalized embedding contract failed: norm={norm:.6f}")

    return RemoteCodeSmokeResult(
        schema=1,
        candidate_id=candidate.candidate_id,
        model_name=candidate.model_name,
        model_revision=candidate.revision,
        code_repo_id=candidate.code_dependency.repo_id,
        code_revision=candidate.code_dependency.revision,
        observed_dimension=len(vector),
        normalized=True,
        elapsed_seconds=elapsed,
        peak_rss_bytes=peak_rss_reading().bytes,
        local_files_only=True,
        # A successful smoke is evidence for a later review, never an automatic catalog mutation.
        catalog_status_after_smoke=candidate.runtime_status,
    )
