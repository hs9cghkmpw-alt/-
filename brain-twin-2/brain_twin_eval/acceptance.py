from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .critical_slice import CriticalSliceError, rule_spec_sha256, rules_from_policy_mapping
from .dataset import is_formal_blind_run


class AcceptancePolicyError(ValueError):
    pass


_CONFIG_STRING_FIELDS = (
    "provider_label",
    "model_name",
    "model_revision",
    "instruction_id",
    "instruction_text_sha256",
    "document_template_version",
    "backend_label",
)

# These fields describe the evaluation protocol/environment, not retrieval behavior.
# They remain in the experiment manifest for auditability but are deliberately
# excluded from the frozen retrieval-configuration identity.
_NON_BEHAVIOR_BACKEND_PARAM_KEYS = {
    "evaluation_k",
    "warm_repeats",
    "corpus_memory_count",
    "base_candidate_id",
}


@dataclass(frozen=True)
class AcceptancePolicy:
    policy_id: str
    dataset_version: str
    dataset_sha256: str
    evaluator_git_commit: str
    expected_retrieval_config_sha256: str
    critical_slice_spec_sha256: str
    critical_slice_rule_count: int
    minimum_query_count: int
    expected_warm_repeats: int
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
        return (
            self.max_warm_p95_seconds is not None
            and self.max_peak_rss_after_bytes is not None
            and self.critical_slice_rule_count > 0
            and self.expected_warm_repeats > 0
        )


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    observed: float | int | str | bool | None
    required: float | int | str | bool | None


@dataclass(frozen=True)
class AcceptanceDecision:
    status: str
    policy_id: str
    policy_sha256: str
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AcceptancePolicyError(f"{field} must be an object")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcceptancePolicyError(f"{field} must be a non-empty string")
    return value


def _hex_sha(value: Any, length: int, field: str) -> str:
    text = _nonempty(value, field).lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise AcceptancePolicyError(
            f"{field} must be a {length}-character hexadecimal SHA"
        )
    return text


