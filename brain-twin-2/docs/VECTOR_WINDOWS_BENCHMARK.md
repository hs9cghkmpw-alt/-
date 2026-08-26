# Vector Search Benchmark — ExactScanBackend reference/fallback

Status: **measured on a Linux remote execution environment, NOT the Windows dev machine
requested by the task. Explicitly a substitute reference run** (see "Environment"
below). A Windows-machine re-run is still required before this can be cited as the
official Sprint 4D Windows benchmark; see "Windows official run" at the end of this document
(pending).

## Sprint 4D benchmark final hardening (this round)

External review of the original Linux reference run below required three fixes to
`scripts/vector_benchmark.py` before a Windows run could even be attempted:

1. **Windows portability**: the script imported the POSIX-only `resource` module
   unconditionally at module top-level, which fails on Windows (no `resource` module exists
   there) and would have crashed the script before it could run at all. Fixed with a guarded
   `try`/`except ImportError` and a `_peak_rss_kb()` helper that returns `None` (with an
   explanatory `rss_measurement` string) instead of raising when `resource` is unavailable —
   no optional dependency (e.g. `psutil`) was added, and a missing memory metric never fails
   the benchmark run itself.
2. **`G` was mislabeled**: the original run's `G_hybrid_plus_related` value only measured
   `retrieval.retrieve_from_primary()` on a Hybrid Primary result that had already been
   computed *once, outside the timed loop*. That is **related-expansion overhead only**, not
   the end-to-end latency of `search --hybrid --related`. This is now `G_related_expansion_only`
   (kept — it is still a useful, valid metric), plus a new `H_hybrid_plus_related_end_to_end`
   that calls `hybrid_search.hybrid_search()` **and** `retrieval.retrieve_from_primary()`
   inside the same timed callable on every cold/warm sample — this is the number that reflects
   what a caller of `search --hybrid --related` actually experiences.
3. **Invalid synthetic dates**: `event_date` was computed with hand-rolled month/day
   arithmetic (`1 + (day_offset % 365) // 31`, `1 + (day_offset % 31)`), which can produce
   invalid calendar dates such as `2016-02-30`. Replaced with
   `_BENCHMARK_BASE_DATE + timedelta(days=day_offset)`, which always yields a valid,
   deterministic `YYYY-MM-DD` for a given seed/count.

The original run's tables are kept below as a **historical, explicitly-relabeled** record
(per instruction, not deleted); a **corrected Linux reference run** with the fixed script
follows in its own section. Windows numbers, once collected, go in their own "Windows
official run" section — Linux and Windows values are never merged into one table.

This benchmark measures **`ExactScanBackend` + a synthetic, offline, deterministic
embedding provider only**. There is no production embedding provider and no production-scale
vector backend (e.g. `SqliteVecBackend`) implemented in this project yet. These numbers must
never be cited as "production Vector Search performance" — they are an `ExactScanBackend`
reference/fallback baseline, useful for judging how far a full linear-scan backend can be
pushed before a production backend becomes necessary.

## Environment

This run was executed in this session's Linux remote execution container, not a real Windows
machine, because this session has no access to Windows hardware. The task explicitly asked for
this data to be recorded and clearly labeled as a substitute, so it is:

| Field | Value |
|---|---|
| OS | Linux (`Linux-6.18.44-fc-v21-x86_64-with-glibc2.39`) — **not Windows** |
| Kernel release | `6.18.44-fc-v21` |
| Architecture | `x86_64` |
| Python version | `3.11.15` |
| `sqlite3.sqlite_version` | `3.45.1` |
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz |
| CPU logical count | 4 |
| RAM | 15 GiB (per `free -h`) |

**Windows version, and a from-scratch confirmation of these numbers on the actual Windows
development machine, are still outstanding** and must be filled in before Sprint 4D's Windows
benchmark item is considered complete. Everything else in this document (methodology,
metrics, findings, recommendation) is otherwise complete and reusable once that Windows run
happens — only the "which machine ran this" column needs to change.

## Methodology

