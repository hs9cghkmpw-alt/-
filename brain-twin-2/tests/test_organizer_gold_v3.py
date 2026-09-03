from __future__ import annotations

from brain_twin_eval.organizer import evaluate_organizer, oracle_predictions
from brain_twin_eval.organizer_gold_v2 import build_organizer_open_v2
from brain_twin_eval.organizer_gold_v3 import STRESS_SLICES, build_organizer_open_v3


def test_open_organizer_v3_extends_v2_without_rewriting_existing_gold() -> None:
    v2 = build_organizer_open_v2()
    v3 = build_organizer_open_v3()
    assert v2.version == "organizer-open-v2"
    assert v3.version == "organizer-open-v3-stress"
    assert len(v2.samples) == 192
    assert len(v3.samples) == 240
    assert v3.samples[: len(v2.samples)] == v2.samples
    assert v3.canonical_sha256 == build_organizer_open_v3().canonical_sha256


def test_every_declared_stress_slice_has_multiple_cases() -> None:
    dataset = build_organizer_open_v3()
    counts = {
        slice_name: sum(slice_name in sample.slices for sample in dataset.samples)
        for slice_name in STRESS_SLICES
    }
    assert set(counts) == set(STRESS_SLICES)
    assert all(count >= 4 for count in counts.values())


def test_prompt_injection_payload_is_gold_as_data_not_as_instruction() -> None:
    samples = [sample for sample in build_organizer_open_v3().samples if "prompt_injection_as_data" in sample.slices]
    assert len(samples) == 4
    for sample in samples:
        assert "Ignore previous instructions" in sample.raw_text
        assert "RootAdmin" in sample.raw_text
        assert "2099-01-01" in sample.raw_text
        assert sample.gold.memory_type == "knowledge"
        assert sample.gold.entities == ()
        assert sample.gold.event_date is None
        assert sample.gold.importance != 5


def test_embedded_json_and_code_do_not_become_real_metadata_gold() -> None:
    samples = [sample for sample in build_organizer_open_v3().samples if "embedded_json_or_code" in sample.slices]
    assert len(samples) == 4
    for sample in samples:
        assert '"memory_type":"goal"' in sample.raw_text
        assert "2099-01-01" in sample.raw_text
        assert sample.gold.memory_type == "knowledge"
        assert sample.gold.event_date is None
        assert sample.gold.entities == ()


def test_long_capture_and_many_entity_stress_are_substantive() -> None:
    dataset = build_organizer_open_v3()
    long_samples = [sample for sample in dataset.samples if "long_capture" in sample.slices]
    many_entities = [sample for sample in dataset.samples if "many_entities" in sample.slices]
    assert len(long_samples) == 4
    assert all(len(sample.raw_text) > 1000 for sample in long_samples)
    assert len(many_entities) == 4
    assert all(len(sample.gold.entities) == 6 for sample in many_entities)


def test_no_memory_chatter_stress_remains_non_memory() -> None:
    samples = [sample for sample in build_organizer_open_v3().samples if "no_memory_chatter" in sample.slices]
    assert len(samples) == 4
    assert all(sample.gold.memory_worthy is False for sample in samples)
    assert all(sample.gold.topics == () and sample.gold.entities == () for sample in samples)


def test_cancelled_then_replanned_selects_new_date_not_cancelled_date() -> None:
    samples = [sample for sample in build_organizer_open_v3().samples if "cancelled_then_replanned" in sample.slices]
    assert len(samples) == 4
    for sample in samples:
        assert sample.gold.memory_type == "decision"
        assert sample.gold.event_date is not None
        assert sample.gold.event_date.startswith("2026-10-")
        assert "2026-09-" in sample.raw_text


def test_v3_oracle_remains_perfect_under_same_evaluator() -> None:
    dataset = build_organizer_open_v3()
    report = evaluate_organizer(dataset, oracle_predictions(dataset)).overall
    assert report["schema_valid_rate"] == 1.0
    assert report["strict_record_accuracy"] == 1.0
    assert report["memory_worthy_f1"] == 1.0
    assert report["memory_type_accuracy"] == 1.0
    assert report["topics_f1"] == 1.0
    assert report["entities_f1"] == 1.0
    assert report["entity_hallucination_rate"] == 0.0
    assert report["event_date_exact_rate"] == 1.0
    assert report["event_date_null_accuracy"] == 1.0
    assert report["importance_mae"] == 0.0
    assert report["links_f1"] == 1.0


def test_v3_contains_no_user_vault_paths() -> None:
    dataset = build_organizer_open_v3()
    corpus = "\n".join(sample.raw_text for sample in dataset.samples).lower()
    assert "c:\\users\\north-act135" not in corpus
    assert "/users/" not in corpus
    assert "vault/" not in corpus
