# Vector Search Benchmark — ExactScanBackend reference/fallback

Status: **measured on a Linux remote execution environment, NOT the Windows dev machine
requested by the task. Explicitly a substitute reference run** (see "Environment"
below). A Windows-machine re-run is still required before this can be cited as the
official Sprint 4D Windows benchmark.

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
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` (Linux reports KiB; noted as
  Linux-specific — a Windows equivalent would need a different API, e.g. `psutil`, and was
  not added here to avoid growing this benchmark's dependencies).

### Phases measured

| Code | Phase |
|---|---|
| A | dataset preparation (synthetic Memory/Link generation + SQLite insert) |
| B | canonical embedding cache population (`EmbeddingService.sync()`, provider calls) |
| C | first backend build (captured via a `build()`-timing `ExactScanBackend` subclass, so it does not require a second, redundant full build to measure in isolation) |
| D | pure lexical query (`search.search()`) |
| E | Vector `ExactScanBackend` query (`vector_search.vector_search()`) |
| F | Hybrid query (`hybrid_search.hybrid_search()`) |
| G | Hybrid + Related 1-hop (`retrieval.retrieve_from_primary()` on the Hybrid Primary result) |
| H | backend-only rebuild (`EmbeddingService.rebuild_backend()` — never calls the provider) |
| I | SQLite DB file size after sync |

For `ExactScanBackend`, `build()` only validates that every canonical BLOB decodes at the
expected dimension (there is no separate index structure) — so phase C and phase H measure
essentially the same operation; they are reported separately anyway to match the task's
requested phase list.

## Results

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
| G. hybrid + related | 0.0042 s | 0.0039 s | 0.0044 s | 0.0038 s | 0.0044 s |

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
| G. hybrid + related | 0.058 s | 0.058 s | 0.061 s | 0.055 s | 0.061 s |

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
| G. hybrid + related | 0.060 s | 0.060 s | 0.063 s | 0.058 s | 0.075 s |

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

## Interpretation

- Lexical search (D) stays fast and nearly flat (~2-8 ms) from 1k to 10k Memories — SQLite
  FTS5 scales as expected for this workload.
- Vector `ExactScanBackend` search (E) and Hybrid (F, which is dominated by its own internal
  `ExactScanBackend.search()` call) scale roughly linearly with `count × dimension`, as
  expected for a full linear cosine scan with no index: ~58 ms (1k/384) → ~601 ms (10k/384,
  ~10x count → ~10x latency) → ~1.16 s (10k/768, ~2x dimension → ~2x latency on top of that).
  This is the expected behavior of a backend that is explicitly documented as having "no
  separate index" (`vector_exact.py`) — it is not a bug, it is the architecture.
- Hybrid + Related (G) is cheap relative to E/F: the 1-hop expansion only touches the `links`
  table and a handful of ids, not the full candidate scan.
- Backend build/rebuild (C/H) is proportional to `count` (blob-decode validation only) and is
  a small fraction of total sync time compared to embedding cache population (B), as expected
  since B is dominated here by the (synthetic, cheap) provider call plus per-item DB writes.
- DB file size scales linearly with `count × dimension` as expected (uncompressed float
  vectors dominate the canonical embedding cache).

## Recommended ExactScanBackend operating range (observed values, not a hard-coded threshold)

Based on this single reference run only:

- **Comfortably interactive (single-digit-ms to ~60ms range): up to ~1,000 Memories.** Vector/
  Hybrid queries stayed at ~58-60 ms even including the query embedding step.
- **Still usable but noticeably slower for an interactive CLI: ~1,000-5,000 Memories**
  (extrapolating linearly from the 1k→10k trend, ~5,000 Memories would land Vector/Hybrid
  queries in the ~250-300 ms range at dimension 384). Not benchmarked directly at 5,000 in
  this round.
- **Warning-candidate range: ~10,000+ Memories**, where a single Vector or Hybrid query
  already costs ~0.6-1.2 s depending on dimension. At this scale a real ANN backend (e.g.
  `SqliteVecBackend`) would materially improve interactive latency; `ExactScanBackend` remains
  correct here, just increasingly slow per query.
- These are **observed values from one machine, one run, synthetic vectors, and a small
  Memory-count range (1k/10k only, no 100k point)** — per the task's explicit instruction, no
  hard-coded item-count threshold is implemented in code based on this alone. A concrete
  threshold (e.g. a CLI warning above N Memories) should go through its own separate review
  once a Windows re-run and, ideally, a 100k-scale data point are available.

## Known limitations

- Run on Linux, not the requested Windows machine (see "Environment" above) — must be
  re-verified on Windows before this is the authoritative Sprint 4D Windows benchmark.
- Synthetic random vectors have no real semantic structure, so similarity-ranking *quality* is
  not evaluated here at all — this benchmark is about latency/throughput/size only.
- No 100k-Memory data point (explicitly not required this round per the task).
- `ExactScanBackend` has no separate index, so "backend build" (C/H) is unusually cheap here
  compared to what a real ANN backend's index-construction phase would cost; do not
  extrapolate this build-time number to a future `SqliteVecBackend`.
- Peak RSS is a whole-process, Linux-specific measurement, not a precise per-operation memory
  cost, and no direct Windows equivalent was collected.