def _fraction(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcceptancePolicyError(f"{field} must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise AcceptancePolicyError(f"{field} must be in [0, 1]")
    return number


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AcceptancePolicyError(f"{field} must be a positive integer")
    return value


def _validate_nested_model_revisions(
    value: Any, path: str = "backend_params"
) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower().replace("-", "_")
            child = f"{path}.{key}"
            if key_text.endswith("model_revision"):
                _hex_sha(nested, 40, child)
            else:
                _validate_nested_model_revisions(nested, child)
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_nested_model_revisions(nested, f"{path}[{index}]")


def _behavior_backend_params(
    backend_params: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in backend_params.items()
        if str(key) not in _NON_BEHAVIOR_BACKEND_PARAM_KEYS
    }


def retrieval_config_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash only behavior-changing retrieval configuration.

    Runtime/evidence fields such as warm-repeat count and corpus size are excluded.
    This lets the retrieval configuration be frozen before the blind runner/query
    package is introduced, while the full manifest still records those fields.
    """
    manifest = _mapping(manifest, "manifest")
    config: dict[str, Any] = {}
    for field in _CONFIG_STRING_FIELDS:
        config[field] = _nonempty(manifest.get(field), f"manifest.{field}")

    _hex_sha(config["model_revision"], 40, "manifest.model_revision")
    _hex_sha(
        config["instruction_text_sha256"],
        64,
        "manifest.instruction_text_sha256",
    )

    dimension = manifest.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise AcceptancePolicyError(
            "manifest.dimension must be a positive integer"
        )

    normalized = manifest.get("normalized")
    if not isinstance(normalized, bool):
        raise AcceptancePolicyError("manifest.normalized must be boolean")

    backend_params = _mapping(
        manifest.get("backend_params"), "manifest.backend_params"
    )
    _validate_nested_model_revisions(backend_params)

    config["dimension"] = dimension
    config["normalized"] = normalized
    config["backend_params"] = _behavior_backend_params(backend_params)

    canonical = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def policy_from_mapping(raw: Mapping[str, Any]) -> AcceptancePolicy:
    raw = _mapping(raw, "policy root")

    minimum_query_count = _positive_int(
        raw.get("minimum_query_count"), "minimum_query_count"
    )
    expected_warm_repeats = _positive_int(
        raw.get("expected_warm_repeats", 30), "expected_warm_repeats"
    )

    max_drift = raw.get("max_warm_rank_drift_count", 0)
    if (
        isinstance(max_drift, bool)
        or not isinstance(max_drift, int)
        or max_drift < 0
    ):
        raise AcceptancePolicyError(
            "max_warm_rank_drift_count must be a non-negative integer"
        )
    if max_drift != 0:
        raise AcceptancePolicyError(
            "max_warm_rank_drift_count must be 0 because any ranking drift is selection-ineligible"
        )

    warm = raw.get("max_warm_p95_seconds")
    if warm is not None:
        if (
            isinstance(warm, bool)
            or not isinstance(warm, (int, float))
            or float(warm) <= 0
        ):
            raise AcceptancePolicyError(
                "max_warm_p95_seconds must be positive or null"
            )
        warm = float(warm)

    rss = raw.get("max_peak_rss_after_bytes")
    if rss is not None and (
        isinstance(rss, bool) or not isinstance(rss, int) or rss <= 0
    ):
        raise AcceptancePolicyError(
            "max_peak_rss_after_bytes must be a positive integer or null"
        )

    try:
        critical_rules = rules_from_policy_mapping(raw)
    except CriticalSliceError as exc:
        raise AcceptancePolicyError(str(exc)) from exc

    return AcceptancePolicy(
        policy_id=_nonempty(raw.get("policy_id"), "policy_id"),
        dataset_version=_nonempty(
            raw.get("dataset_version"), "dataset_version"
        ),
        dataset_sha256=_hex_sha(
            raw.get("dataset_sha256"), 64, "dataset_sha256"
        ),
        evaluator_git_commit=_hex_sha(
            raw.get("evaluator_git_commit"), 40, "evaluator_git_commit"
        ),
        expected_retrieval_config_sha256=_hex_sha(
            raw.get("expected_retrieval_config_sha256"),
            64,
            "expected_retrieval_config_sha256",
        ),
        critical_slice_spec_sha256=rule_spec_sha256(critical_rules),
        critical_slice_rule_count=len(critical_rules),
        minimum_query_count=minimum_query_count,
        expected_warm_repeats=expected_warm_repeats,
        min_recall_at_5=_fraction(
            raw.get("min_recall_at_5"), "min_recall_at_5"
        ),
        min_mrr_at_10=_fraction(raw.get("min_mrr_at_10"), "min_mrr_at_10"),
        min_ndcg_at_10=_fraction(raw.get("min_ndcg_at_10"), "min_ndcg_at_10"),
        min_must_hit_at_5=_fraction(
            raw.get("min_must_hit_at_5"), "min_must_hit_at_5"
        ),
        max_false_positive_at_5=_fraction(
            raw.get("max_false_positive_at_5"), "max_false_positive_at_5"
        ),
        max_warm_p95_seconds=warm,
        max_peak_rss_after_bytes=rss,
        max_warm_rank_drift_count=max_drift,
    )


def policy_sha256(policy: AcceptancePolicy) -> str:
    payload = json.dumps(
        asdict(policy),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _metric(overall: Mapping[str, Any], field: str) -> float:
    value = overall.get(field)
    if value is None:
        raise AcceptancePolicyError(f"report.overall.{field} is required")
    return _fraction(value, f"report.overall.{field}")


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise AcceptancePolicyError(f"{field} must be boolean")
    return value


def _critical_attestation_gates(
    payload: Mapping[str, Any], policy: AcceptancePolicy
) -> list[GateResult]:
    attestation = payload.get("formal_attestation")
    if not isinstance(attestation, Mapping):
        attestation = {}

    critical = attestation.get("critical_slice_gates")
    if not isinstance(critical, Mapping):
        critical = {}

    observed_spec = critical.get("spec_sha256")
    observed_count = critical.get("rule_count")
    observed_passed = critical.get("all_passed")

    return [
        GateResult(
            "policy_attestation",
            attestation.get("policy_sha256") == policy_sha256(policy),
            attestation.get("policy_sha256"),
            policy_sha256(policy),
        ),
        GateResult(
            "retrieval_config_attestation",
            attestation.get("retrieval_config_sha256")
            == policy.expected_retrieval_config_sha256,
            attestation.get("retrieval_config_sha256"),
            policy.expected_retrieval_config_sha256,
        ),
        GateResult(
            "critical_slice_spec_sha256",
            observed_spec == policy.critical_slice_spec_sha256,
            observed_spec,
            policy.critical_slice_spec_sha256,
        ),
        GateResult(
            "critical_slice_rule_count",
            observed_count == policy.critical_slice_rule_count,
            observed_count,
            policy.critical_slice_rule_count,
        ),
        GateResult(
            "critical_slice_gates",
            observed_passed is True,
            observed_passed,
            True,
        ),
    ]


def evaluate_acceptance(
    payload: Mapping[str, Any],
    policy: AcceptancePolicy,
    *,
    formal: bool = True,
) -> AcceptanceDecision:
    payload = _mapping(payload, "report root")

    if formal and not policy.formal_ready:
        return AcceptanceDecision(
            status="blocked",
            policy_id=policy.policy_id,
            policy_sha256=policy_sha256(policy),
            gates=(),
        )

    manifest = _mapping(payload.get("manifest"), "report.manifest")
    overall = _mapping(payload.get("overall"), "report.overall")
    recall = _mapping(
        overall.get("recall_at"), "report.overall.recall_at"
    )
    latency = _mapping(payload.get("latency"), "report.latency")
    warm_block = _mapping(latency.get("warm"), "report.latency.warm")
    resources = _mapping(payload.get("resources"), "report.resources")

    query_count = overall.get("query_count")
    if isinstance(query_count, bool) or not isinstance(query_count, int):
        raise AcceptancePolicyError(
            "report.overall.query_count must be an integer"
        )

    drift = latency.get("warm_rank_drift_count")
    if (
        isinstance(drift, bool)
        or not isinstance(drift, int)
        or drift < 0
    ):
        raise AcceptancePolicyError(
            "report.latency.warm_rank_drift_count must be a non-negative integer"
        )

    if "5" not in recall:
        raise AcceptancePolicyError("report.overall.recall_at.5 is required")

    recall5 = _fraction(recall["5"], "report.overall.recall_at.5")
    mrr = _metric(overall, "mrr_at_10")
    ndcg = _metric(overall, "ndcg_at_10")
    must_hit = _metric(overall, "must_hit_at_5")
    false_positive = _metric(overall, "false_positive_at_5")
    config_sha = retrieval_config_sha256(manifest)
    reproducible = _boolean(payload.get("reproducible"), "report.reproducible")
    selection_eligible = _boolean(
        payload.get("selection_eligible"), "report.selection_eligible"
    )

    gates = [
        GateResult(
            "dataset_version",
            payload.get("dataset_version") == policy.dataset_version,
            payload.get("dataset_version"),
            policy.dataset_version,
        ),
        GateResult(
            "dataset_sha256",
            payload.get("dataset_sha256") == policy.dataset_sha256,
            payload.get("dataset_sha256"),
            policy.dataset_sha256,
        ),
        GateResult(
            "evaluator_git_commit",
            manifest.get("git_commit") == policy.evaluator_git_commit,
            manifest.get("git_commit"),
            policy.evaluator_git_commit,
        ),
        GateResult(
            "retrieval_config_sha256",
            config_sha == policy.expected_retrieval_config_sha256,
            config_sha,
            policy.expected_retrieval_config_sha256,
        ),
        GateResult(
            "query_count",
            query_count >= policy.minimum_query_count,
            query_count,
            policy.minimum_query_count,
        ),
        GateResult(
            "recall_at_5",
            recall5 >= policy.min_recall_at_5,
            recall5,
            policy.min_recall_at_5,
        ),
        GateResult(
            "mrr_at_10",
            mrr >= policy.min_mrr_at_10,
            mrr,
            policy.min_mrr_at_10,
        ),
        GateResult(
            "ndcg_at_10",
            ndcg >= policy.min_ndcg_at_10,
            ndcg,
            policy.min_ndcg_at_10,
        ),
        GateResult(
            "must_hit_at_5",
            must_hit >= policy.min_must_hit_at_5,
            must_hit,
            policy.min_must_hit_at_5,
        ),
        GateResult(
            "false_positive_at_5",
            false_positive <= policy.max_false_positive_at_5,
            false_positive,
            policy.max_false_positive_at_5,
        ),
        GateResult(
            "warm_rank_drift_count",
            drift <= policy.max_warm_rank_drift_count,
            drift,
            policy.max_warm_rank_drift_count,
        ),
        GateResult(
            "reproducible",
            reproducible and drift == 0,
            reproducible,
            True,
        ),
        GateResult(
            "selection_eligible",
            selection_eligible and reproducible and drift == 0,
            selection_eligible,
            True,
        ),
    ]

    if formal:
        formal_blind_run = is_formal_blind_run(
            str(payload.get("judgement_visibility", "")), payload.get("split")
        )
        gates.extend(
            [
                GateResult(
                    "acceptance_blind_ready",
                    payload.get("acceptance_blind_ready") is True
                    and formal_blind_run,
                    payload.get("acceptance_blind_ready"),
                    True,
                ),
                GateResult(
                    "held_out_judgements",
                    payload.get("judgement_visibility") == "held_out",
                    payload.get("judgement_visibility"),
                    "held_out",
                ),
                GateResult(
                    "blind_split",
                    payload.get("split") == "blind",
                    payload.get("split"),
                    "blind",
                ),
                GateResult(
                    "query_details_redacted",
                    payload.get("query_details_redacted") is True,
                    payload.get("query_details_redacted"),
                    True,
                ),
            ]
        )

        warm = warm_block.get("p95_seconds")
        rss = resources.get("peak_rss_after_bytes")
        warm_samples = warm_block.get("samples")

        if (
            isinstance(warm, bool)
            or not isinstance(warm, (int, float))
            or float(warm) < 0
        ):
            raise AcceptancePolicyError(
                "formal report must contain non-negative warm p95 latency"
            )
        if isinstance(rss, bool) or not isinstance(rss, int) or rss <= 0:
            raise AcceptancePolicyError(
                "formal report must contain positive peak RSS"
            )
        if (
            isinstance(warm_samples, bool)
            or not isinstance(warm_samples, int)
            or warm_samples < 0
        ):
            raise AcceptancePolicyError(
                "formal report must contain warm sample count"
            )

        expected_warm_samples = query_count * policy.expected_warm_repeats
        gates.extend(
            [
                GateResult(
                    "warm_sample_count",
                    warm_samples == expected_warm_samples,
                    warm_samples,
                    expected_warm_samples,
                ),
                GateResult(
                    "warm_p95_seconds",
                    float(warm) <= float(policy.max_warm_p95_seconds),
                    float(warm),
                    policy.max_warm_p95_seconds,
                ),
                GateResult(
                    "peak_rss_after_bytes",
                    rss <= int(policy.max_peak_rss_after_bytes),
                    rss,
                    policy.max_peak_rss_after_bytes,
                ),
            ]
        )
        gates.extend(_critical_attestation_gates(payload, policy))

    return AcceptanceDecision(
        status="pass" if all(gate.passed for gate in gates) else "fail",
        policy_id=policy.policy_id,
        policy_sha256=policy_sha256(policy),
        gates=tuple(gates),
    )
