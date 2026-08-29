from __future__ import annotations

from brain_twin_eval.blind import create_blind_packages
from brain_twin_eval.blind_ranking import (
    BlindRankingError,
    build_blind_manifest,
    run_blind_rankings,
    runner_input_from_mapping,
    score_blind_evidence,
)
from brain_twin_eval.dataset import REQUIRED_SLICE_TAGS, EvaluationDataset, EvaluationMemory, EvaluationQuery
from brain_twin_eval.report import report_payload
from brain_twin_eval.resources import PeakRssReading
from brain_twin_eval.runner import RankedResult


class _FakeRetriever:
    def search(self, query: str, k: int):
        return (RankedResult("mem-1", 1.0),)


def _dataset():
    return EvaluationDataset(
        version="heldout-v1",
        judgement_visibility="held_out",
        memories=(EvaluationMemory("mem-1", "架空記憶", "合成された正解記憶", ("ja",), "short", True),),
        queries=(EvaluationQuery(
            query_id="q-1",
            text="架空の記憶は？",
            slice_tags=tuple(sorted(REQUIRED_SLICE_TAGS)),
            relevance={"mem-1": 3},
            must_hit_ids=("mem-1",),
            lexical_sufficient=False,
            adjudication_note="private synthetic judgement",
            split="blind",
        ),),
    )


def _runner_and_private():
    packages = create_blind_packages(_dataset())
    return packages.runner, packages.private_judgements


def _manifest(runner):
    parsed = runner_input_from_mapping(runner)
    return build_blind_manifest(
        runner=parsed,
        experiment_id="candidate",
        git_commit="a" * 40,
        provider_label="local-eval",
        model_name="org/model",
        model_revision="b" * 40,
        instruction_id="instruction-v1",
        instruction_text="query: {query}",
        dimension=8,
        normalized=True,
        document_template_version="1",
        backend_label="evaluation_exact_dense",
        backend_params={"candidate_k": 10},
        timestamp_utc="2026-08-29T00:00:00+00:00",
    )


def test_blind_model_side_evidence_contains_no_query_text_or_judgements() -> None:
    runner_raw, _private = _runner_and_private()
    runner = runner_input_from_mapping(runner_raw)
    clocks = iter((0.0, 0.1, 0.1, 0.2))
    rss = iter((PeakRssReading(100, "test"), PeakRssReading(200, "test")))
    evidence = run_blind_rankings(
        runner,
        _FakeRetriever(),
        _manifest(runner_raw),
        warm_repeats=1,
        clock=lambda: next(clocks),
        rss_reader=lambda: next(rss),
    )
    serialized = str(evidence)
    assert "架空の記憶は？" not in serialized
    assert "relevance" not in serialized
    assert "must_hit" not in serialized
    assert evidence["queries"][0]["ranked_ids"] == ["mem-1"]


def test_private_scoring_reconstructs_metrics_and_final_report_is_redacted() -> None:
    runner_raw, private = _runner_and_private()
    runner = runner_input_from_mapping(runner_raw)
    clocks = iter((0.0, 0.1))
    rss = iter((PeakRssReading(100, "test"), PeakRssReading(200, "test")))
    evidence = run_blind_rankings(
        runner,
        _FakeRetriever(),
        _manifest(runner_raw),
        warm_repeats=0,
        clock=lambda: next(clocks),
        rss_reader=lambda: next(rss),
    )
    run, manifest = score_blind_evidence(runner_raw, private, evidence)
    assert run.overall.mrr_at_10 == 1.0
    assert run.overall.ndcg_at_10 == 1.0
    payload = report_payload(run, manifest)
    assert payload["query_details_redacted"] is True
    assert payload["per_slice_redacted"] is True
    assert payload["queries"] == []
    assert payload["failed_must_hit_queries"] == []


def test_tampered_ranking_evidence_runner_commitment_is_rejected() -> None:
    runner_raw, private = _runner_and_private()
    runner = runner_input_from_mapping(runner_raw)
    clocks = iter((0.0, 0.1))
    rss = iter((PeakRssReading(100, "test"), PeakRssReading(200, "test")))
    evidence = run_blind_rankings(
        runner,
        _FakeRetriever(),
        _manifest(runner_raw),
        warm_repeats=0,
        clock=lambda: next(clocks),
        rss_reader=lambda: next(rss),
    )
    evidence["runner_sha256"] = "f" * 64
    try:
        score_blind_evidence(runner_raw, private, evidence)
    except BlindRankingError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("expected BlindRankingError")


def test_blind_runner_rejects_inactive_result() -> None:
    runner_raw, _ = _runner_and_private()
    runner_raw["memories"].append({
        "memory_id": "mem-inactive",
        "title": "非表示",
        "content": "非アクティブ",
        "language_tags": ["ja"],
        "length_bucket": "short",
        "active": False,
    })
    runner = runner_input_from_mapping(runner_raw)

    class Bad:
        def search(self, query, k):
            return (RankedResult("mem-inactive", 1.0),)

    clocks = iter((0.0, 0.1))
    rss = iter((PeakRssReading(100, "test"), PeakRssReading(200, "test")))
    try:
        run_blind_rankings(
            runner,
            Bad(),
            _manifest(runner_raw),
            warm_repeats=0,
            clock=lambda: next(clocks),
            rss_reader=lambda: next(rss),
        )
    except BlindRankingError as exc:
        assert "inactive" in str(exc)
    else:
        raise AssertionError("expected BlindRankingError")
