from __future__ import annotations

import json

import pytest

from brain_twin_eval.organizer import (
    OrganizerDataset,
    OrganizerEvaluationError,
    OrganizerGold,
    OrganizerSample,
    evaluate_organizer,
    oracle_predictions,
    parse_prediction,
)
from brain_twin_eval.organizer_gold import build_organizer_open_v1


def test_open_organizer_gold_is_deterministic_and_broad() -> None:
    first = build_organizer_open_v1()
    second = build_organizer_open_v1()

    assert len(first.samples) == 128
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.judgement_visibility == "open"

    types = {sample.gold.memory_type for sample in first.samples if sample.gold.memory_worthy}
    assert {"fact", "experience", "thought", "decision", "preference", "goal", "knowledge", "person", "project"} <= types

    slices = {name for sample in first.samples for name in sample.slices}
    assert {
        "non_memory",
        "multi_topic",
        "multi_entity",
        "date_present",
        "date_absent",
        "high_importance",
        "link_candidate",
        "mixed_jp_en",
    } <= slices


def test_open_organizer_gold_is_synthetic_and_does_not_contain_user_vault_paths() -> None:
    dataset = build_organizer_open_v1()
    joined = "\n".join(sample.raw_text for sample in dataset.samples)
    lowered = joined.casefold()
    assert "c:\\users\\" not in lowered
    assert "/users/" not in lowered
    assert "obsidian" not in lowered


def test_public_payload_excludes_gold_and_slice_labels() -> None:
    dataset = build_organizer_open_v1()
    payload = dataset.public_payload()
    assert payload["dataset_sha256"] == dataset.canonical_sha256
    first = payload["samples"][0]
    assert "gold" not in first
    assert "slices" not in first
    assert "raw_text" in first


def test_prediction_contract_rejects_destructive_or_extra_fields() -> None:
    dataset = build_organizer_open_v1()
    sample = dataset.samples[0]
    payload = oracle_predictions(dataset)[sample.sample_id]
    payload["rewritten_text"] = "原文を置換"

    with pytest.raises(OrganizerEvaluationError, match="keys mismatch"):
        parse_prediction(payload, allowed_link_ids=set())


def test_prediction_contract_rejects_ai_inference_for_raw_capture() -> None:
    dataset = build_organizer_open_v1()
    sample = dataset.samples[0]
    payload = oracle_predictions(dataset)[sample.sample_id]
    payload["memory_type"] = "ai_inference"

    with pytest.raises(OrganizerEvaluationError, match="memory_type"):
        parse_prediction(payload, allowed_link_ids=set())


def test_prediction_contract_rejects_unknown_link_target() -> None:
    dataset = build_organizer_open_v1()
    sample = next(sample for sample in dataset.samples if "link_candidate" in sample.slices)
    payload = oracle_predictions(dataset)[sample.sample_id]
    payload["link_candidates"] = ["not-supplied"]

    with pytest.raises(OrganizerEvaluationError, match="not supplied"):
        parse_prediction(
            payload,
            allowed_link_ids={item.memory_id for item in sample.context_memories},
        )


def test_perfect_oracle_scores_one_except_zero_error_metrics() -> None:
    dataset = build_organizer_open_v1()
    result = evaluate_organizer(dataset, oracle_predictions(dataset))
    overall = result.overall

    assert overall["schema_valid_rate"] == 1.0
    assert overall["strict_record_accuracy"] == 1.0
    assert overall["memory_worthy_accuracy"] == 1.0
    assert overall["memory_worthy_f1"] == 1.0
    assert overall["memory_type_accuracy"] == 1.0
    assert overall["topics_f1"] == 1.0
    assert overall["entities_f1"] == 1.0
    assert overall["entity_hallucination_rate"] == 0.0
    assert overall["event_date_exact_rate"] == 1.0
    assert overall["event_date_null_accuracy"] == 1.0
    assert overall["importance_mae"] == 0.0
    assert overall["importance_within_one_rate"] == 1.0
    assert overall["links_f1"] == 1.0
    assert overall["confidence_brier"] == 0.0


def test_malformed_json_is_counted_as_invalid_without_aborting_run() -> None:
    dataset = build_organizer_open_v1()
    predictions = oracle_predictions(dataset)
    predictions[dataset.samples[0].sample_id] = "{not json"

    result = evaluate_organizer(dataset, predictions)
    assert len(result.invalid_sample_ids) == 1
    assert result.overall["schema_valid_rate"] == pytest.approx(127 / 128)
    assert result.overall["strict_record_accuracy"] == pytest.approx(127 / 128)


def test_entity_false_positive_is_reported_as_hallucination() -> None:
    dataset = build_organizer_open_v1()
    predictions = oracle_predictions(dataset)
    sample = next(sample for sample in dataset.samples if sample.gold.entities)
    payload = predictions[sample.sample_id]
    payload["entities"] = list(payload["entities"]) + [{"name": "存在しない会社XYZ", "confidence": 0.99}]

    result = evaluate_organizer(dataset, predictions)
    assert result.overall["entities_precision"] < 1.0
    assert result.overall["entity_hallucination_rate"] > 0.0
    assert result.overall["strict_record_accuracy"] < 1.0


def test_wrong_date_and_importance_are_separate_failures() -> None:
    dataset = build_organizer_open_v1()
    predictions = oracle_predictions(dataset)
    sample = next(sample for sample in dataset.samples if sample.gold.event_date is not None and sample.gold.memory_worthy)
    payload = predictions[sample.sample_id]
    payload["event_date"] = "2026-01-01"
    payload["importance"] = 1

    result = evaluate_organizer(dataset, predictions)
    assert result.overall["event_date_exact_rate"] < 1.0
    assert result.overall["importance_mae"] > 0.0


def test_low_confidence_on_correct_core_prediction_worsens_brier() -> None:
    dataset = build_organizer_open_v1()
    predictions = oracle_predictions(dataset)
    sample = dataset.samples[0]
    predictions[sample.sample_id]["confidence"] = 0.1

    result = evaluate_organizer(dataset, predictions)
    assert result.overall["confidence_brier"] > 0.0


def test_held_out_report_redacts_slice_and_failure_details() -> None:
    open_dataset = build_organizer_open_v1()
    held_out = OrganizerDataset(
        version="organizer-held-out-test",
        judgement_visibility="held_out",
        samples=open_dataset.samples[:2],
    )
    predictions = oracle_predictions(held_out)
    predictions[held_out.samples[0].sample_id] = "bad-json"

    report = evaluate_organizer(held_out, predictions).to_dict(redact_held_out=True)
    assert "per_slice" not in report
    assert "invalid_sample_ids" not in report
    assert report["per_slice_redacted"] is True
    assert report["invalid_sample_count"] == 1


def test_dataset_rejects_gold_link_not_supplied_in_context() -> None:
    with pytest.raises(OrganizerEvaluationError, match="not in context"):
        OrganizerSample(
            sample_id="broken",
            raw_text="関連するメモがある",
            created_at="2026-08-15T10:00:00+09:00",
            gold=OrganizerGold(
                memory_worthy=True,
                memory_type="thought",
                link_candidates=("missing",),
            ),
            slices=("link",),
            context_memories=(),
        )


def test_unknown_prediction_id_rejects_mixed_dataset_run() -> None:
    dataset = build_organizer_open_v1()
    predictions = oracle_predictions(dataset)
    predictions["foreign-sample"] = json.dumps({})

    with pytest.raises(OrganizerEvaluationError, match="unknown sample ids"):
        evaluate_organizer(dataset, predictions)
