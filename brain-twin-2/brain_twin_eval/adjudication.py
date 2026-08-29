from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .dataset import VALID_GRADES


class AdjudicationError(ValueError):
    pass


@dataclass(frozen=True)
class JudgeQuery:
    query_id: str
    relevance: Mapping[str, int]
    must_hit_ids: tuple[str, ...]
    hard_negative: bool


@dataclass(frozen=True)
class JudgePackage:
    judge_id: str
    runner_sha256: str
    queries: tuple[JudgeQuery, ...]


@dataclass(frozen=True)
class QueryDisagreement:
    query_id: str
    relevance_differences: Mapping[str, tuple[int | None, int | None]]
    must_hit_a: tuple[str, ...]
    must_hit_b: tuple[str, ...]
    hard_negative_a: bool
    hard_negative_b: bool


@dataclass(frozen=True)
class AgreementSummary:
    query_count: int
    exact_agreement_count: int
    exact_agreement_rate: float
    disagreements: tuple[QueryDisagreement, ...]


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdjudicationError(f"{field} must be a non-empty string")
    return value


def judge_package_from_mapping(raw: Mapping[str, Any]) -> JudgePackage:
    if not isinstance(raw, Mapping) or raw.get("schema") != 1:
        raise AdjudicationError("unsupported judge package schema")
    judge_id = _nonempty(raw.get("judge_id"), "judge_id")
    runner_sha = _nonempty(raw.get("runner_sha256"), "runner_sha256").lower()
    if len(runner_sha) != 64 or any(ch not in "0123456789abcdef" for ch in runner_sha):
        raise AdjudicationError("runner_sha256 must be a 64-character SHA-256")
    items = raw.get("queries")
    if not isinstance(items, list) or not items:
        raise AdjudicationError("judge package queries must be a non-empty list")

    seen: set[str] = set()
    queries: list[JudgeQuery] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise AdjudicationError("judge query must be an object")
        query_id = _nonempty(item.get("query_id"), "query_id")
        if query_id in seen:
            raise AdjudicationError(f"duplicate query_id: {query_id}")
        seen.add(query_id)
        relevance_raw = item.get("relevance")
        if not isinstance(relevance_raw, Mapping):
            raise AdjudicationError(f"{query_id}.relevance must be an object")
        relevance: dict[str, int] = {}
        for memory_id, grade in relevance_raw.items():
            memory_id = _nonempty(memory_id, f"{query_id}.relevance.memory_id")
            if isinstance(grade, bool) or not isinstance(grade, int) or grade not in VALID_GRADES:
                raise AdjudicationError(f"{query_id}.relevance[{memory_id!r}] must be in 0..3")
            relevance[memory_id] = grade
        must_hit_raw = item.get("must_hit_ids", [])
        if not isinstance(must_hit_raw, list) or any(not isinstance(value, str) or not value.strip() for value in must_hit_raw):
            raise AdjudicationError(f"{query_id}.must_hit_ids must be a list of non-empty strings")
        must_hit = tuple(must_hit_raw)
        if len(must_hit) != len(set(must_hit)):
            raise AdjudicationError(f"{query_id}.must_hit_ids must not contain duplicates")
        for memory_id in must_hit:
            if relevance.get(memory_id, 0) <= 0:
                raise AdjudicationError(f"{query_id} must-hit {memory_id!r} must have positive relevance")
        hard_negative = item.get("hard_negative")
        if not isinstance(hard_negative, bool):
            raise AdjudicationError(f"{query_id}.hard_negative must be boolean")
        if hard_negative and any(grade > 0 for grade in relevance.values()):
            raise AdjudicationError(f"{query_id} cannot be hard-negative with positive relevance")
        queries.append(
            JudgeQuery(
                query_id=query_id,
                relevance=dict(sorted(relevance.items())),
                must_hit_ids=tuple(sorted(must_hit)),
                hard_negative=hard_negative,
            )
        )
    return JudgePackage(judge_id=judge_id, runner_sha256=runner_sha, queries=tuple(queries))


def compare_judges(a: JudgePackage, b: JudgePackage) -> AgreementSummary:
    if a.judge_id == b.judge_id:
        raise AdjudicationError("judge packages must have different judge_id values")
    if a.runner_sha256 != b.runner_sha256:
        raise AdjudicationError("judge packages must target the same blind runner SHA-256")
    a_by_id = {item.query_id: item for item in a.queries}
    b_by_id = {item.query_id: item for item in b.queries}
    if set(a_by_id) != set(b_by_id):
        raise AdjudicationError("judge packages must contain the same query IDs")

    disagreements: list[QueryDisagreement] = []
    for query_id in sorted(a_by_id):
        left = a_by_id[query_id]
        right = b_by_id[query_id]
        memory_ids = set(left.relevance) | set(right.relevance)
        relevance_differences = {
            memory_id: (left.relevance.get(memory_id), right.relevance.get(memory_id))
            for memory_id in sorted(memory_ids)
            if left.relevance.get(memory_id) != right.relevance.get(memory_id)
        }
        if (
            relevance_differences
            or left.must_hit_ids != right.must_hit_ids
            or left.hard_negative != right.hard_negative
        ):
            disagreements.append(
                QueryDisagreement(
                    query_id=query_id,
                    relevance_differences=relevance_differences,
                    must_hit_a=left.must_hit_ids,
                    must_hit_b=right.must_hit_ids,
                    hard_negative_a=left.hard_negative,
                    hard_negative_b=right.hard_negative,
                )
            )
    count = len(a_by_id)
    exact = count - len(disagreements)
    return AgreementSummary(
        query_count=count,
        exact_agreement_count=exact,
        exact_agreement_rate=exact / count if count else 0.0,
        disagreements=tuple(disagreements),
    )


def summary_payload(summary: AgreementSummary) -> dict[str, Any]:
    return {
        "query_count": summary.query_count,
        "exact_agreement_count": summary.exact_agreement_count,
        "exact_agreement_rate": summary.exact_agreement_rate,
        "disagreement_count": len(summary.disagreements),
        "disagreements": [asdict(item) for item in summary.disagreements],
    }
