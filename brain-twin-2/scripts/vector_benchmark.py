"""Sprint 4D: reproducible ExactScanBackend reference/fallback benchmark.

IMPORTANT -- this measures `ExactScanBackend` plus a synthetic, offline, deterministic
embedding provider. Neither a production embedding provider nor a production-scale vector
backend (e.g. `SqliteVecBackend`) exists in this project yet. Do not call these numbers
"production Vector Search performance" -- they are an `ExactScanBackend` reference/fallback
baseline only, useful for judging how far a full linear-scan backend can be pushed before a
production backend becomes necessary.

No network access, no model download: vectors are generated from a seeded PRNG keyed on
each Memory's deterministic content, so a given `--seed` always reproduces the same dataset
and the same vectors. Never touches a real user Vault -- everything runs in an isolated
temporary directory that is removed when the script exits.

Usage:
    python scripts/vector_benchmark.py --count 1000 --dimension 384
    python scripts/vector_benchmark.py --count 10000 --dimension 384 --json out.json
    python scripts/vector_benchmark.py --count 10000 --dimension 768

This script is not part of the pytest suite (a 10k-Memory run is too slow to run on every
`pytest` invocation) -- run it explicitly when a benchmark is needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import resource
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin import db, hybrid_search, retrieval, search, vector_search  # noqa: E402
from brain_twin.config import Config  # noqa: E402
from brain_twin.embedding_provider import EmbeddingProfile  # noqa: E402
from brain_twin.embedding_service import EmbeddingService  # noqa: E402
from brain_twin.vector_exact import ExactScanBackend  # noqa: E402

TOPICS_POOL = [
    "running", "nutrition", "work", "family", "travel",
    "reading", "music", "finance", "health", "coding",
]


class DeterministicSyntheticProvider:
    """Offline, deterministic, seeded provider. No network call, no model download.

    Each vector is derived from `sha256(f"{seed}:{text}")`, so it depends only on the
    document text and the chosen `--seed` -- not on insertion order or wall-clock time --
    which is what makes a run reproducible across machines.
    """

    def __init__(self, dimension: int, *, seed: int, normalized: bool = True) -> None:
        self._profile = EmbeddingProfile(
            provider_id="synthetic-benchmark", model_name="deterministic-synthetic",
            model_revision=None, profile_epoch=f"benchmark-seed-{seed}",
            embedding_contract_version=1, dimension=dimension,
            normalized=normalized, document_template_version=1,
        )
        self._seed = seed
        self._normalized = normalized

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    def _vector_for(self, text: str) -> list[float]:
        digest = hashlib.sha256(f"{self._seed}:{text}".encode("utf-8")).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        values = [rng.uniform(-1.0, 1.0) for _ in range(self._profile.dimension)]
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:  # pragma: no cover -- astronomically unlikely with a real PRNG
            values[0] = 1.0
            norm = 1.0
        if self._normalized:
            values = [value / norm for value in values]
        return values

    def embed_documents(self, texts):
        return [self._vector_for(text) for text in texts]

    def embed_query(self, text):
        return self._vector_for(text)


class TimingExactScanBackend(ExactScanBackend):
    """Records `build()` time in place, so a single `EmbeddingService.sync()` call can be
    split into "embedding cache population" and "backend build" without running the
    (expensive) embedding step twice."""

    def __init__(self) -> None:
        self.build_seconds = 0.0
        self.build_calls = 0

    def build(self, conn, profile_fingerprint):
        start = time.perf_counter()
        result = super().build(conn, profile_fingerprint)
        self.build_seconds += time.perf_counter() - start
        self.build_calls += 1
        return result


@dataclass(frozen=True)
class LatencyStats:
    cold_seconds: float
    warm_median_seconds: float
    warm_p95_seconds: float
    warm_min_seconds: float
    warm_max_seconds: float
    warm_samples: int


def _time_repeated(fn, *, warm_repeats: int) -> LatencyStats:
    start = time.perf_counter()
    fn()
    cold = time.perf_counter() - start

    samples = []
    for _ in range(warm_repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    samples.sort()
    p95_index = min(len(samples) - 1, max(0, math.ceil(0.95 * len(samples)) - 1))
    return LatencyStats(
        cold_seconds=cold,
        warm_median_seconds=statistics.median(samples),
        warm_p95_seconds=samples[p95_index],
        warm_min_seconds=min(samples),
        warm_max_seconds=max(samples),
        warm_samples=len(samples),
    )


def _generate_dataset(conn, *, count: int, seed: int, link_every: int) -> None:
    """Deterministic synthetic Memories, inserted directly into SQLite (not via Markdown --
    this benchmark measures the DB/vector-retrieval layer, not Markdown I/O)."""
    base_rng = random.Random(f"dataset-{seed}")
    for index in range(count):
        memory_id = f"bench-{index:07d}"
        rng = random.Random(f"{seed}-{memory_id}")
        topic_count = rng.randint(1, 3)
        topics = rng.sample(TOPICS_POOL, topic_count)
        title = f"Memory {index} about {' and '.join(topics)}"
        content = (
            f"This is synthetic benchmark memory number {index}, concerning "
            f"{', '.join(topics)}. Deterministic content for reproducible retrieval."
        )
        day_offset = index % 3650
        event_date = f"{2016 + day_offset // 365}-{1 + (day_offset % 365) // 31:02d}-{1 + (day_offset % 31):02d}"
        db.upsert_memory(
            conn, id=memory_id, type="thought",
            created_at=f"{event_date}T00:00:00+00:00", event_date=event_date,
            importance=rng.randint(1, 5), confidence=round(rng.uniform(0.5, 1.0), 2),
            source="benchmark", status="active", title=title, content=content,
            raw_log_id=None, file_path=f"20_Memory/Thoughts/{memory_id}.md",
            topics_json=json.dumps(topics, ensure_ascii=False),
        )
        if link_every > 0 and index > 0 and index % link_every == 0:
            target_id = f"bench-{index - 1:07d}"
            db.upsert_link(
                conn, source_memory_id=memory_id, target_memory_id=target_id,
                relation_type="same_topic", reason="shared topic (synthetic)",
                strength=round(base_rng.uniform(0.2, 0.9), 3),
                created_at=f"{event_date}T00:00:00+00:00",
            )
    conn.commit()


def _machine_info() -> dict:
    import sqlite3

    rusage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "cpu_count_logical": _cpu_count(),
        # Linux reports ru_maxrss in KiB; other platforms may differ (documented, not
        # normalized here -- this script has only been run on Linux so far).
        "peak_rss_kb_at_report_time": rusage_kb,
    }


def _cpu_count() -> int | None:
    import os

    return os.cpu_count()


def run_benchmark(*, count: int, dimension: int, seed: int, warm_repeats: int, link_every: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="brain_twin_bench_") as tmp:
        tmp_path = Path(tmp)
        config = Config(
            project_root=tmp_path, vault_dir=tmp_path / "vault", data_dir=tmp_path / "data",
        )

        # --- A. dataset preparation ---
        start = time.perf_counter()
        with db.connect(config) as conn:
            _generate_dataset(conn, count=count, seed=seed, link_every=link_every)
        dataset_prep_seconds = time.perf_counter() - start

        provider = DeterministicSyntheticProvider(dimension, seed=seed)
        backend = TimingExactScanBackend()
        service = EmbeddingService(config, provider, backend)

        # --- B/C. canonical embedding cache population + first backend build ---
        start = time.perf_counter()
        sync_result = service.sync()
        sync_total_seconds = time.perf_counter() - start
        backend_build_seconds = backend.build_seconds
        embed_only_seconds = sync_total_seconds - backend_build_seconds

        # --- H. backend-only rebuild (never calls the provider) ---
        start = time.perf_counter()
        service.rebuild_backend()
        backend_only_rebuild_seconds = time.perf_counter() - start

        # --- D/E/F/G. query latency ---
        query_word = TOPICS_POOL[seed % len(TOPICS_POOL)]
        with db.connect(config) as conn:
            lexical_stats = _time_repeated(
                lambda: search.search(conn, query_word, limit=20), warm_repeats=warm_repeats
            )
            vector_stats = _time_repeated(
                lambda: vector_search.vector_search(conn, query_word, provider, backend, limit=20),
                warm_repeats=warm_repeats,
            )
            hybrid_stats = _time_repeated(
                lambda: hybrid_search.hybrid_search(conn, query_word, provider, backend, limit=20),
                warm_repeats=warm_repeats,
            )
            hybrid_primary = hybrid_search.hybrid_search(conn, query_word, provider, backend, limit=20)
            hybrid_related_stats = _time_repeated(
                lambda: retrieval.retrieve_from_primary(conn, hybrid_primary, related_limit=20),
                warm_repeats=warm_repeats,
            )

        # --- I. SQLite DB file size ---
        db_size_bytes = config.db_path.stat().st_size

        return {
            "params": {
                "count": count, "dimension": dimension, "seed": seed,
                "warm_repeats": warm_repeats, "link_every": link_every,
            },
            "machine": _machine_info(),
            "backend_label": "ExactScanBackend reference/fallback benchmark (no production provider, no SqliteVecBackend)",
            "phases": {
                "A_dataset_preparation_seconds": dataset_prep_seconds,
                "B_embedding_cache_population_seconds": embed_only_seconds,
                "C_first_backend_build_seconds": backend_build_seconds,
                "H_backend_only_rebuild_seconds": backend_only_rebuild_seconds,
                "sync_embedded": sync_result.embedded,
                "sync_skipped": sync_result.skipped,
            },
            "queries": {
                "D_lexical": asdict(lexical_stats),
                "E_vector_exact_scan": asdict(vector_stats),
                "F_hybrid": asdict(hybrid_stats),
                "G_hybrid_plus_related": asdict(hybrid_related_stats),
            },
            "I_db_size_bytes": db_size_bytes,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1000, help="number of synthetic Memories")
    parser.add_argument("--dimension", type=int, default=384, help="embedding vector dimension")
    parser.add_argument("--seed", type=int, default=42, help="deterministic seed for dataset+vectors")
    parser.add_argument("--warm-repeats", type=int, default=20, help="warm query repeats for stats")
    parser.add_argument(
        "--link-every", type=int, default=20,
        help="create a link every N memories (0 disables links)",
    )
    parser.add_argument("--json", type=Path, default=None, help="optional path to write JSON results")
    args = parser.parse_args()

    result = run_benchmark(
        count=args.count, dimension=args.dimension, seed=args.seed,
        warm_repeats=args.warm_repeats, link_every=args.link_every,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[written] {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
