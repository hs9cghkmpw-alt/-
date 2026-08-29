from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


class AcceptancePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class AcceptancePolicy:
    policy_id: str
    dataset_version: str
    dataset_sha256: str
    evaluator_git_commit: str
    minimum_query_count: int
    min_recall_at_5: float
    min_mrr_at_10: float
    min_ndcg_at_10: float
    min_must_hit_at_5: float
    max_false_positive_at_5: float
    max_warm_p95_seconds: float | None
    max_peak_rss_after_bytes: int | None
    max_warm_rank_drift_count: int = 0

    @property
    def formal_ready(self) -> bool:
        return self.max_warm_p95_seconds is not None and self.max_peak_rss_after_bytes is not None


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    observed: float | int | str | None
    required: float | int | str | None


@dataclass(frozen=True)
class AcceptanceDecision:
    status: str
    policy_id: str
    policy_sha256: str
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcceptancePolicyError(f"{field} must be a non-empty string")
    return value


def _sha40(value: Any, field: str) -> str:
    text = _nonempty(value, field).lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise AcceptancePolicyError(f"{field} must be a full 40-character git SHA")
    return text


def _sha64(value: Any, field: str) -> str:
    text = _nonempty(value, field).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise AcceptancePolicyError(f"{field} must be a 64-character SHA-256")
    return text


