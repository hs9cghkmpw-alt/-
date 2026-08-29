from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .candidate_catalog import CandidateSpec


class ChallengerPlanError(ValueError):
    pass


@dataclass(frozen=True)
class ChallengerRun:
    candidate_id: str
    model_name: str
    model_revision: str
    model_directory_name: str
    dimension: int
    query_template_file: str
    document_template_file: str
    trust_remote_code: bool
    runtime_status: str
    runnable: bool
    blocked_reason: str | None

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


def _template_path(project_root: Path, value: str | None, field: str) -> str:
    if not value:
        raise ChallengerPlanError(f"{field} is required for fixed-profile challengers")
    path = project_root / value
    if not path.is_file():
        raise ChallengerPlanError(f"template does not exist: {value}")
    return value


def build_challenger_plan(
    candidates: tuple[CandidateSpec, ...],
    *,
    project_root: Path,
) -> tuple[ChallengerRun, ...]:
    runs: list[ChallengerRun] = []
    for candidate in candidates:
        if not candidate.enabled or candidate.role != "embedding":
            continue
        # Qwen has its own three-instruction + dimensionality matrix and must not be
        # accidentally re-run as a fixed-profile challenger.
        if candidate.profile_strategy != "fixed":
            continue
        if candidate.revision is None:
            raise ChallengerPlanError(f"candidate is not pinned: {candidate.candidate_id}")
        query_template = _template_path(
            project_root,
            candidate.query_template_file,
            f"{candidate.candidate_id}.query_template_file",
        )
        document_template = _template_path(
            project_root,
            candidate.document_template_file,
            f"{candidate.candidate_id}.document_template_file",
        )
        blocked_reason = None
        if not candidate.runnable:
            blocked_reason = candidate.runtime_status
        for dimension in candidate.allowed_dimensions:
            runs.append(
                ChallengerRun(
                    candidate_id=candidate.candidate_id,
                    model_name=candidate.model_name,
                    model_revision=candidate.revision,
                    model_directory_name=f"{candidate.candidate_id}_{candidate.revision[:8]}",
                    dimension=dimension,
                    query_template_file=query_template,
                    document_template_file=document_template,
                    trust_remote_code=candidate.trust_remote_code,
                    runtime_status=candidate.runtime_status,
                    runnable=candidate.runnable,
                    blocked_reason=blocked_reason,
                )
            )
    if not runs:
        raise ChallengerPlanError("no fixed-profile embedding challengers are enabled")
    return tuple(runs)
