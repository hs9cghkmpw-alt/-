from __future__ import annotations

from datetime import datetime, timedelta

from brain_twin_eval.organizer import evaluate_organizer, oracle_predictions
from brain_twin_eval.organizer_gold_v2 import build_organizer_open_v2


def test_open_organizer_v2_is_deterministic_and_extends_v1() -> None:
    first = build_organizer_open_v2()
    second = build_organizer_open_v2()
    assert len(first.samples) == 192
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.version == "organizer-open-v2"


def test_open_organizer_v2_has_hard_reasoning_slices() -> None:
    dataset = build_organizer_open_v2()
    slices = {name for sample in dataset.samples for name in sample.slices}
    assert {
        "relative_date",
        "negation",
        "cancelled_intention",
        "uncertainty",
        "vague_date",
        "quoted_statement",
        "attribution",
        "multiple_dates",
        "deadline_selection",
        "type_ambiguity",
        "not_decided",
        "link_hard_negative",
    } <= slices


def test_relative_date_gold_is_resolved_from_created_at() -> None:
    dataset = build_organizer_open_v2()
    yesterday_samples = [sample for sample in dataset.samples if sample.sample_id.startswith("org-v2-relative-yesterday-")]
    tomorrow_samples = [sample for sample in dataset.samples if sample.sample_id.startswith("org-v2-relative-tomorrow-")]
    assert len(yesterday_samples) == 8
    assert len(tomorrow_samples) == 8
    for sample in yesterday_samples:
        created = datetime.fromisoformat(sample.created_at).date()
        assert sample.gold.event_date == (created - timedelta(days=1)).isoformat()
    for sample in tomorrow_samples:
        created = datetime.fromisoformat(sample.created_at).date()
        assert sample.gold.event_date == (created + timedelta(days=1)).isoformat()


def test_vague_dates_do_not_fabricate_exact_event_date() -> None:
    dataset = build_organizer_open_v2()
    vague = [sample for sample in dataset.samples if "vague_date" in sample.slices]
    assert len(vague) == 8
    assert all(sample.gold.event_date is None for sample in vague)


def test_multiple_date_goal_selects_deadline_not_discussion_date() -> None:
    dataset = build_organizer_open_v2()
    samples = [sample for sample in dataset.samples if "deadline_selection" in sample.slices]
    assert len(samples) == 8
    for index, sample in enumerate(samples, start=1):
        assert sample.gold.memory_type == "goal"
        assert sample.gold.event_date == f"2026-09-{index + 10:02d}"


def test_not_decided_cases_are_thoughts_not_decisions() -> None:
    dataset = build_organizer_open_v2()
    samples = [sample for sample in dataset.samples if "type_ambiguity" in sample.slices]
    assert len(samples) == 8
    assert all(sample.gold.memory_type == "thought" for sample in samples)


def test_cancelled_purchase_is_current_decision_not_goal() -> None:
    dataset = build_organizer_open_v2()
    samples = [sample for sample in dataset.samples if "cancelled_intention" in sample.slices]
    assert len(samples) == 8
    assert all(sample.gold.memory_type == "decision" for sample in samples)
    assert all(sample.gold.event_date is None for sample in samples)


def test_link_hard_negative_selects_backup_context_not_entity_overlap_storage_context() -> None:
    dataset = build_organizer_open_v2()
    samples = [sample for sample in dataset.samples if "link_hard_negative" in sample.slices]
    assert len(samples) == 8
    for index, sample in enumerate(samples, start=1):
        assert sample.gold.link_candidates == (f"ctx-v2-backup-{index:02d}",)
        assert f"ctx-v2-storage-{index:02d}" not in sample.gold.link_candidates


def test_v2_oracle_remains_perfect_under_same_evaluator() -> None:
    dataset = build_organizer_open_v2()
    result = evaluate_organizer(dataset, oracle_predictions(dataset))
    assert result.overall["schema_valid_rate"] == 1.0
    assert result.overall["strict_record_accuracy"] == 1.0
    assert result.overall["entity_hallucination_rate"] == 0.0
    assert result.overall["confidence_brier"] == 0.0