def _fraction(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcceptancePolicyError(f"{field} must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise AcceptancePolicyError(f"{field} must be in [0, 1]")
    return number


def policy_from_mapping(raw: Mapping[str, Any]) -> AcceptancePolicy:
    if not isinstance(raw, Mapping):
        raise AcceptancePolicyError("policy root must be an object")
    minimum_query_count = raw.get("minimum_query_count")
    if isinstance(minimum_query_count, bool) or not isinstance(minimum_query_count, int) or minimum_query_count <= 0:
        raise AcceptancePolicyError("minimum_query_count must be a positive integer")
    max_drift = raw.get("max_warm_rank_drift_count", 0)
    if isinstance(max_drift, bool) or not isinstance(max_drift, int) or max_drift < 0:
        raise AcceptancePolicyError("max_warm_rank_drift_count must be a non-negative integer")

    warm = raw.get("max_warm_p95_seconds")
    if warm is not None:
        if isinstance(warm, bool) or not isinstance(warm, (int, float)) or float(warm) <= 0:
            raise AcceptancePolicyError("max_warm_p95_seconds must be positive or null")
        warm = float(warm)

    rss = raw.get("max_peak_rss_after_bytes")
    if rss is not None:
        if isinstance(rss, bool) or not isinstance(rss, int) or rss <= 0:
            raise AcceptancePolicyError("max_peak_rss_after_bytes must be a positive integer or null")

    return AcceptancePolicy(
        policy_id=_nonempty(raw.get("policy_id"), "policy_id"),
        dataset_version=_nonempty(raw.get("dataset_version"), "dataset_version"),
        dataset_sha256=_sha64(raw.get("dataset_sha256"), "dataset_sha256"),
        evaluator_git_commit=_sha40(raw.get("evaluator_git_commit"), "evaluator_git_commit"),
        minimum_query_count=minimum_query_count,
        min_recall_at_5=_fraction(raw.get("min_recall_at_5"), "min_recall_at_5"),
        min_mrr_at_10=_fraction(raw.get("min_mrr_at_10"), "min_mrr_at_10"),
        min_ndcg_at_10=_fraction(raw.get("min_ndcg_at_10"), "min_ndcg_at_10"),
        min_must_hit_at_5=_fraction(raw.get("min_must_hit_at_5"), "min_must_hit_at_5"),
        max_false_positive_at_5=_fraction(raw.get("max_false_positive_at_5"), "max_false_positive_at_5"),
        max_warm_p95_seconds=warm,
        max_peak_rss_after_bytes=rss,
        max_warm_rank_drift_count=max_drift,
    )


def policy_sha256(policy: AcceptancePolicy) -> str:
    payload = json.dumps(asdict(policy), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _metric(payload: Mapping[str, Any], field: str) -> float:
    overall = payload.get("overall")
    if not isinstance(overall, Mapping):
        raise AcceptancePolicyError("report.overall must be an object")
    value = overall.get(field)
    if value is None:
        raise AcceptancePolicyError(f"report.overall.{field} is required")
    return _fraction(value, f"report.overall.{field}")


def evaluate_acceptance(
    payload: Mapping[str, Any],
    policy: AcceptancePolicy,
    *,
    formal: bool = True,
) -> AcceptanceDecision:
    if not isinstance(payload, Mapping):
        raise AcceptancePolicyError("report root must be an object")

    if formal and not policy.formal_ready:
        return AcceptanceDecision(
            status="blocked",
            policy_id=policy.policy_id,
            policy_sha256=policy_sha256(policy),
            gates=(),
        )

    manifest = payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise AcceptancePolicyError("report.manifest must be an object")
    recall = payload.get("overall", {}).get("recall_at", {})
    if not isinstance(recall, Mapping) or "5" not in recall:
        raise AcceptancePolicyError("report.overall.recall_at.5 is required")
    query_count = payload.get("overall", {}).get("query_count")
    if isinstance(query_count, bool) or not isinstance(query_count, int):
        raise AcceptancePolicyError("report.overall.query_count must be an integer")

    warm = payload.get("latency", {}).get("warm", {}).get("p95_seconds")
    rss = payload.get("resources", {}).get("peak_rss_after_bytes")
    drift = payload.get("latency", {}).get("warm_rank_drift_count")
    if isinstance(drift, bool) or not isinstance(drift, int):
        raise AcceptancePolicyError("report.latency.warm_rank_drift_count must be an integer")

    gates = [
        GateResult("dataset_version", payload.get("dataset_version") == policy.dataset_version, payload.get("dataset_version"), policy.dataset_version),
        GateResult("dataset_sha256", payload.get("dataset_sha256") == policy.dataset_sha256, payload.get("dataset_sha256"), policy.dataset_sha256),
        GateResult("evaluator_git_commit", manifest.get("git_commit") == policy.evaluator_git_commit, manifest.get("git_commit"), policy.evaluator_git_commit),
        GateResult("query_count", query_count >= policy.minimum_query_count, query_count, policy.minimum_query_count),
        GateResult("recall_at_5", _fraction(recall["5"], "report.overall.recall_at.5") >= policy.min_recall_at_5, float(recall["5"]), policy.min_recall_at_5),
        GateResult("mrr_at_10", _metric(payload, "mrr_at_10") >= policy.min_mrr_at_10, _metric(payload, "mrr_at_10"), policy.min_mrr_at_10),
        GateResult("ndcg_at_10", _metric(payload, "ndcg_at_10") >= policy.min_ndcg_at_10, _metric(payload, "ndcg_at_10"), policy.min_ndcg_at_10),
        GateResult("must_hit_at_5", _metric(payload, "must_hit_at_5") >= policy.min_must_hit_at_5, _metric(payload, "must_hit_at_5"), policy.min_must_hit_at_5),
        GateResult("false_positive_at_5", _metric(payload, "false_positive_at_5") <= policy.max_false_positive_at_5, _metric(payload, "false_positive_at_5"), policy.max_false_positive_at_5),
        GateResult("warm_rank_drift_count", drift <= policy.max_warm_rank_drift_count, drift, policy.max_warm_rank_drift_count),
    ]

    if formal:
        gates.extend(
            [
                GateResult("held_out_judgements", payload.get("judgement_visibility") == "held_out", payload.get("judgement_visibility"), "held_out"),
                GateResult("blind_split", payload.get("split") == "blind", payload.get("split"), "blind"),
                GateResult("query_details_redacted", payload.get("query_details_redacted") is True, payload.get("query_details_redacted"), True),
            ]
        )
        if isinstance(warm, bool) or not isinstance(warm, (int, float)):
            raise AcceptancePolicyError("formal report must contain warm p95 latency")
        if isinstance(rss, bool) or not isinstance(rss, int):
            raise AcceptancePolicyError("formal report must contain peak RSS")
        gates.extend(
            [
                GateResult("warm_p95_seconds", float(warm) <= float(policy.max_warm_p95_seconds), float(warm), policy.max_warm_p95_seconds),
                GateResult("peak_rss_after_bytes", rss <= int(policy.max_peak_rss_after_bytes), rss, policy.max_peak_rss_after_bytes),
            ]
        )

    return AcceptanceDecision(
        status="pass" if all(gate.passed for gate in gates) else "fail",
        policy_id=policy.policy_id,
        policy_sha256=policy_sha256(policy),
        gates=tuple(gates),
    )
