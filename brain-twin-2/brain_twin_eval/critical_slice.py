from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .runner import AggregateMetrics, EvaluationRun


class CriticalSliceError(ValueError):
    pass


VALID_METRICS = {
    "recall_at_5",
    "mrr_at_10",
    "ndcg_at_10",
    "must_hit_at_5",
    "false_positive_at_5",
}
VALID_COMPARATORS = {"min", "max"}


@dataclass(frozen=True)
class CriticalSliceRule:
    slice_tag: str
    metric: str
    comparator: str
    threshold: float


@dataclass(frozen=True)
class CriticalSliceSummary:
    spec_sha256: str
    rule_count: int
    all_passed: bool


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CriticalSliceError(f"{field} must be a non-empty string")
    return value


def _fraction(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CriticalSliceError(f"{field} must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise CriticalSliceError(f"{field} must be in [0, 1]")
    return number


def rules_from_policy_mapping(raw: Mapping[str, Any]) -> tuple[CriticalSliceRule, ...]:
    if not isinstance(raw, Mapping):
        raise CriticalSliceError("policy root must be an object")
    items = raw.get("critical_slice_rules", [])
    if not isinstance(items, list):
        raise CriticalSliceError("critical_slice_rules must be a list")
    rules: list[CriticalSliceRule] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise CriticalSliceError(f"critical_slice_rules[{index}] must be an object")
        slice_tag = _nonempty(item.get("slice_tag"), f"critical_slice_rules[{index}].slice_tag")
        metric = _nonempty(item.get("metric"), f"critical_slice_rules[{index}].metric")
        comparator = _nonempty(item.get("comparator"), f"critical_slice_rules[{index}].comparator")
        if metric not in VALID_METRICS:
            raise CriticalSliceError(f"unsupported critical slice metric: {metric}")
        if comparator not in VALID_COMPARATORS:
            raise CriticalSliceError(f"unsupported critical slice comparator: {comparator}")
        if metric == "false_positive_at_5" and comparator != "max":
            raise CriticalSliceError("false_positive_at_5 critical gates must use comparator=max")
        if metric != "false_positive_at_5" and comparator != "min":
            raise CriticalSliceError(f"{metric} critical gates must use comparator=min")
        key = (slice_tag, metric)
        if key in seen:
            raise CriticalSliceError(f"duplicate critical slice rule: {slice_tag}/{metric}")
        seen.add(key)
        rules.append(
            CriticalSliceRule(
                slice_tag=slice_tag,
                metric=metric,
                comparator=comparator,
                threshold=_fraction(item.get("threshold"), f"critical_slice_rules[{index}].threshold"),
            )
        )
    return tuple(sorted(rules, key=lambda rule: (rule.slice_tag, rule.metric)))


def rule_spec_sha256(rules: Sequence[CriticalSliceRule]) -> str:
    payload = [
        {
            "slice_tag": rule.slice_tag,
            "metric": rule.metric,
            "comparator": rule.comparator,
            "threshold": rule.threshold,
        }
        for rule in sorted(rules, key=lambda rule: (rule.slice_tag, rule.metric))
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _metric_value(metrics: AggregateMetrics, metric: str) -> float | None:
    if metric == "recall_at_5":
        return float(metrics.recall_at[5])
    if metric == "mrr_at_10":
        return float(metrics.mrr_at_10)
    if metric == "ndcg_at_10":
        return float(metrics.ndcg_at_10)
    if metric == "must_hit_at_5":
        return None if metrics.must_hit_at_5 is None else float(metrics.must_hit_at_5)
    if metric == "false_positive_at_5":
        return float(metrics.false_positive_at_5)
    raise CriticalSliceError(f"unsupported critical slice metric: {metric}")


def evaluate_critical_slices(run: EvaluationRun, rules: Sequence[CriticalSliceRule]) -> CriticalSliceSummary:
    passed = run.selection_eligible
    for rule in rules:
        metrics = run.per_slice.get(rule.slice_tag)
        if metrics is None or metrics.query_count <= 0:
            raise CriticalSliceError(f"critical slice missing from held-out run: {rule.slice_tag}")
        value = _metric_value(metrics, rule.metric)
        if value is None:
            passed = False
            continue
        if rule.comparator == "min":
            passed = passed and value >= rule.threshold
        else:
            passed = passed and value <= rule.threshold
    return CriticalSliceSummary(
        spec_sha256=rule_spec_sha256(rules),
        rule_count=len(rules),
        all_passed=passed,
    )


def summary_payload(summary: CriticalSliceSummary) -> dict[str, Any]:
    """Leak-resistant summary: no slice names, thresholds, or observed blind scores."""
    return {
        "spec_sha256": summary.spec_sha256,
        "rule_count": summary.rule_count,
        "all_passed": summary.all_passed,
    }


def verify_summary(raw: Any, rules: Sequence[CriticalSliceRule]) -> bool:
    if not isinstance(raw, Mapping):
        return False
    return (
        raw.get("spec_sha256") == rule_spec_sha256(rules)
        and raw.get("rule_count") == len(rules)
        and raw.get("all_passed") is True
    )