- Script: `brain-twin-2/scripts/vector_benchmark.py` (not part of the pytest suite — run
  explicitly; a 10k-Memory run is too slow for every `pytest` invocation).
- No network access, no model download: an offline `DeterministicSyntheticProvider` derives
  each vector from `sha256(f"{seed}:{text}")` seeding a local PRNG — fully reproducible given
  the same `--seed`, independent of insertion order or wall-clock time.
- Never touches a real user Vault: everything runs inside a `tempfile.TemporaryDirectory()`
  that is deleted when the script exits.
- Dataset: synthetic Memories with a deterministic id (`bench-0000001`, ...), templated
  title/content referencing 1-3 topics drawn from a fixed pool, a deterministic `event_date`
  spread across ~10 years, `importance`/`confidence` from a seeded RNG, and a Link created
  every 20th Memory (to exercise Associative Retrieval's 1-hop expansion, not just isolated
  Memories). Inserted directly into SQLite (`db.upsert_memory`/`db.upsert_link`), not through
  Markdown — this benchmark measures the DB/vector-retrieval layer, not Markdown I/O.
- Each latency metric is a **cold** call followed by **20 warm repeats**, reporting median,
  p95, min, and max — never a single-call time.
- `time.perf_counter()` is used throughout. Peak RSS is read from
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` when the (POSIX-only) `resource` module is
  importable; on a platform without it (Windows), `_peak_rss_kb()` returns `None` and
  `rss_measurement` explains why, rather than crashing or requiring an optional dependency
  (e.g. `psutil`) just for a benchmark metric.

### Phases measured

Note: the "phases" and "queries" sections of the script's JSON output are separate dicts, so
letters are reused with different meanings across the two — `phases["H_..."]` (backend-only
rebuild) is unrelated to `queries["H_..."]` (hybrid + related end-to-end).

| Code | Phase |
|---|---|
| A | dataset preparation (synthetic Memory/Link generation + SQLite insert) |
| B | canonical embedding cache population (`EmbeddingService.sync()`, provider calls) |
| C | first backend build (captured via a `build()`-timing `ExactScanBackend` subclass, so it does not require a second, redundant full build to measure in isolation) |
| D | pure lexical query (`search.search()`) |
| E | Vector `ExactScanBackend` query (`vector_search.vector_search()`) |
| F | Hybrid query (`hybrid_search.hybrid_search()`) |
| G | Related-expansion overhead only (`retrieval.retrieve_from_primary()` on a Hybrid Primary result computed once, outside the timed loop) |
| H (phases dict) | backend-only rebuild (`EmbeddingService.rebuild_backend()` — never calls the provider) |
| H (queries dict) | Hybrid + Related end-to-end (`hybrid_search.hybrid_search()` **and** `retrieval.retrieve_from_primary()`, both inside the same timed callable on every sample) |
| I | SQLite DB file size after sync |

For `ExactScanBackend`, `build()` only validates that every canonical BLOB decodes at the
expected dimension (there is no separate index structure) — so phase C and the backend-only
rebuild measure essentially the same operation; they are reported separately anyway to match
the task's requested phase list.

## Results (original run, 2026-08-25 — historical, `G` mislabeled)

**`G` in this section was measured as related-expansion overhead only, not
end-to-end "hybrid + related" latency** — see "Sprint 4D benchmark final hardening" above.
Kept here unmodified per instruction (not deleted); use the "Corrected Linux reference run"
section below for the accurate `G`/`H` split.

All latencies in seconds unless noted. "warm" = median of 20 repeats after 1 cold call
(cold and warm are reported separately below; they were consistently close, i.e. no
meaningful cache-warming effect at this scale on this machine).

### 1,000 Memories / dimension 384

| Phase | Value |
|---|---|
| A. dataset preparation | 0.151 s |
| B. embedding cache population | 0.278 s |
| C. first backend build | 0.034 s |
| H. backend-only rebuild | 0.044 s |
| I. DB file size | 3,866,624 bytes (~3.7 MiB) |

| Query | cold | warm median | warm p95 | warm min | warm max |
|---|---|---|---|---|---|
| D. lexical | 0.0040 s | 0.0017 s | 0.0018 s | 0.0016 s | 0.0019 s |
| E. vector (ExactScan) | 0.0608 s | 0.0583 s | 0.0600 s | 0.0554 s | 0.0605 s |
| F. hybrid | 0.0591 s | 0.0605 s | 0.0617 s | 0.0588 s | 0.0631 s |
| G. related expansion only (mislabeled at the time as "hybrid + related") | 0.0042 s | 0.0039 s | 0.0044 s | 0.0038 s | 0.0044 s |

### 10,000 Memories / dimension 384

| Phase | Value |
|---|---|
| A. dataset preparation | 1.524 s |
| B. embedding cache population | 3.639 s |
| C. first backend build | 0.497 s |
| H. backend-only rebuild | 0.492 s |
| I. DB file size | 37,285,888 bytes (~35.6 MiB) |

| Query | cold | warm median | warm p95 | warm min | warm max |
|---|---|---|---|---|---|
| D. lexical | 0.0098 s | 0.0077 s | 0.0082 s | 0.0076 s | 0.0085 s |
| E. vector (ExactScan) | 0.618 s | 0.601 s | 0.625 s | 0.584 s | 0.629 s |
| F. hybrid | 0.613 s | 0.614 s | 0.631 s | 0.592 s | 0.643 s |
| G. related expansion only (mislabeled at the time as "hybrid + related") | 0.058 s | 0.058 s | 0.061 s | 0.055 s | 0.061 s |

### 10,000 Memories / dimension 768

| Phase | Value |
|---|---|
| A. dataset preparation | 1.540 s |
| B. embedding cache population | 5.192 s |
| C. first backend build | 0.997 s |
| H. backend-only rebuild | 0.842 s |
| I. DB file size | 57,810,944 bytes (~55.1 MiB) |

| Query | cold | warm median | warm p95 | warm min | warm max |
|---|---|---|---|---|---|
| D. lexical | 0.0100 s | 0.0077 s | 0.0085 s | 0.0076 s | 0.0088 s |
| E. vector (ExactScan) | 1.160 s | 1.157 s | 1.264 s | 1.124 s | 1.322 s |
| F. hybrid | 1.151 s | 1.152 s | 1.178 s | 1.120 s | 1.191 s |
| G. related expansion only (mislabeled at the time as "hybrid + related") | 0.060 s | 0.060 s | 0.063 s | 0.058 s | 0.075 s |

Peak RSS (`ru_maxrss`, reported at end of run, Linux KiB): ~28.8 MB at 1k/384, ~44.5 MB at
10k/384, ~59.3 MB at 10k/768. This is the whole benchmark process's peak resident set, not an
isolated per-query allocation — treat it as a rough order-of-magnitude signal only.

Raw JSON output for all three runs is not committed to the repository (per the task's
instruction not to commit large generated benchmark output); re-run the commands below to
reproduce them, or ask for the JSON files directly.

```bash
python scripts/vector_benchmark.py --count 1000 --dimension 384 --json /tmp/1k_384.json
python scripts/vector_benchmark.py --count 10000 --dimension 384 --json /tmp/10k_384.json
python scripts/vector_benchmark.py --count 10000 --dimension 768 --json /tmp/10k_768.json
```

## Corrected Linux reference run (2026-08-26, after Sprint 4D benchmark final hardening)

Same Linux environment as above (see "Environment"), same script, same `--seed 42` — re-run
after the three fixes in "Sprint 4D benchmark final hardening". This is a genuine re-measurement,
not a recalculation of the original numbers: `A`/`B`/`C`/backend-only-rebuild/`D`/`E`/`F`/`I`
differ slightly from the original run purely from ordinary run-to-run variance on this shared
machine (they measure the same operations as before — the event-date and RSS fixes do not
change their cost). `G` and `H` are the metrics that actually changed in *meaning*: `G` is now
correctly labeled "related expansion only", and `H` is a new, genuine end-to-end measurement
that did not exist in the original run.

### 1,000 Memories / dimension 384

| Phase | Value |
|---|---|
| A. dataset preparation | 0.181 s |
| B. embedding cache population | 0.397 s |
| C. first backend build | 0.085 s |
| backend-only rebuild | 0.052 s |
| I. DB file size | 3,866,624 bytes (~3.7 MiB) |

| Query | cold | warm median | warm p95 | warm min | warm max |
|---|---|---|---|---|---|
| D. lexical | 0.0047 s | 0.0017 s | 0.0019 s | 0.0016 s | 0.0019 s |
| E. vector (ExactScan) | 0.0709 s | 0.0680 s | 0.0762 s | 0.0650 s | 0.0815 s |
| F. hybrid | 0.0821 s | 0.0699 s | 0.0740 s | 0.0661 s | 0.0757 s |
| G. related expansion only | 0.0049 s | 0.0046 s | 0.0052 s | 0.0042 s | 0.0053 s |
| H. hybrid + related (end-to-end) | 0.0752 s | 0.0737 s | 0.0802 s | 0.0710 s | 0.0805 s |

### 10,000 Memories / dimension 384

| Phase | Value |
|---|---|
| A. dataset preparation | 1.658 s |
| B. embedding cache population | 4.635 s |
| C. first backend build | 0.614 s |
| backend-only rebuild | 0.567 s |
| I. DB file size | 37,294,080 bytes (~35.6 MiB) |

| Query | cold | warm median | warm p95 | warm min | warm max |
|---|---|---|---|---|---|
| D. lexical | 0.0102 s | 0.0086 s | 0.0091 s | 0.0083 s | 0.0101 s |
| E. vector (ExactScan) | 0.653 s | 0.669 s | 0.724 s | 0.654 s | 0.813 s |
| F. hybrid | 0.671 s | 0.677 s | 0.692 s | 0.655 s | 0.734 s |
| G. related expansion only | 0.067 s | 0.065 s | 0.066 s | 0.064 s | 0.066 s |
| H. hybrid + related (end-to-end) | 0.735 s | 0.743 s | 0.770 s | 0.720 s | 0.783 s |

### 10,000 Memories / dimension 768

| Phase | Value |
|---|---|
| A. dataset preparation | 1.570 s |
| B. embedding cache population | 6.032 s |
| C. first backend build | 1.257 s |
| backend-only rebuild | 0.935 s |
| I. DB file size | 57,819,136 bytes (~55.1 MiB) |

| Query | cold | warm median | warm p95 | warm min | warm max |
|---|---|---|---|---|---|
| D. lexical | 0.0113 s | 0.0083 s | 0.0090 s | 0.0076 s | 0.0095 s |
| E. vector (ExactScan) | 1.272 s | 1.265 s | 1.317 s | 1.226 s | 1.319 s |
| F. hybrid | 1.254 s | 1.257 s | 1.312 s | 1.230 s | 1.313 s |
| G. related expansion only | 0.064 s | 0.065 s | 0.068 s | 0.064 s | 0.069 s |
| H. hybrid + related (end-to-end) | 1.320 s | 1.343 s | 1.355 s | 1.297 s | 1.359 s |

Peak RSS (`ru_maxrss`, KiB): ~28.9 MB at 1k/384, ~44.5 MB at 10k/384, ~59.7 MB at 10k/768 —
consistent with the original run's numbers (whole-process peak, not per-operation).

Confirming `H ≈ F + G` (within measurement noise) is exactly what the fix should produce: the
end-to-end cost of `search --hybrid --related` is (to a first approximation) the Hybrid query
cost plus the related-expansion overhead, run back-to-back on every sample — e.g. at
10k/384, F (0.677s) + G (0.065s) ≈ 0.742s, matching H (0.743s) closely.

Raw JSON for this corrected run is likewise not committed to the repository; reproduce with
the same commands as above (same script, same flags).

## Interpretation

- Lexical search (D) stays fast and nearly flat (~2-8 ms) from 1k to 10k Memories — SQLite
  FTS5 scales as expected for this workload.
- Vector `ExactScanBackend` search (E) and Hybrid (F, which is dominated by its own internal
  `ExactScanBackend.search()` call) scale roughly linearly with `count × dimension`, as
  expected for a full linear cosine scan with no index: ~58 ms (1k/384) → ~601 ms (10k/384,
  ~10x count → ~10x latency) → ~1.16 s (10k/768, ~2x dimension → ~2x latency on top of that).
  This is the expected behavior of a backend that is explicitly documented as having "no
  separate index" (`vector_exact.py`) — it is not a bug, it is the architecture.
- Related-expansion overhead (G) is cheap relative to E/F: the 1-hop expansion only touches
  the `links` table and a handful of ids, not the full candidate scan. Genuine end-to-end
  Hybrid + Related latency (H, corrected run) is therefore dominated by the Hybrid query
  itself (F) — `H ≈ F + G` held closely across all three corrected-run configurations.
- Backend build/rebuild (C/H) is proportional to `count` (blob-decode validation only) and is
  a small fraction of total sync time compared to embedding cache population (B), as expected
  since B is dominated here by the (synthetic, cheap) provider call plus per-item DB writes.
- DB file size scales linearly with `count × dimension` as expected (uncompressed float
  vectors dominate the canonical embedding cache).

## Recommended ExactScanBackend operating range (observed values, not a hard-coded threshold)

Based on the Linux reference runs only (both the original and corrected measurements agree at
this order of magnitude):

- **Comfortably interactive (single-digit-ms to ~70ms range): up to ~1,000 Memories.** Vector/
  Hybrid queries stayed at ~60-70 ms including the query embedding step.
- **Still usable but noticeably slower for an interactive CLI: ~1,000-5,000 Memories**
  (extrapolating linearly from the 1k→10k trend, ~5,000 Memories would land Vector/Hybrid
  queries in the ~300-350 ms range at dimension 384). Not benchmarked directly at 5,000 in
  this round.
- **Warning-candidate range: ~10,000+ Memories**, where a single Vector or Hybrid query
  already costs ~0.65-1.3 s depending on dimension, and genuine end-to-end Hybrid + Related is
  in the same range (H ≈ F + a small G). At this scale a real ANN backend (e.g.
  `SqliteVecBackend`) would materially improve interactive latency; `ExactScanBackend` remains
  correct here, just increasingly slow per query.
- These are **observed values from one machine, two runs (before/after the benchmark script
  fixes), synthetic vectors, and a small Memory-count range (1k/10k only, no 100k point)** —
  per the task's explicit instruction, no hard-coded item-count threshold is implemented in
  code based on this alone. A concrete threshold (e.g. a CLI warning above N Memories) should
  go through its own separate review once a Windows re-run and, ideally, a 100k-scale data
  point are available.

## Windows official run

**Pending.** This session has no Windows machine; if this document's fixes were applied by a
session running on the actual Windows development machine, its official run belongs in this
section (environment table + phase/query tables in the same format as the corrected Linux
run above), and this "pending" line should be replaced accordingly. Do not fill in Windows
numbers by estimation, extrapolation, or reuse of the Linux figures above — only a real run on
Windows hardware belongs here. Until this section has real data, Sprint 4D's Windows
benchmark requirement remains unmet.

## Known limitations

- Windows benchmark is still pending (see "Windows official run" above) — the Linux runs in
  this document are explicit substitutes, not the official Sprint 4D Windows benchmark.
- Synthetic random vectors have no real semantic structure, so similarity-ranking *quality* is
  not evaluated here at all — this benchmark is about latency/throughput/size only.
- No 100k-Memory data point (explicitly not required this round per the task).
- `ExactScanBackend` has no separate index, so "backend build" (C) is unusually cheap here
  compared to what a real ANN backend's index-construction phase would cost; do not
  extrapolate this build-time number to a future `SqliteVecBackend`.
- Peak RSS is a whole-process, POSIX-only (`resource` module) measurement, not a precise
  per-operation memory cost; it will read as `None`/`"unavailable..."` on Windows rather than
  crash, per this round's portability fix, but no Windows-native equivalent (e.g. via
  `psutil`) was added.
