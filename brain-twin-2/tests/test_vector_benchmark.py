"""Sprint 4D benchmark final hardening: lightweight tests for the portable parts of
scripts/vector_benchmark.py.

The 10k-scale benchmark itself stays out of the pytest suite (too slow to run on every
`pytest` invocation, and its own module docstring says so); these tests only cover small,
fast, deterministic pieces: RSS collection degrading gracefully without the (POSIX-only)
`resource` module, generated dates always being valid, the related-expansion-only metric
being structurally distinct from the hybrid+related end-to-end metric, and a tiny end-to-end
smoke run of `run_benchmark()` itself.
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

import pytest

from brain_twin import db
from brain_twin.config import Config

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "vector_benchmark.py"
_spec = importlib.util.spec_from_file_location("vector_benchmark", _SCRIPT_PATH)
vector_benchmark = importlib.util.module_from_spec(_spec)
sys.modules["vector_benchmark"] = vector_benchmark
_spec.loader.exec_module(vector_benchmark)


def test_machine_info_does_not_raise_without_the_resource_module(monkeypatch):
    """`resource` has no Windows build; `_machine_info()` must degrade to `None`/an
    explanatory string instead of raising, so the benchmark itself never fails just because
    a memory metric isn't available on this platform."""
    monkeypatch.setattr(vector_benchmark, "resource", None)
    info = vector_benchmark._machine_info()
    assert info["peak_rss_kb_at_report_time"] is None
    assert "unavailable" in info["rss_measurement"]


def test_machine_info_reports_rss_when_resource_is_available():
    info = vector_benchmark._machine_info()
    if vector_benchmark.resource is None:
        pytest.skip("resource module not available on this platform")
    assert isinstance(info["peak_rss_kb_at_report_time"], int)
    assert info["rss_measurement"] == "kib_via_resource_ru_maxrss"


def test_generated_event_dates_are_always_valid_calendar_dates(config):
    with db.connect(config) as conn:
        vector_benchmark._generate_dataset(conn, count=400, seed=7, link_every=0)
        rows = conn.execute("SELECT event_date FROM memories").fetchall()

    assert len(rows) == 400
    for (event_date,) in rows:
        # Raises ValueError on an invalid date (e.g. the Feb-30-style bug this replaces);
        # a passing test proves every generated date really is a valid calendar date.
        datetime.date.fromisoformat(event_date)


def test_generated_event_dates_are_deterministic_across_runs(tmp_path):
    config_a = Config(project_root=tmp_path / "a", vault_dir=tmp_path / "a" / "vault", data_dir=tmp_path / "a" / "data")
    config_b = Config(project_root=tmp_path / "b", vault_dir=tmp_path / "b" / "vault", data_dir=tmp_path / "b" / "data")

    with db.connect(config_a) as conn:
        vector_benchmark._generate_dataset(conn, count=50, seed=7, link_every=0)
        dates_a = [row[0] for row in conn.execute("SELECT event_date FROM memories ORDER BY id").fetchall()]
    with db.connect(config_b) as conn:
        vector_benchmark._generate_dataset(conn, count=50, seed=7, link_every=0)
        dates_b = [row[0] for row in conn.execute("SELECT event_date FROM memories ORDER BY id").fetchall()]

    assert dates_a == dates_b


def test_related_expansion_only_and_end_to_end_are_structurally_distinct_metrics(monkeypatch):
    """G (related-expansion-only) must compute the Hybrid primary result ONCE, outside the
    timed loop; H (hybrid+related end-to-end) must call hybrid_search() fresh on every
    sample. Counting real hybrid_search() calls proves this structurally, instead of
    comparing noisy wall-clock timings on a tiny dataset."""
    calls = {"count": 0}
    real_hybrid_search = vector_benchmark.hybrid_search.hybrid_search

    def counting_hybrid_search(*args, **kwargs):
        calls["count"] += 1
        return real_hybrid_search(*args, **kwargs)

    monkeypatch.setattr(vector_benchmark.hybrid_search, "hybrid_search", counting_hybrid_search)

    warm_repeats = 3
    result = vector_benchmark.run_benchmark(
        count=20, dimension=8, seed=1, warm_repeats=warm_repeats, link_every=5
    )

    assert "G_related_expansion_only" in result["queries"]
    assert "H_hybrid_plus_related_end_to_end" in result["queries"]

    # F_hybrid: (1 cold + warm_repeats) calls.
    # G: exactly 1 call (the primary is computed once, outside retrieve_from_primary's timing).
    # H: (1 cold + warm_repeats) calls (hybrid_search re-run inside the timed callable).
    expected_calls = (1 + warm_repeats) + 1 + (1 + warm_repeats)
    assert calls["count"] == expected_calls


def test_run_benchmark_small_count_smoke_run():
    result = vector_benchmark.run_benchmark(count=30, dimension=8, seed=3, warm_repeats=2, link_every=5)

    assert result["phases"]["sync_embedded"] == 30
    for key in ("D_lexical", "E_vector_exact_scan", "F_hybrid", "G_related_expansion_only", "H_hybrid_plus_related_end_to_end"):
        assert key in result["queries"]
        assert result["queries"][key]["warm_samples"] == 2
    assert result["I_db_size_bytes"] > 0
    assert result["machine"]["system"] in ("Linux", "Darwin", "Windows")
