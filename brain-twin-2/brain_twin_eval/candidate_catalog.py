from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class CandidateCatalogError(ValueError):
    pass


VALID_ROLES = {"embedding", "reranker"}
VALID_RUNTIME_STATUS = {"ready", "requires_remote_code_smoke"}
VALID_PROFILE_STRATEGY = {"fixed", "qwen_instruction_matrix", "reranker"}
MUTABLE_REVISIONS = {"main", "master", "latest", "head"}


@dataclass(frozen=True)
class CodeDependency:
    repo_id: str
    revision: str


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    role: str
    model_name: str
    revision: str | None
    enabled: bool
    notes: str
    loader: str = "sentence_transformers_dense"
    native_dimension: int | None = None
    allowed_dimensions: tuple[int, ...] = ()
    max_sequence_length: int | None = None
    query_template_file: str | None = None
    document_template_file: str | None = None
    trust_remote_code: bool = False
    code_dependency: CodeDependency | None = None
    runtime_status: str = "ready"
    profile_strategy: str = "fixed"

    @property
    def acquirable(self) -> bool:
        if not self.enabled or self.revision is None:
            return False
        if self.trust_remote_code and self.code_dependency is None:
            return False
        return True

    @property
    def runnable(self) -> bool:
        return self.acquirable and self.runtime_status == "ready"


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateCatalogError(f"{field} must be a non-empty string")
    return value


def _optional_nonempty(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field)


