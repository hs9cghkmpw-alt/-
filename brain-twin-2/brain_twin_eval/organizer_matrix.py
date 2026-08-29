"""Frozen organizer model-matrix contract used by local evaluation tooling."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .organizer_candidates import OrganizerCandidate, OrganizerCandidateError


MATRIX_TIERS = ("core", "extended")


@dataclass(frozen=True)
class OrganizerModelMatrix:
    core: tuple[str, ...]
    extended: tuple[str, ...]
    blocked: tuple[str, ...]

    def candidate_ids(self, tier: str) -> tuple[str, ...]:
        if tier == "core":
            return self.core
        if tier == "extended":
            return self.extended
        if tier == "all":
            return self.core + self.extended
        raise OrganizerCandidateError(f"unsupported organizer matrix tier: {tier}")


def load_organizer_model_matrix(
    path: Path,
    candidates: tuple[OrganizerCandidate, ...],
) -> OrganizerModelMatrix:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrganizerCandidateError(f"cannot load organizer model matrix: {path}") from exc
    if not isinstance(payload, dict) or frozenset(payload) != {"schema", "core", "extended", "blocked"}:
        raise OrganizerCandidateError("organizer model matrix keys do not match schema 1")
    if payload.get("schema") != 1:
        raise OrganizerCandidateError("organizer model matrix must use schema 1")

    known = {candidate.candidate_id: candidate for candidate in candidates}
    groups: dict[str, tuple[str, ...]] = {}
    all_ids: list[str] = []
    for group in ("core", "extended", "blocked"):
        raw = payload[group]
        if not isinstance(raw, list) or not raw:
            raise OrganizerCandidateError(f"organizer matrix {group} must be a non-empty array")
        if not all(isinstance(item, str) and item.strip() for item in raw):
            raise OrganizerCandidateError(f"organizer matrix {group} ids must be non-empty strings")
        values = tuple(item.strip() for item in raw)
        if len(values) != len(set(values)):
            raise OrganizerCandidateError(f"duplicate candidate in organizer matrix {group}")
        unknown = sorted(set(values) - set(known))
        if unknown:
            raise OrganizerCandidateError(f"unknown organizer matrix candidate(s): {unknown}")
        groups[group] = values
        all_ids.extend(values)

    if len(all_ids) != len(set(all_ids)):
        raise OrganizerCandidateError("organizer candidate may appear in only one matrix group")
    if set(all_ids) != set(known):
        missing = sorted(set(known) - set(all_ids))
        raise OrganizerCandidateError(f"organizer matrix does not classify every catalog candidate: {missing}")

    for candidate_id in groups["core"] + groups["extended"]:
        candidate = known[candidate_id]
        if not candidate.runnable_reference:
            raise OrganizerCandidateError(
                f"runnable organizer matrix tier contains blocked candidate: {candidate_id}"
            )
    for candidate_id in groups["blocked"]:
        if known[candidate_id].runnable_reference:
            raise OrganizerCandidateError(
                f"blocked organizer matrix group contains directly runnable candidate: {candidate_id}"
            )

    return OrganizerModelMatrix(
        core=groups["core"],
        extended=groups["extended"],
        blocked=groups["blocked"],
    )


def organizer_candidate_directory_name(candidate: OrganizerCandidate) -> str:
    if candidate.revision is None:
        raise OrganizerCandidateError(f"candidate is not pinned: {candidate.candidate_id}")
    return f"organizer_{candidate.candidate_id}_{candidate.revision[:8]}"
