"""Fail-closed organizer-model candidate catalog and formal config identity."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUNTIME_STATUSES = {
    "pinned_reference",
    "requires_remote_code_smoke",
    "research_only",
    "research_only_gated",
}
ACCESS_MODES = {"open", "gated"}


class OrganizerCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class OrganizerCandidate:
    candidate_id: str
    model_name: str
    revision: str | None
    license_id: str
    access: str
    loader: str
    trust_remote_code: bool
    runtime_status: str
    parameter_billions: float | None
    reference_repo_size_gb: float | None
    notes: str
    official_source: str

    @property
    def runnable_reference(self) -> bool:
        return self.runtime_status == "pinned_reference" and self.revision is not None


@dataclass(frozen=True)
class OrganizerRunConfig:
    candidate_id: str
    model_name: str
    model_revision: str
    prompt_sha256: str
    schema_sha256: str
    chat_template_sha256: str
    runtime_backend: str
    runtime_revision: str
    quantization: str
    temperature: float
    top_p: float
    max_new_tokens: int
    seed: int
    extra_runtime_params: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_full_sha(self.model_revision, "model_revision")
        _require_sha256(self.prompt_sha256, "prompt_sha256")
        _require_sha256(self.schema_sha256, "schema_sha256")
        _require_sha256(self.chat_template_sha256, "chat_template_sha256")
        if not self.runtime_backend.strip():
            raise OrganizerCandidateError("runtime_backend must not be blank")
        if not self.runtime_revision.strip():
            raise OrganizerCandidateError("runtime_revision must not be blank")
        if not self.quantization.strip():
            raise OrganizerCandidateError("quantization must not be blank")
        if self.temperature < 0:
            raise OrganizerCandidateError("temperature must be >= 0")
        if not 0 < self.top_p <= 1:
            raise OrganizerCandidateError("top_p must be in (0, 1]")
        if isinstance(self.max_new_tokens, bool) or not isinstance(self.max_new_tokens, int) or self.max_new_tokens <= 0:
            raise OrganizerCandidateError("max_new_tokens must be a positive integer")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise OrganizerCandidateError("seed must be an integer")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "chat_template_sha256": self.chat_template_sha256,
            "runtime_backend": self.runtime_backend,
            "runtime_revision": self.runtime_revision,
            "quantization": self.quantization,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_new_tokens": self.max_new_tokens,
            "seed": self.seed,
            "extra_runtime_params": [list(item) for item in self.extra_runtime_params],
        }

    @property
    def sha256(self) -> str:
        encoded = json.dumps(
            self.canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def load_organizer_candidate_catalog(path: Path) -> tuple[OrganizerCandidate, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrganizerCandidateError(f"cannot load organizer candidate catalog: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != 1 or not isinstance(payload.get("candidates"), list):
        raise OrganizerCandidateError("organizer candidate catalog must use schema 1")

    result: list[OrganizerCandidate] = []
    seen: set[str] = set()
    for raw in payload["candidates"]:
        if not isinstance(raw, dict):
            raise OrganizerCandidateError("candidate entry must be an object")
        required = {
            "candidate_id",
            "model_name",
            "revision",
            "license_id",
            "access",
            "loader",
            "trust_remote_code",
            "runtime_status",
            "parameter_billions",
            "reference_repo_size_gb",
            "notes",
            "official_source",
        }
        if frozenset(raw) != required:
            raise OrganizerCandidateError("candidate entry keys do not match schema 1")
        candidate_id = _nonempty(raw["candidate_id"], "candidate_id")
        if candidate_id in seen:
            raise OrganizerCandidateError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        model_name = _nonempty(raw["model_name"], "model_name")
        license_id = _nonempty(raw["license_id"], "license_id")
        access = _nonempty(raw["access"], "access")
        if access not in ACCESS_MODES:
            raise OrganizerCandidateError(f"invalid access: {access}")
        loader = _nonempty(raw["loader"], "loader")
        trust_remote_code = raw["trust_remote_code"]
        if type(trust_remote_code) is not bool:
            raise OrganizerCandidateError("trust_remote_code must be boolean")
        status = _nonempty(raw["runtime_status"], "runtime_status")
        if status not in RUNTIME_STATUSES:
            raise OrganizerCandidateError(f"invalid runtime_status: {status}")
        revision = raw["revision"]
        if revision is not None:
            if not isinstance(revision, str) or not FULL_SHA_RE.fullmatch(revision):
                raise OrganizerCandidateError(f"revision must be a full immutable SHA: {candidate_id}")
        if status in {"pinned_reference", "requires_remote_code_smoke"} and revision is None:
            raise OrganizerCandidateError(f"pinned candidate requires revision: {candidate_id}")
        if status == "pinned_reference" and trust_remote_code:
            raise OrganizerCandidateError(
                f"remote-code candidate cannot be directly runnable without smoke: {candidate_id}"
            )
        if status == "requires_remote_code_smoke" and not trust_remote_code:
            raise OrganizerCandidateError(
                f"remote-code smoke status requires trust_remote_code=true: {candidate_id}"
            )
        if access == "gated" and status == "pinned_reference":
            raise OrganizerCandidateError(f"gated candidate cannot be auto-runnable: {candidate_id}")

        parameter_billions = _optional_positive_number(raw["parameter_billions"], "parameter_billions")
        repo_size = _optional_positive_number(raw["reference_repo_size_gb"], "reference_repo_size_gb")
        result.append(
            OrganizerCandidate(
                candidate_id=candidate_id,
                model_name=model_name,
                revision=revision,
                license_id=license_id,
                access=access,
                loader=loader,
                trust_remote_code=trust_remote_code,
                runtime_status=status,
                parameter_billions=parameter_billions,
                reference_repo_size_gb=repo_size,
                notes=_nonempty(raw["notes"], "notes"),
                official_source=_nonempty(raw["official_source"], "official_source"),
            )
        )
    return tuple(result)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise OrganizerCandidateError(f"cannot hash file: {path}") from exc
    return digest.hexdigest()


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrganizerCandidateError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_positive_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise OrganizerCandidateError(f"{field} must be null or a positive number")
    return float(value)


def _require_full_sha(value: str, field: str) -> None:
    if not FULL_SHA_RE.fullmatch(value):
        raise OrganizerCandidateError(f"{field} must be a full immutable 40-character SHA")


def _require_sha256(value: str, field: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise OrganizerCandidateError(f"{field} must be a lowercase SHA-256 hex digest")
