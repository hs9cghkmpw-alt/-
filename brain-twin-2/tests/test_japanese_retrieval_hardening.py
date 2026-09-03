from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from brain_twin_eval.dataset import (
    DatasetValidationError,
    dataset_from_mapping,
    dataset_sha256,
    is_formal_blind_run,
    load_dataset,
)
from brain_twin_eval.manifest import ManifestValidationError, build_manifest
from brain_twin_eval.report import report_markdown, report_payload
from brain_twin_eval.resources import PeakRssReading, peak_rss_reading
from brain_twin_eval.runner import RankedResult, evaluate_ann_recall, evaluate_rankings, evaluate_retriever

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "japanese_retrieval_v1.json"


def _dataset():
    return load_dataset(FIXTURE)


def _perfect_rankings(dataset):
    rankings = {}
    for query in dataset.queries:
        positives = [
            memory_id
            for memory_id, grade in sorted(
                query.relevance.items(), key=lambda item: (-item[1], item[0])
            )
            if grade > 0
        ]
        negatives = [
            memory.memory_id
            for memory in dataset.memories
            if memory.memory_id not in positives and memory.active
        ]
        rankings[query.query_id] = (positives + negatives)[:10]
    return rankings


def _manifest(dataset):
    return build_manifest(
        dataset=dataset,
        experiment_id="hardening-test",
        git_commit="b" * 40,
        provider_label="fixture",
        model_name="fixture-model",
        model_revision="rev-1",
        instruction_id="none",
        instruction_text="",
        dimension=4,
        normalized=True,
        document_template_version="1",
        backend_label="precomputed",
        backend_params={"k": 10},
        random_seed=7,
        timestamp_utc="2026-08-28T00:00:00+00:00",
    )


def test_committed_seed_defaults_to_open_judgements_not_acceptance_blind():
    dataset = _dataset()
    assert dataset.judgement_visibility == "open"
    assert dataset.acceptance_blind_ready is False
    assert _manifest(dataset).dataset_judgement_visibility == "open"


def test_invalid_judgement_visibility_is_rejected():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["judgement_visibility"] = "public-ish"
    with pytest.raises(DatasetValidationError, match="judgement_visibility"):
        dataset_from_mapping(raw)


def test_non_string_judgement_visibility_is_rejected_cleanly():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["judgement_visibility"] = ["open"]
    with pytest.raises(DatasetValidationError, match="judgement_visibility"):
        dataset_from_mapping(raw)


def test_judgement_visibility_changes_canonical_dataset_identity():
    dataset = _dataset()
    held_out = replace(dataset, judgement_visibility="held_out")
    assert dataset_sha256(dataset) != dataset_sha256(held_out)


def test_dataset_formal_blind_readiness_requires_held_out_blind_only_queries():
    held_out_mixed = replace(_dataset(), judgement_visibility="held_out")
    held_out_blind = replace(
        held_out_mixed, queries=held_out_mixed.queries_for_split("blind")
    )
    assert held_out_mixed.acceptance_blind_ready is False
    assert held_out_blind.acceptance_blind_ready is True
    assert is_formal_blind_run("held_out", "blind") is True
    assert is_formal_blind_run("held_out", "dev") is False
    assert is_formal_blind_run("held_out", None) is False


@pytest.mark.parametrize("split", ["dev", None])
def test_held_out_non_blind_report_is_not_acceptance_ready_or_redacted(split):
    dataset = replace(_dataset(), judgement_visibility="held_out")
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split=split)
    payload = report_payload(run, _manifest(dataset))
    assert payload["acceptance_blind_ready"] is False
    assert payload["query_details_redacted"] is False
    assert payload["per_slice_redacted"] is False


def test_held_out_blind_report_redacts_query_rankings_failure_and_slice_details():
    dataset = replace(_dataset(), judgement_visibility="held_out")
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="blind")
    payload = report_payload(run, _manifest(dataset))
    assert payload["acceptance_blind_ready"] is True
    assert payload["query_details_redacted"] is True
    assert payload["per_slice_redacted"] is True
    assert payload["queries"] == []
    assert payload["per_slice"] == {}
    assert payload["failed_must_hit_queries"] == []
    assert payload["false_positive_cases"] == []


class _StableRetriever:
    def search(self, query: str, k: int):
        return [RankedResult("mem-001", 1.0)]


class _DriftingRetriever:
    def __init__(self):
        self.calls = 0

    def search(self, query: str, k: int):
        self.calls += 1
        memory_id = "mem-001" if self.calls % 2 else "mem-002"
        return [RankedResult(memory_id, 1.0)]


