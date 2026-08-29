from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class CandidateCatalogError(ValueError):
    pass


VALID_ROLES = {"embedding", "reranker"}
MUTABLE_REVISIONS = {"main", "master", "latest", "head"}


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    role: str
    model_name: str
    revision: str | None
    enabled: bool
    notes: str

    @property
    def runnable(self) -> bool:
        return self.enabled and self.revision is not None


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateCatalogError(f"{field} must be a non-empty string")
    return value


def _revision(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _nonempty(value, field).lower()
    if text in MUTABLE_REVISIONS:
        raise CandidateCatalogError(f"{field} must not use a mutable revision such as {text!r}")
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise CandidateCatalogError(f"{field} must be a full immutable 40-character commit SHA or null")
    return text


def catalog_from_mapping(raw: Mapping[str, Any]) -> tuple[CandidateSpec, ...]:
    if not isinstance(raw, Mapping):
        raise CandidateCatalogError("catalog root must be an object")
    if raw.get("schema") != 1:
        raise CandidateCatalogError("unsupported candidate catalog schema")
    items = raw.get("candidates")
    if not isinstance(items, list) or not items:
        raise CandidateCatalogError("catalog candidates must be a non-empty list")

    result: list[CandidateSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise CandidateCatalogError(f"candidate {index} must be an object")
        candidate_id = _nonempty(item.get("candidate_id"), f"candidate[{index}].candidate_id")
        if candidate_id in seen:
            raise CandidateCatalogError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        role = _nonempty(item.get("role"), f"{candidate_id}.role")
        if role not in VALID_ROLES:
            raise CandidateCatalogError(f"{candidate_id}.role must be one of {sorted(VALID_ROLES)}")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise CandidateCatalogError(f"{candidate_id}.enabled must be boolean")
        notes = item.get("notes", "")
        if not isinstance(notes, str):
            raise CandidateCatalogError(f"{candidate_id}.notes must be a string")
        result.append(
            CandidateSpec(
                candidate_id=candidate_id,
                role=role,
                model_name=_nonempty(item.get("model_name"), f"{candidate_id}.model_name"),
                revision=_revision(item.get("revision"), f"{candidate_id}.revision"),
                enabled=enabled,
                notes=notes,
            )
        )
    return tuple(result)


def load_catalog(path: str | Path) -> tuple[CandidateSpec, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return catalog_from_mapping(raw)


def unresolved_candidates(candidates: tuple[CandidateSpec, ...]) -> tuple[CandidateSpec, ...]:
    return tuple(item for item in candidates if item.enabled and item.revision is None)
