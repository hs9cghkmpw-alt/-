"""Model-independent evaluation contract for the future Brain Twin organizer LLM.

This module is evaluation-only. Production ``brain_twin`` must not import it.
The organizer is allowed to derive metadata, never to replace the captured raw text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
import math
import unicodedata
from typing import Any, Mapping


ORGANIZER_MEMORY_TYPES = (
    "fact",
    "experience",
    "thought",
    "decision",
    "preference",
    "goal",
    "knowledge",
    "person",
    "project",
)

OUTPUT_KEYS = frozenset(
    {
        "memory_worthy",
        "memory_type",
        "title",
        "topics",
        "entities",
        "event_date",
        "importance",
        "confidence",
        "link_candidates",
    }
)


class OrganizerEvaluationError(ValueError):
    """Raised when an evaluation artifact violates the frozen contract."""


@dataclass(frozen=True)
class OrganizerContextMemory:
    memory_id: str
    title: str
    summary: str

    def canonical(self) -> dict[str, str]:
        return {
            "memory_id": self.memory_id,
            "title": self.title,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class OrganizerGold:
    memory_worthy: bool
    memory_type: str
    topics: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    event_date: str | None = None
    importance: int = 1
    link_candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.memory_type not in ORGANIZER_MEMORY_TYPES:
            raise OrganizerEvaluationError(f"unsupported gold memory_type: {self.memory_type}")
        if isinstance(self.importance, bool) or not isinstance(self.importance, int) or not 1 <= self.importance <= 5:
            raise OrganizerEvaluationError("gold importance must be an integer in [1, 5]")
        if self.event_date is not None:
            _validate_iso_date(self.event_date, "gold event_date")
        _validate_unique_strings(self.topics, "gold topics")
        _validate_unique_strings(self.entities, "gold entities")
        _validate_unique_strings(self.link_candidates, "gold link_candidates")

    def canonical(self) -> dict[str, Any]:
        return {
            "memory_worthy": self.memory_worthy,
            "memory_type": self.memory_type,
            "topics": list(self.topics),
            "entities": list(self.entities),
            "event_date": self.event_date,
            "importance": self.importance,
            "link_candidates": list(self.link_candidates),
        }


@dataclass(frozen=True)
class OrganizerSample:
    sample_id: str
    raw_text: str
    created_at: str
    gold: OrganizerGold
    slices: tuple[str, ...]
    context_memories: tuple[OrganizerContextMemory, ...] = ()

    def __post_init__(self) -> None:
        if not self.sample_id.strip():
            raise OrganizerEvaluationError("sample_id must not be blank")
        if not self.raw_text.strip():
            raise OrganizerEvaluationError(f"raw_text must not be blank: {self.sample_id}")
        if not self.slices:
            raise OrganizerEvaluationError(f"sample must have at least one slice: {self.sample_id}")
        _validate_unique_strings(self.slices, f"slices for {self.sample_id}")
        context_ids = [item.memory_id for item in self.context_memories]
        if len(context_ids) != len(set(context_ids)):
            raise OrganizerEvaluationError(f"duplicate context memory id: {self.sample_id}")
        unknown_links = set(self.gold.link_candidates) - set(context_ids)
        if unknown_links:
            raise OrganizerEvaluationError(
                f"gold link target is not in context for {self.sample_id}: {sorted(unknown_links)}"
            )

    def canonical(self, *, include_gold: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sample_id": self.sample_id,
            "raw_text": self.raw_text,
            "created_at": self.created_at,
            "slices": list(self.slices),
            "context_memories": [item.canonical() for item in self.context_memories],
        }
        if include_gold:
            payload["gold"] = self.gold.canonical()
        return payload


@dataclass(frozen=True)
class OrganizerDataset:
    version: str
    judgement_visibility: str
    samples: tuple[OrganizerSample, ...]

    def __post_init__(self) -> None:
        if self.judgement_visibility not in {"open", "held_out"}:
            raise OrganizerEvaluationError("judgement_visibility must be 'open' or 'held_out'")
        if not self.samples:
            raise OrganizerEvaluationError("organizer dataset must not be empty")
        ids = [sample.sample_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise OrganizerEvaluationError("duplicate organizer sample id")

    @property
    def canonical_sha256(self) -> str:
        payload = {
            "version": self.version,
            "judgement_visibility": self.judgement_visibility,
            "samples": [sample.canonical(include_gold=True) for sample in self.samples],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def public_payload(self) -> dict[str, Any]:
        """Return model-side inputs without gold judgements or slice labels."""
        return {
            "version": self.version,
            "dataset_sha256": self.canonical_sha256,
            "samples": [
                {
                    "sample_id": sample.sample_id,
                    "raw_text": sample.raw_text,
                    "created_at": sample.created_at,
                    "context_memories": [item.canonical() for item in sample.context_memories],
                }
                for sample in self.samples
            ],
        }


@dataclass(frozen=True)
class OrganizerEntityPrediction:
    name: str
    confidence: float


@dataclass(frozen=True)
class OrganizerPrediction:
    memory_worthy: bool
    memory_type: str
    title: str
    topics: tuple[str, ...]
    entities: tuple[OrganizerEntityPrediction, ...]
    event_date: str | None
    importance: int
    confidence: float
    link_candidates: tuple[str, ...]

    @property
    def entity_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.entities)


@dataclass
class _Accumulator:
    sample_count: int = 0
    valid_count: int = 0
    strict_count: int = 0
    memory_worthy_correct: int = 0
    mw_tp: int = 0
    mw_fp: int = 0
    mw_fn: int = 0
    type_total: int = 0
    type_correct: int = 0
    topic_tp: int = 0
    topic_fp: int = 0
    topic_fn: int = 0
    entity_tp: int = 0
    entity_fp: int = 0
    entity_fn: int = 0
    predicted_entity_count: int = 0
    hallucinated_entity_count: int = 0
    date_present_total: int = 0
    date_present_correct: int = 0
    date_absent_total: int = 0
    date_absent_correct: int = 0
    importance_total: int = 0
    importance_abs_error: float = 0.0
    importance_within_one: int = 0
    link_tp: int = 0
    link_fp: int = 0
    link_fn: int = 0
    confidence_brier_sum: float = 0.0


@dataclass(frozen=True)
class OrganizerEvaluationResult:
    dataset_version: str
    dataset_sha256: str
    judgement_visibility: str
    overall: dict[str, Any]
    per_slice: dict[str, dict[str, Any]]
    invalid_sample_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self, *, redact_held_out: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dataset_version": self.dataset_version,
            "dataset_sha256": self.dataset_sha256,
            "judgement_visibility": self.judgement_visibility,
            "overall": self.overall,
        }
        if self.judgement_visibility == "held_out" and redact_held_out:
            payload["per_slice_redacted"] = True
            payload["invalid_sample_count"] = len(self.invalid_sample_ids)
        else:
            payload["per_slice"] = self.per_slice
            payload["invalid_sample_ids"] = list(self.invalid_sample_ids)
        return payload


def normalize_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def parse_prediction(raw: Any, *, allowed_link_ids: set[str]) -> OrganizerPrediction:
    """Parse one model output using a strict, dependency-free JSON contract.

    Extra keys are rejected. This is intentional: fields such as ``content`` or
    ``rewritten_text`` would violate the non-destructive organizer boundary.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OrganizerEvaluationError("organizer output is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise OrganizerEvaluationError("organizer output must be a JSON object")

    keys = frozenset(raw)
    if keys != OUTPUT_KEYS:
        missing = sorted(OUTPUT_KEYS - keys)
        extra = sorted(keys - OUTPUT_KEYS)
        raise OrganizerEvaluationError(f"organizer output keys mismatch; missing={missing}, extra={extra}")

    memory_worthy = raw["memory_worthy"]
    if type(memory_worthy) is not bool:
        raise OrganizerEvaluationError("memory_worthy must be boolean")

    memory_type = raw["memory_type"]
    if not isinstance(memory_type, str) or memory_type not in ORGANIZER_MEMORY_TYPES:
        raise OrganizerEvaluationError("memory_type is invalid")

    title = raw["title"]
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 48:
        raise OrganizerEvaluationError("title must be a non-empty string of at most 48 characters")
    title = title.strip()

    topics = _parse_string_list(raw["topics"], "topics", max_items=8)

    entity_raw = raw["entities"]
    if not isinstance(entity_raw, list) or len(entity_raw) > 12:
        raise OrganizerEvaluationError("entities must be an array with at most 12 items")
    entities: list[OrganizerEntityPrediction] = []
    seen_entities: set[str] = set()
    for item in entity_raw:
        if not isinstance(item, dict) or frozenset(item) != {"name", "confidence"}:
            raise OrganizerEvaluationError("each entity must contain exactly name and confidence")
        name = item["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise OrganizerEvaluationError("entity name is invalid")
        confidence = _parse_probability(item["confidence"], "entity confidence")
        normalized = normalize_label(name)
        if normalized in seen_entities:
            raise OrganizerEvaluationError("duplicate entity name")
        seen_entities.add(normalized)
        entities.append(OrganizerEntityPrediction(name=name.strip(), confidence=confidence))

    event_date = raw["event_date"]
    if event_date is not None:
        if not isinstance(event_date, str):
            raise OrganizerEvaluationError("event_date must be null or YYYY-MM-DD")
        _validate_iso_date(event_date, "event_date")

    importance = raw["importance"]
    if isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 5:
        raise OrganizerEvaluationError("importance must be an integer in [1, 5]")

    confidence = _parse_probability(raw["confidence"], "confidence")
    links = _parse_string_list(raw["link_candidates"], "link_candidates", max_items=5)
    unknown_links = set(links) - allowed_link_ids
    if unknown_links:
        raise OrganizerEvaluationError(f"link candidate not supplied in context: {sorted(unknown_links)}")

    return OrganizerPrediction(
        memory_worthy=memory_worthy,
        memory_type=memory_type,
        title=title,
        topics=topics,
        entities=tuple(entities),
        event_date=event_date,
        importance=importance,
        confidence=confidence,
        link_candidates=links,
    )


def evaluate_organizer(
    dataset: OrganizerDataset,
    predictions: Mapping[str, Any],
) -> OrganizerEvaluationResult:
    unknown_ids = set(predictions) - {sample.sample_id for sample in dataset.samples}
    if unknown_ids:
        raise OrganizerEvaluationError(f"predictions contain unknown sample ids: {sorted(unknown_ids)}")

    parsed: dict[str, OrganizerPrediction | None] = {}
    invalid_ids: list[str] = []
    for sample in dataset.samples:
        raw = predictions.get(sample.sample_id)
        if raw is None:
            parsed[sample.sample_id] = None
            invalid_ids.append(sample.sample_id)
            continue
        try:
            parsed[sample.sample_id] = parse_prediction(
                raw,
                allowed_link_ids={item.memory_id for item in sample.context_memories},
            )
        except OrganizerEvaluationError:
            parsed[sample.sample_id] = None
            invalid_ids.append(sample.sample_id)

    overall_acc = _score_samples(dataset.samples, parsed)
    all_slices = sorted({slice_name for sample in dataset.samples for slice_name in sample.slices})
    per_slice: dict[str, dict[str, Any]] = {}
    for slice_name in all_slices:
        subset = tuple(sample for sample in dataset.samples if slice_name in sample.slices)
        per_slice[slice_name] = _metrics(_score_samples(subset, parsed))

    return OrganizerEvaluationResult(
        dataset_version=dataset.version,
        dataset_sha256=dataset.canonical_sha256,
        judgement_visibility=dataset.judgement_visibility,
        overall=_metrics(overall_acc),
        per_slice=per_slice,
        invalid_sample_ids=tuple(invalid_ids),
    )


def oracle_predictions(dataset: OrganizerDataset) -> dict[str, dict[str, Any]]:
    """Create a perfect semantic oracle for evaluator tests, not a production baseline."""
    output: dict[str, dict[str, Any]] = {}
    for sample in dataset.samples:
        output[sample.sample_id] = {
            "memory_worthy": sample.gold.memory_worthy,
            "memory_type": sample.gold.memory_type,
            "title": f"整理 {sample.sample_id}"[:48],
            "topics": list(sample.gold.topics),
            "entities": [
                {"name": name, "confidence": 1.0}
                for name in sample.gold.entities
            ],
            "event_date": sample.gold.event_date,
            "importance": sample.gold.importance,
            "confidence": 1.0,
            "link_candidates": list(sample.gold.link_candidates),
        }
    return output


def _score_samples(
    samples: tuple[OrganizerSample, ...],
    parsed: Mapping[str, OrganizerPrediction | None],
) -> _Accumulator:
    acc = _Accumulator()
    for sample in samples:
        acc.sample_count += 1
        prediction = parsed[sample.sample_id]
        gold = sample.gold
        if prediction is None:
            # Invalid JSON/schema is an explicit full-record failure, including calibration.
            acc.confidence_brier_sum += 1.0
            if gold.memory_worthy:
                acc.mw_fn += 1
                acc.type_total += 1
                acc.importance_total += 1
                acc.importance_abs_error += 4.0
            else:
                acc.date_absent_total += int(gold.event_date is None)
            _add_set_counts(set(), set(map(normalize_label, gold.topics)), acc, "topic")
            _add_set_counts(set(), set(map(normalize_label, gold.entities)), acc, "entity")
            _add_set_counts(set(), set(gold.link_candidates), acc, "link")
            if gold.event_date is not None:
                acc.date_present_total += 1
            elif gold.memory_worthy:
                acc.date_absent_total += 1
            continue

        acc.valid_count += 1
        mw_correct = prediction.memory_worthy == gold.memory_worthy
        acc.memory_worthy_correct += int(mw_correct)
        if prediction.memory_worthy and gold.memory_worthy:
            acc.mw_tp += 1
        elif prediction.memory_worthy and not gold.memory_worthy:
            acc.mw_fp += 1
        elif not prediction.memory_worthy and gold.memory_worthy:
            acc.mw_fn += 1

        type_correct = True
        if gold.memory_worthy:
            acc.type_total += 1
            type_correct = prediction.memory_worthy and prediction.memory_type == gold.memory_type
            acc.type_correct += int(type_correct)
            acc.importance_total += 1
            error = abs(prediction.importance - gold.importance)
            acc.importance_abs_error += error
            acc.importance_within_one += int(error <= 1)

        predicted_topics = set(map(normalize_label, prediction.topics))
        gold_topics = set(map(normalize_label, gold.topics))
        _add_set_counts(predicted_topics, gold_topics, acc, "topic")

        predicted_entities = set(map(normalize_label, prediction.entity_names))
        gold_entities = set(map(normalize_label, gold.entities))
        _add_set_counts(predicted_entities, gold_entities, acc, "entity")
        acc.predicted_entity_count += len(predicted_entities)
        acc.hallucinated_entity_count += len(predicted_entities - gold_entities)

        if gold.event_date is None:
            acc.date_absent_total += 1
            acc.date_absent_correct += int(prediction.event_date is None)
        else:
            acc.date_present_total += 1
            acc.date_present_correct += int(prediction.event_date == gold.event_date)

        predicted_links = set(prediction.link_candidates)
        gold_links = set(gold.link_candidates)
        _add_set_counts(predicted_links, gold_links, acc, "link")

        core_correct = mw_correct and (not gold.memory_worthy or type_correct)
        acc.confidence_brier_sum += (prediction.confidence - float(core_correct)) ** 2

        strict = (
            mw_correct
            and (not gold.memory_worthy or type_correct)
            and predicted_topics == gold_topics
            and predicted_entities == gold_entities
            and prediction.event_date == gold.event_date
            and (not gold.memory_worthy or prediction.importance == gold.importance)
            and predicted_links == gold_links
        )
        acc.strict_count += int(strict)
    return acc


def _metrics(acc: _Accumulator) -> dict[str, Any]:
    n = acc.sample_count
    return {
        "sample_count": n,
        "schema_valid_rate": _safe_div(acc.valid_count, n),
        "strict_record_accuracy": _safe_div(acc.strict_count, n),
        "memory_worthy_accuracy": _safe_div(acc.memory_worthy_correct, n),
        "memory_worthy_f1": _f1(acc.mw_tp, acc.mw_fp, acc.mw_fn),
        "memory_type_accuracy": _safe_div(acc.type_correct, acc.type_total),
        "topics_precision": _precision(acc.topic_tp, acc.topic_fp),
        "topics_recall": _recall(acc.topic_tp, acc.topic_fn),
        "topics_f1": _f1(acc.topic_tp, acc.topic_fp, acc.topic_fn),
        "entities_precision": _precision(acc.entity_tp, acc.entity_fp),
        "entities_recall": _recall(acc.entity_tp, acc.entity_fn),
        "entities_f1": _f1(acc.entity_tp, acc.entity_fp, acc.entity_fn),
        "entity_hallucination_rate": _safe_div(acc.hallucinated_entity_count, acc.predicted_entity_count),
        "event_date_exact_rate": _safe_div(acc.date_present_correct, acc.date_present_total),
        "event_date_null_accuracy": _safe_div(acc.date_absent_correct, acc.date_absent_total),
        "importance_mae": _safe_div(acc.importance_abs_error, acc.importance_total),
        "importance_within_one_rate": _safe_div(acc.importance_within_one, acc.importance_total),
        "links_precision": _precision(acc.link_tp, acc.link_fp),
        "links_recall": _recall(acc.link_tp, acc.link_fn),
        "links_f1": _f1(acc.link_tp, acc.link_fp, acc.link_fn),
        "confidence_brier": _safe_div(acc.confidence_brier_sum, n),
    }


def _add_set_counts(predicted: set[str], gold: set[str], acc: _Accumulator, kind: str) -> None:
    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)
    if kind == "topic":
        acc.topic_tp += tp
        acc.topic_fp += fp
        acc.topic_fn += fn
    elif kind == "entity":
        acc.entity_tp += tp
        acc.entity_fp += fp
        acc.entity_fn += fn
    elif kind == "link":
        acc.link_tp += tp
        acc.link_fp += fp
        acc.link_fn += fn
    else:  # pragma: no cover - internal programming error
        raise AssertionError(kind)


def _precision(tp: int, fp: int) -> float:
    return 1.0 if tp == 0 and fp == 0 else _safe_div(tp, tp + fp)


def _recall(tp: int, fn: int) -> float:
    return 1.0 if tp == 0 and fn == 0 else _safe_div(tp, tp + fn)


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = _precision(tp, fp)
    recall = _recall(tp, fn)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _safe_div(numerator: float, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _parse_probability(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrganizerEvaluationError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise OrganizerEvaluationError(f"{field_name} must be finite and in [0, 1]")
    return number


def _parse_string_list(value: Any, field_name: str, *, max_items: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > max_items:
        raise OrganizerEvaluationError(f"{field_name} must be an array with at most {max_items} items")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 80:
            raise OrganizerEvaluationError(f"{field_name} contains an invalid string")
        item = item.strip()
        normalized = normalize_label(item)
        if normalized in seen:
            raise OrganizerEvaluationError(f"{field_name} contains a duplicate")
        seen.add(normalized)
        result.append(item)
    return tuple(result)


def _validate_unique_strings(values: tuple[str, ...], field_name: str) -> None:
    normalized = [normalize_label(item) for item in values]
    if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
        raise OrganizerEvaluationError(f"{field_name} must contain unique non-empty strings")


def _validate_iso_date(value: str, field_name: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise OrganizerEvaluationError(f"{field_name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise OrganizerEvaluationError(f"{field_name} must use canonical YYYY-MM-DD")