def test_live_runner_records_first_call_warm_samples_and_process_peak_rss():
    dataset = _dataset()
    readings = iter(
        [
            PeakRssReading(100, "test-rss"),
            PeakRssReading(250, "test-rss"),
        ]
    )
    run = evaluate_retriever(
        dataset,
        _StableRetriever(),
        split="dev",
        k=10,
        warm_repeats=2,
        rss_reader=lambda: next(readings),
    )
    assert run.peak_rss_before_bytes == 100
    assert run.peak_rss_after_bytes == 250
    assert run.peak_rss_method == "test-rss"
    assert all(item.latency_seconds is not None for item in run.queries)
    assert all(len(item.warm_latency_seconds) == 2 for item in run.queries)
    assert all(item.warm_rank_drift_count == 0 for item in run.queries)
    assert run.reproducible is True
    assert run.selection_eligible is True


def test_ranking_drift_preserves_diagnostics_but_blocks_selection():
    base = _dataset()
    dataset = replace(base, queries=(base.queries[0],))
    clock_values = iter([0.0, 0.1, 1.0, 1.1])
    rss_values = iter([PeakRssReading(100, "test"), PeakRssReading(200, "test")])
    run = evaluate_retriever(
        dataset,
        _DriftingRetriever(),
        k=10,
        warm_repeats=1,
        clock=lambda: next(clock_values),
        rss_reader=lambda: next(rss_values),
    )
    assert run.queries[0].warm_rank_drift_count == 1
    assert run.reproducible is False
    assert run.selection_eligible is False
    payload = report_payload(run, _manifest(dataset))
    assert payload["reproducible"] is False
    assert payload["selection_eligible"] is False
    assert payload["latency"]["warm_rank_drift_count"] == 1
    assert "diagnostic only" in report_markdown(run, _manifest(dataset))


def test_report_uses_true_median_and_nearest_rank_p95_for_warm_samples():
    base = _dataset()
    dataset = replace(base, queries=(base.queries[0],))
    clock_values = iter([0.0, 0.4, 1.0, 1.1, 2.0, 2.2, 3.0, 3.3, 4.0, 4.5])
    rss_values = iter([PeakRssReading(None, "test"), PeakRssReading(None, "test")])
    run = evaluate_retriever(
        dataset,
        _StableRetriever(),
        k=10,
        warm_repeats=4,
        clock=lambda: next(clock_values),
        rss_reader=lambda: next(rss_values),
    )
    payload = report_payload(run, _manifest(dataset))
    assert payload["latency"]["run_first_query_seconds"] == pytest.approx(0.4)
    assert payload["latency"]["first_call_per_query"]["median_seconds"] == pytest.approx(0.4)
    assert payload["latency"]["warm"]["median_seconds"] == pytest.approx(0.25)
    assert payload["latency"]["warm"]["p95_seconds"] == pytest.approx(0.5)


def test_ann_oracle_summary_compares_same_queries_against_exactscan_rankings():
    dataset = _dataset()
    exact_rankings = _perfect_rankings(dataset)
    ann_rankings = {query_id: list(ids) for query_id, ids in exact_rankings.items()}
    ann_rankings["q-001"] = list(reversed(ann_rankings["q-001"][:10]))
    exact = evaluate_rankings(dataset, exact_rankings, split="dev")
    ann = evaluate_rankings(dataset, ann_rankings, split="dev")
    summary = evaluate_ann_recall(exact, ann, k=5)
    assert summary.query_count == 15
    assert 0.0 <= summary.mean_recall <= 1.0
    assert set(summary.per_query) == {query.query_id for query in dataset.queries_for_split("dev")}


def test_ann_oracle_rejects_same_version_but_different_dataset_hash():
    dataset = _dataset()
    changed = replace(dataset, judgement_visibility="held_out")
    exact = evaluate_rankings(dataset, _perfect_rankings(dataset), split="dev")
    ann = evaluate_rankings(changed, _perfect_rankings(changed), split="dev")
    with pytest.raises(ValueError, match="identical dataset hash"):
        evaluate_ann_recall(exact, ann, k=10)


def test_manifest_rejects_additional_common_token_prefixes():
    dataset = _dataset()
    with pytest.raises(ManifestValidationError, match="secret-like"):
        build_manifest(
            dataset=dataset,
            experiment_id="secret-test",
            git_commit="b" * 40,
            provider_label="fixture",
            model_name="fixture-model",
            model_revision="rev-1",
            instruction_id="none",
            instruction_text="",
            dimension=4,
            normalized=True,
            document_template_version="1",
            backend_label="precomputed",
            backend_params={"value": "hf_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"},
            random_seed=7,
            timestamp_utc="2026-08-28T00:00:00+00:00",
        )


def test_report_rejects_manifest_from_different_dataset():
    dataset = _dataset()
    changed = replace(dataset, judgement_visibility="held_out")
    run = evaluate_rankings(dataset, _perfect_rankings(dataset), split="dev")
    with pytest.raises(ValueError, match="hashes do not match"):
        report_payload(run, _manifest(changed))


def test_peak_rss_reader_is_best_effort_and_non_throwing():
    reading = peak_rss_reading()
    assert isinstance(reading, PeakRssReading)
    assert reading.bytes is None or reading.bytes > 0
    assert reading.method
