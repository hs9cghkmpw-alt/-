from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .blind import payload_sha256, reconstruct_held_out_dataset, validate_runner_payload
from .dataset import EvaluationMemory
from .manifest import ExperimentManifest, instruction_sha256, manifest_to_dict
from .resources import PeakRssReading, peak_rss_reading
from .runner import EvaluationRetriever, EvaluationRun, RankedResult, evaluate_rankings


class BlindRankingError(ValueError):
    pass


@dataclass(frozen=True)
class BlindQuery:
    query_id: str
    text: str


@dataclass(frozen=True)
class BlindRunnerInput:
    version: str
    source_dataset_sha256: str
    runner_sha256: str
    memories: tuple[EvaluationMemory, ...]
    queries: tuple[BlindQuery, ...]


@dataclass(frozen=True)
class BlindQueryEvidence:
    query_id: str
    ranked_ids: tuple[str, ...]
    first_call_seconds: float
    warm_latency_seconds: tuple[float, ...]
    warm_rank_drift_count: int


def _sha(value: Any, length: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise BlindRankingError(f"{field} must be a {length}-character hexadecimal SHA")
    return value.lower()


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BlindRankingError(f"{field} must be a non-empty string")
    return value


def runner_input_from_mapping(raw: Mapping[str, Any]) -> BlindRunnerInput:
    validate_runner_payload(raw)
    version = _nonempty(raw.get("version"), "version")
    source_sha = _sha(raw.get("source_dataset_sha256"), 64, "source_dataset_sha256")
    memories: list[EvaluationMemory] = []
    seen_memories: set[str] = set()
    for item in raw["memories"]:
        if not isinstance(item, Mapping):
            raise BlindRankingError("runner memory must be an object")
        memory_id = _nonempty(item.get("memory_id"), "memory_id")
        if memory_id in seen_memories:
            raise BlindRankingError(f"duplicate runner memory_id: {memory_id}")
        seen_memories.add(memory_id)
        language_tags = item.get("language_tags")
        if not isinstance(language_tags, list) or not language_tags or any(not isinstance(tag, str) or not tag.strip() for tag in language_tags):
            raise BlindRankingError(f"{memory_id}.language_tags must be a non-empty string list")
        if len(language_tags) != len(set(language_tags)):
            raise BlindRankingError(f"{memory_id}.language_tags must not contain duplicates")
        active = item.get("active", True)
        if not isinstance(active, bool):
            raise BlindRankingError(f"{memory_id}.active must be boolean")
        memories.append(EvaluationMemory(
            memory_id=memory_id,
            title=_nonempty(item.get("title"), f"{memory_id}.title"),
            content=_nonempty(item.get("content"), f"{memory_id}.content"),
            language_tags=tuple(language_tags),
            length_bucket=_nonempty(item.get("length_bucket"), f"{memory_id}.length_bucket"),
            active=active,
        ))
    queries = tuple(
        BlindQuery(query_id=_nonempty(item.get("query_id"), "query_id"), text=_nonempty(item.get("text"), "query.text"))
        for item in raw["queries"]
    )
    return BlindRunnerInput(version, source_sha, payload_sha256(raw), tuple(memories), queries)


def build_blind_manifest(
    *, runner: BlindRunnerInput, experiment_id: str, git_commit: str,
    provider_label: str, model_name: str, model_revision: str,
    instruction_id: str, instruction_text: str, dimension: int,
    normalized: bool, document_template_version: str, backend_label: str,
    backend_params: Mapping[str, Any], random_seed: int = 0,
    timestamp_utc: str | None = None,
) -> ExperimentManifest:
    git_commit = _sha(git_commit, 40, "git_commit")
    model_revision = _sha(model_revision, 40, "model_revision")
    if not isinstance(instruction_text, str):
        raise BlindRankingError("instruction_text must be a string")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise BlindRankingError("dimension must be a positive integer")
    if not isinstance(normalized, bool):
        raise BlindRankingError("normalized must be boolean")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise BlindRankingError("random_seed must be an integer")
    if not isinstance(backend_params, Mapping):
        raise BlindRankingError("backend_params must be an object")
    manifest = ExperimentManifest(
        experiment_id=_nonempty(experiment_id, "experiment_id"),
        timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(),
        dataset_version=runner.version,
        dataset_sha256=runner.source_dataset_sha256,
        dataset_judgement_visibility="held_out",
        git_commit=git_commit,
        provider_label=_nonempty(provider_label, "provider_label"),
        model_name=_nonempty(model_name, "model_name"),
        model_revision=model_revision,
        instruction_id=_nonempty(instruction_id, "instruction_id"),
        instruction_text_sha256=instruction_sha256(instruction_text),
        dimension=dimension,
        normalized=normalized,
        document_template_version=_nonempty(document_template_version, "document_template_version"),
        backend_label=_nonempty(backend_label, "backend_label"),
        backend_params=dict(backend_params),
        python_version=platform.python_version(), platform=platform.platform(), random_seed=random_seed,
    )
    manifest_to_dict(manifest)
    return manifest


def _validate_results(runner: BlindRunnerInput, results: Sequence[RankedResult], query_id: str) -> tuple[str, ...]:
    ids = tuple(result.memory_id for result in results)
    if len(ids) != len(set(ids)):
        raise BlindRankingError(f"duplicate ranked IDs for query {query_id}")
    known = {memory.memory_id for memory in runner.memories}
    active = {memory.memory_id for memory in runner.memories if memory.active}
    unknown = [memory_id for memory_id in ids if memory_id not in known]
    if unknown:
        raise BlindRankingError(f"query {query_id} returned unknown IDs: {', '.join(unknown)}")
    inactive = [memory_id for memory_id in ids if memory_id not in active]
    if inactive:
        raise BlindRankingError(f"query {query_id} returned inactive IDs: {', '.join(inactive)}")
    return ids


def _timed_search(retriever: EvaluationRetriever, text: str, k: int, clock: Callable[[], float]) -> tuple[tuple[RankedResult, ...], float]:
    started = clock()
    results = tuple(retriever.search(text, k))
    elapsed = clock() - started
    if elapsed < 0:
        raise BlindRankingError("clock produced negative elapsed time")
    return results, elapsed


def run_blind_rankings(
    runner: BlindRunnerInput, retriever: EvaluationRetriever, manifest: ExperimentManifest,
    *, k: int = 10, warm_repeats: int = 30,
    clock: Callable[[], float] = time.perf_counter,
    rss_reader: Callable[[], PeakRssReading] = peak_rss_reading,
) -> dict[str, Any]:
    if k < 10:
        raise BlindRankingError("k must be at least 10")
    if isinstance(warm_repeats, bool) or not isinstance(warm_repeats, int) or warm_repeats < 0:
        raise BlindRankingError("warm_repeats must be a non-negative integer")
    if manifest.dataset_sha256 != runner.source_dataset_sha256 or manifest.dataset_version != runner.version:
        raise BlindRankingError("manifest does not match blind runner dataset identity")
    if manifest.dataset_judgement_visibility != "held_out":
        raise BlindRankingError("formal blind manifest must use held_out visibility")

    rss_before = rss_reader()
    evidence: list[BlindQueryEvidence] = []
    for query in runner.queries:
        cold, cold_elapsed = _timed_search(retriever, query.text, k, clock)
        ranked_ids = _validate_results(runner, cold, query.query_id)
        warm_latencies: list[float] = []
        drift = 0
        for _ in range(warm_repeats):
            warm, elapsed = _timed_search(retriever, query.text, k, clock)
            warm_ids = _validate_results(runner, warm, query.query_id)
            warm_latencies.append(elapsed)
            if warm_ids != ranked_ids:
                drift += 1
        evidence.append(BlindQueryEvidence(query.query_id, ranked_ids, cold_elapsed, tuple(warm_latencies), drift))
    rss_after = rss_reader()
    return {
        "schema": 1,
        "runner_sha256": runner.runner_sha256,
        "source_dataset_sha256": runner.source_dataset_sha256,
        "dataset_version": runner.version,
        "judgement_visibility": "held_out",
        "split": "blind",
        "manifest": manifest_to_dict(manifest),
        "k": k,
        "warm_repeats": warm_repeats,
        "queries": [{
            "query_id": item.query_id,
            "ranked_ids": list(item.ranked_ids),
            "first_call_seconds": item.first_call_seconds,
            "warm_latency_seconds": list(item.warm_latency_seconds),
            "warm_rank_drift_count": item.warm_rank_drift_count,
        } for item in evidence],
        "resources": {
            "peak_rss_before_bytes": rss_before.bytes,
            "peak_rss_after_bytes": rss_after.bytes,
            "peak_rss_method": rss_after.method or rss_before.method,
        },
    }


def _manifest_from_mapping(raw: Mapping[str, Any]) -> ExperimentManifest:
    try:
        manifest = ExperimentManifest(**dict(raw))
    except TypeError as exc:
        raise BlindRankingError("malformed blind ranking manifest") from exc
    _sha(manifest.model_revision, 40, "manifest.model_revision")
    _sha(manifest.git_commit, 40, "manifest.git_commit")
    _sha(manifest.instruction_text_sha256, 64, "manifest.instruction_text_sha256")
    manifest_to_dict(manifest)
    return manifest


def score_blind_evidence(runner_raw: Mapping[str, Any], private_judgements: Mapping[str, Any], evidence_raw: Mapping[str, Any]) -> tuple[EvaluationRun, ExperimentManifest]:
    runner = runner_input_from_mapping(runner_raw)
    dataset = reconstruct_held_out_dataset(runner_raw, private_judgements)
    if not isinstance(evidence_raw, Mapping) or evidence_raw.get("schema") != 1:
        raise BlindRankingError("unsupported blind ranking evidence schema")
    if evidence_raw.get("runner_sha256") != runner.runner_sha256:
        raise BlindRankingError("ranking evidence does not match this blind runner package")
    if evidence_raw.get("source_dataset_sha256") != runner.source_dataset_sha256:
        raise BlindRankingError("ranking evidence source commitment mismatch")
    if evidence_raw.get("dataset_version") != runner.version or evidence_raw.get("split") != "blind" or evidence_raw.get("judgement_visibility") != "held_out":
        raise BlindRankingError("ranking evidence dataset/split/visibility mismatch")
    manifest_raw = evidence_raw.get("manifest")
    if not isinstance(manifest_raw, Mapping):
        raise BlindRankingError("ranking evidence manifest must be an object")
    manifest = _manifest_from_mapping(manifest_raw)
    if manifest.dataset_sha256 != runner.source_dataset_sha256 or manifest.dataset_version != runner.version or manifest.dataset_judgement_visibility != "held_out":
        raise BlindRankingError("ranking evidence manifest is not bound to the held-out dataset")

    items = evidence_raw.get("queries")
    if not isinstance(items, list):
        raise BlindRankingError("ranking evidence queries must be a list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise BlindRankingError("ranking evidence query must be an object")
        query_id = _nonempty(item.get("query_id"), "ranking query_id")
        if query_id in by_id:
            raise BlindRankingError(f"duplicate ranking evidence query_id: {query_id}")
        by_id[query_id] = item
    expected = {query.query_id for query in dataset.queries}
    if set(by_id) != expected:
        raise BlindRankingError("ranking evidence must contain exactly the held-out query IDs")

    rankings: dict[str, tuple[str, ...]] = {}
    for query_id, item in by_id.items():
        ranked = item.get("ranked_ids")
        if not isinstance(ranked, list) or any(not isinstance(value, str) or not value for value in ranked):
            raise BlindRankingError(f"{query_id} ranked_ids must be a string list")
        rankings[query_id] = tuple(ranked)
    base_run = evaluate_rankings(dataset, rankings, split="blind")
    base_by_id = {item.query_id: item for item in base_run.queries}
    timed_queries = []
    for query_id in sorted(expected):
        raw = by_id[query_id]
        cold, warm, drift = raw.get("first_call_seconds"), raw.get("warm_latency_seconds"), raw.get("warm_rank_drift_count")
        if isinstance(cold, bool) or not isinstance(cold, (int, float)) or float(cold) < 0:
            raise BlindRankingError(f"{query_id} first_call_seconds must be non-negative")
        if not isinstance(warm, list) or any(isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0 for value in warm):
            raise BlindRankingError(f"{query_id} warm_latency_seconds must be non-negative numeric values")
        if isinstance(drift, bool) or not isinstance(drift, int) or drift < 0:
            raise BlindRankingError(f"{query_id} warm_rank_drift_count must be non-negative")
        timed_queries.append(replace(base_by_id[query_id], latency_seconds=float(cold), warm_latency_seconds=tuple(float(value) for value in warm), warm_rank_drift_count=drift))

    resources = evidence_raw.get("resources")
    if not isinstance(resources, Mapping):
        raise BlindRankingError("ranking evidence resources must be an object")
    before, after = resources.get("peak_rss_before_bytes"), resources.get("peak_rss_after_bytes")
    for name, value in (("peak_rss_before_bytes", before), ("peak_rss_after_bytes", after)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise BlindRankingError(f"{name} must be a positive integer or null")
    run = EvaluationRun(
        dataset_version=base_run.dataset_version, dataset_sha256=base_run.dataset_sha256,
        judgement_visibility=base_run.judgement_visibility, split="blind", queries=tuple(timed_queries),
        overall=base_run.overall, per_slice=base_run.per_slice,
        peak_rss_before_bytes=before, peak_rss_after_bytes=after,
        peak_rss_method=resources.get("peak_rss_method"),
    )
    return run, manifest


def evidence_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