def _revision(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _nonempty(value, field).lower()
    if text in MUTABLE_REVISIONS:
        raise CandidateCatalogError(f"{field} must not use a mutable revision such as {text!r}")
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise CandidateCatalogError(f"{field} must be a full immutable 40-character commit SHA or null")
    return text


def _positive_int_or_none(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandidateCatalogError(f"{field} must be a positive integer or null")
    return value


def _dimensions(value: Any, field: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CandidateCatalogError(f"{field} must be a list of positive integers")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise CandidateCatalogError(f"{field} must contain only positive integers")
        if item in result:
            raise CandidateCatalogError(f"{field} must not contain duplicate dimensions")
        result.append(item)
    return tuple(result)


def _code_dependency(value: Any, field: str) -> CodeDependency | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CandidateCatalogError(f"{field} must be an object or null")
    unknown = set(value) - {"repo_id", "revision"}
    if unknown:
        raise CandidateCatalogError(f"{field} contains unsupported fields: {sorted(unknown)}")
    revision = _revision(value.get("revision"), f"{field}.revision")
    if revision is None:
        raise CandidateCatalogError(f"{field}.revision must be pinned when a code dependency exists")
    return CodeDependency(
        repo_id=_nonempty(value.get("repo_id"), f"{field}.repo_id"),
        revision=revision,
    )


def _schema1_candidate(item: Mapping[str, Any], index: int) -> CandidateSpec:
    candidate_id = _nonempty(item.get("candidate_id"), f"candidate[{index}].candidate_id")
    role = _nonempty(item.get("role"), f"{candidate_id}.role")
    enabled = item.get("enabled", True)
    notes = item.get("notes", "")
    if not isinstance(enabled, bool):
        raise CandidateCatalogError(f"{candidate_id}.enabled must be boolean")
    if not isinstance(notes, str):
        raise CandidateCatalogError(f"{candidate_id}.notes must be a string")
    return CandidateSpec(
        candidate_id=candidate_id,
        role=role,
        model_name=_nonempty(item.get("model_name"), f"{candidate_id}.model_name"),
        revision=_revision(item.get("revision"), f"{candidate_id}.revision"),
        enabled=enabled,
        notes=notes,
        profile_strategy="reranker" if role == "reranker" else "fixed",
    )


def _schema2_candidate(item: Mapping[str, Any], index: int) -> CandidateSpec:
    candidate_id = _nonempty(item.get("candidate_id"), f"candidate[{index}].candidate_id")
    role = _nonempty(item.get("role"), f"{candidate_id}.role")
    enabled = item.get("enabled", True)
    notes = item.get("notes", "")
    trust_remote_code = item.get("trust_remote_code", False)
    if not isinstance(enabled, bool):
        raise CandidateCatalogError(f"{candidate_id}.enabled must be boolean")
    if not isinstance(notes, str):
        raise CandidateCatalogError(f"{candidate_id}.notes must be a string")
    if not isinstance(trust_remote_code, bool):
        raise CandidateCatalogError(f"{candidate_id}.trust_remote_code must be boolean")

    runtime_status = _nonempty(item.get("runtime_status", "ready"), f"{candidate_id}.runtime_status")
    if runtime_status not in VALID_RUNTIME_STATUS:
        raise CandidateCatalogError(
            f"{candidate_id}.runtime_status must be one of {sorted(VALID_RUNTIME_STATUS)}"
        )
    profile_strategy = _nonempty(item.get("profile_strategy", "fixed"), f"{candidate_id}.profile_strategy")
    if profile_strategy not in VALID_PROFILE_STRATEGY:
        raise CandidateCatalogError(
            f"{candidate_id}.profile_strategy must be one of {sorted(VALID_PROFILE_STRATEGY)}"
        )

    code_dependency = _code_dependency(item.get("code_dependency"), f"{candidate_id}.code_dependency")
    if trust_remote_code and code_dependency is None:
        raise CandidateCatalogError(
            f"{candidate_id} enables trust_remote_code but has no immutable code_dependency pin"
        )
    if code_dependency is not None and not trust_remote_code:
        raise CandidateCatalogError(
            f"{candidate_id} declares code_dependency but trust_remote_code is false"
        )
    if runtime_status == "requires_remote_code_smoke" and not trust_remote_code:
        raise CandidateCatalogError(
            f"{candidate_id} requires a remote-code smoke but trust_remote_code is false"
        )

    native_dimension = _positive_int_or_none(item.get("native_dimension"), f"{candidate_id}.native_dimension")
    allowed_dimensions = _dimensions(item.get("allowed_dimensions"), f"{candidate_id}.allowed_dimensions")
    max_sequence_length = _positive_int_or_none(
        item.get("max_sequence_length"), f"{candidate_id}.max_sequence_length"
    )
    if role == "embedding":
        if native_dimension is None:
            raise CandidateCatalogError(f"{candidate_id}.native_dimension is required for embeddings")
        if not allowed_dimensions:
            raise CandidateCatalogError(f"{candidate_id}.allowed_dimensions is required for embeddings")
        if any(dimension > native_dimension for dimension in allowed_dimensions):
            raise CandidateCatalogError(
                f"{candidate_id}.allowed_dimensions cannot exceed native_dimension"
            )
        if max_sequence_length is None:
            raise CandidateCatalogError(f"{candidate_id}.max_sequence_length is required for embeddings")
        if profile_strategy == "reranker":
            raise CandidateCatalogError(f"{candidate_id} embedding cannot use reranker profile strategy")
    else:
        if native_dimension is not None or allowed_dimensions:
            raise CandidateCatalogError(f"{candidate_id} reranker must not declare embedding dimensions")
        if profile_strategy != "reranker":
            raise CandidateCatalogError(f"{candidate_id} reranker must use profile_strategy='reranker'")

    return CandidateSpec(
        candidate_id=candidate_id,
        role=role,
        model_name=_nonempty(item.get("model_name"), f"{candidate_id}.model_name"),
        revision=_revision(item.get("revision"), f"{candidate_id}.revision"),
        enabled=enabled,
        notes=notes,
        loader=_nonempty(item.get("loader", "sentence_transformers_dense"), f"{candidate_id}.loader"),
        native_dimension=native_dimension,
        allowed_dimensions=allowed_dimensions,
        max_sequence_length=max_sequence_length,
        query_template_file=_optional_nonempty(
            item.get("query_template_file"), f"{candidate_id}.query_template_file"
        ),
        document_template_file=_optional_nonempty(
            item.get("document_template_file"), f"{candidate_id}.document_template_file"
        ),
        trust_remote_code=trust_remote_code,
        code_dependency=code_dependency,
        runtime_status=runtime_status,
        profile_strategy=profile_strategy,
    )


def catalog_from_mapping(raw: Mapping[str, Any]) -> tuple[CandidateSpec, ...]:
    if not isinstance(raw, Mapping):
        raise CandidateCatalogError("catalog root must be an object")
    schema = raw.get("schema")
    if schema not in (1, 2):
        raise CandidateCatalogError("unsupported candidate catalog schema")
    items = raw.get("candidates")
    if not isinstance(items, list) or not items:
        raise CandidateCatalogError("catalog candidates must be a non-empty list")

    result: list[CandidateSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise CandidateCatalogError(f"candidate {index} must be an object")
        spec = _schema1_candidate(item, index) if schema == 1 else _schema2_candidate(item, index)
        if spec.candidate_id in seen:
            raise CandidateCatalogError(f"duplicate candidate_id: {spec.candidate_id}")
        seen.add(spec.candidate_id)
        if spec.role not in VALID_ROLES:
            raise CandidateCatalogError(f"{spec.candidate_id}.role must be one of {sorted(VALID_ROLES)}")
        result.append(spec)
    return tuple(result)


def load_catalog(path: str | Path) -> tuple[CandidateSpec, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return catalog_from_mapping(raw)


def unresolved_candidates(candidates: tuple[CandidateSpec, ...]) -> tuple[CandidateSpec, ...]:
    return tuple(item for item in candidates if item.enabled and item.revision is None)


def blocked_candidates(candidates: tuple[CandidateSpec, ...]) -> tuple[CandidateSpec, ...]:
    return tuple(item for item in candidates if item.enabled and item.acquirable and not item.runnable)


def runnable_embeddings(candidates: tuple[CandidateSpec, ...]) -> tuple[CandidateSpec, ...]:
    return tuple(item for item in candidates if item.role == "embedding" and item.runnable)
