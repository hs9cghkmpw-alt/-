# Brain Twin 2 — Current State

Last updated: 2026-08-27

## Active development context

- Repository: `hs9cghkmpw-alt/-`
- Project: `brain-twin-2/`
- Working branch: `brain-twin-dev`
- Legacy project `brain-twin/`: out of scope unless explicitly requested

## Current phase

- Phase 1 — Memory Foundation: **complete**
- Phase 2 — Automatic Memory Worker / Entity Extraction / Link generation: **complete**
- Phase 3 — Retrieval:
  - Associative Retrieval (1-hop outgoing + incoming links): **implemented**
  - Timeline Search (`event_date` range filtering): **implemented**
  - Final hardening review: **complete**
- Phase 4 — Vector Retrieval Core: **GO / COMPLETE**
  - Sprint 4A: **COMPLETE**
  - Sprint 4B: **COMPLETE**
  - Sprint 4C: **COMPLETE**
  - Sprint 4D: **GO / COMPLETE**
  - Windows official ExactScan benchmark: **complete** on the Windows development machine
    (Windows 11, AMD64, Python 3.12.10, SQLite 3.49.1; full results and Linux comparison in
    `docs/VECTOR_WINDOWS_BENCHMARK.md`).
- Production Vector Search activation: **PENDING**
  - production embedding provider is not implemented;
  - production-scale vector backend is not implemented/selected;
  - Japanese semantic retrieval quality evaluation has not been performed.
  Phase 4 core completion does not mean the Vector Search product feature is production-ready.

## Last known good implementation

- Implementation commit: `68ac6e420332bf87feecb47eb32b67cd84bd4016`
- Commit title: `brain-twin-2: close Sprint 4D after Windows benchmark`
- Local Windows tests: **321 passed, 1 skipped** (expected POSIX-only `resource` skip)
- GitHub Actions run: `33033340980`
- GitHub Actions result: **success** (`headSha` exactly matched the implementation commit)
- External review: Sprint 4D **GO / COMPLETE**; Phase 4 Vector Retrieval Core
  **GO / COMPLETE**.

## Completed review fixes — verify before Vector Search

### 1. Persist real link strength through Retrieval

Phase 2の実 `LinkSuggestion.strength` をMarkdown `link_details`とSQLiteへ保存し、
Retrievalも固定relation weightではなく保存値の合計でrankingする。legacy Linkは
relation種別によらない保守的なstrength `0.25`へ非破壊migration/reindexする。

- process / reindex / reconcile / crash recoveryで同じstrengthを復元
- strength列の無い既存DBはconnect時に非破壊self-heal

### 2. Avoid loading every related Memory body before applying `related_limit`

ranking前は本文を含まない軽量candidateだけを取得し、dedupe/ranking後の
`related_limit` IDに限ってtitle/content/type/event_dateを取得する。
outgoing/incoming、inactive除外、1-hop、決定的順序は維持する。

### 3. Sprint 4C: embedding consistency race between provider call and cache write

`EmbeddingService.sync()` computed a Memory's `content_hash` before the (potentially slow)
provider call, then wrote `is_valid=1` using that pre-call hash without re-checking current
content. A concurrent title/content edit during the provider call could let a stale vector
become searchable.

First pass: re-read the Memory in a short (non-transactional) read immediately before the
write and skip the write when the current content_hash no longer matched. This closed the
"during the provider call" window but left a second, narrower window open: another writer
could still commit a change between that re-read and the canonical write itself, because the
re-read was a plain `SELECT` that did not yet hold the write lock.

Final hardening (this round): the commit-chunk write path now issues `BEGIN IMMEDIATE`
*before* the re-verification read, so the read-verify-write sequence for canonical cache +
backend `sync_upsert` runs inside one held write lock, with no gap a second writer could use.
The provider call itself stays outside any transaction. On any exception the transaction is
rolled back and the item is left for the next `sync()` to reprocess; staging activation still
re-verifies `ready == total_active` immediately before switching the active profile/backend.

### 4. Sprint 4C: deterministic lexical tie-break for Hybrid ranking

`db.search_lexical_candidates()` (the Hybrid-only pure-BM25 API) ordered by `bm25()` score
alone; tied scores (e.g. near-duplicate content) left `lexical_rank` order unspecified, which
could make Hybrid's RRF fusion and best-channel-rank tie-break non-deterministic across
otherwise-identical calls. Added an explicit `ORDER BY score ASC, m.id ASC` tie-break to this
Hybrid-only function. `db.search()` / `search.search()` (the plain-search backward-compat
path) are unchanged.

### 5. Sprint 4D: connect Hybrid/Vector Primary to Associative Retrieval

`--vector --related` / `--hybrid --related` previously returned an explicit "not yet
supported" error; Associative Retrieval's 1-hop expansion only ran for plain lexical
`search`. The expansion logic in `retrieval.py` (previously inlined in `retrieve()`) is now
`retrieve_from_primary()`: it only requires each primary result to expose `memory_id`
(a `Protocol`/`TypeVar`, not a concrete import of `search.ScoredResult`), so it works
unchanged for `search.ScoredResult`, `vector_search.VectorResult`, and `hybrid_search.
HybridResult` alike. `retrieve()` now just calls `search.search()` then delegates to
`retrieve_from_primary()` — its behavior and output are unchanged (existing
`tests/test_retrieval.py` tests pass without modification). The CLI wires `--vector
--related` / `--hybrid --related` through the same function, so relation display is
identical to the plain-`--related` path.

### 6. Sprint 4D: CLI hardening for negative `--related-limit`

`search --vector/--hybrid --related --related-limit -1` used to run Primary search (and, for
`--vector`/`--hybrid`, embedding config/provider setup and the vector/hybrid query itself)
before the `related_limit` validation raised — printing Primary results to stdout for a
command that was ultimately an error, and doing unnecessary provider/vector work. `_cmd_search`
now validates `args.related and args.related_limit < 0` before any of that starts, for the
plain/`--vector`/`--hybrid` paths alike: a clear `[NG]` error, non-zero exit, no provider call,
no vector/hybrid search call, nothing printed to stdout.

### 7. Sprint 4D: Windows benchmark (Linux-substitute) and failure/recovery/migration/corruption validation

`scripts/vector_benchmark.py` measures `ExactScanBackend` + a synthetic offline deterministic
provider at 1k and 10k Memories, dimension 384 and 768 — explicitly labeled as an
`ExactScanBackend` reference/fallback benchmark, never "production Vector Search performance"
(no production provider or `SqliteVecBackend` exists). Run in this session's Linux remote
execution environment as an explicit substitute for the requested Windows machine; a Windows
re-run is still needed. Full methodology/results/interpretation in
`docs/VECTOR_WINDOWS_BENCHMARK.md`.

Failure/recovery/migration/corruption scenarios (provider partial-failure resume, profile
switch failure keeping the old active profile, backend index loss recovering via
`rebuild_backend()`, a stale Memory being excluded from Vector-only but still reachable via
Hybrid's lexical channel until resync, inactive/delete exclusion, a full SQLite-file deletion
followed by `reindex` + embedding resync, a combined legacy-schema self-heal fixture, and
malformed/corrupted-cache rejection) were validated against real DB fixtures — new end-to-end
tests plus citations of pre-existing focused unit tests. Full results in
`docs/VECTOR_RECOVERY_VALIDATION.md`.

### 8. Sprint 4D benchmark final hardening

External review of the Sprint 4D benchmark required three fixes before a Windows run could
even be attempted, all in `scripts/vector_benchmark.py`:

1. The script imported the POSIX-only `resource` module unconditionally at top level, which
   has no Windows build and would have crashed the script before it could run there at all.
   Now guarded with `try`/`except ImportError`; `_machine_info()`/`_peak_rss_kb()` degrade to
   `None` plus an explanatory `rss_measurement` string instead of raising, and no optional
   dependency (e.g. `psutil`) was added.
2. The original `G_hybrid_plus_related` metric only measured `retrieval.retrieve_from_primary()`
   on a Hybrid Primary result computed once, *outside* the timed loop — i.e.
   related-expansion overhead only, not genuine end-to-end `search --hybrid --related`
   latency. Kept (renamed `G_related_expansion_only`) and a new
   `H_hybrid_plus_related_end_to_end` metric added that calls `hybrid_search()` and
   `retrieve_from_primary()` together inside the same timed callable on every sample.
3. Synthetic `event_date` generation used hand-rolled month/day arithmetic that could produce
   invalid calendar dates (e.g. `2016-02-30`); replaced with `date + timedelta`, which always
   yields a valid, deterministic date for a given seed/count.

The original Linux benchmark run is kept in `docs/VECTOR_WINDOWS_BENCHMARK.md` as an
explicitly-relabeled historical record (its `G` column was related-expansion-only, not
end-to-end); a corrected Linux re-measurement with the fixed script was added alongside it.
The official Windows numbers now follow in their own section of that document — never merged
with the Linux figures.

### 9. Sprint 4D: Windows official benchmark and closeout

The official ExactScan benchmark completed on the Windows development machine. Windows
retrieval was roughly 2–3 times slower than the corrected Linux reference at the measured
10,000-Memory points. About 1,000 Memories remained comfortable/interactive; 10,000/384 was
correct but noticeably slow; 10,000/768 was unsuitable as the primary interactive backend.
`ExactScanBackend` remains the reference implementation, fallback, and small-Vault backend.
No hard-coded threshold was added because the intermediate range was not directly measured.

External review declared Sprint 4D and Phase 4 Vector Retrieval Core **GO / COMPLETE**.
Production activation remains pending on a production embedding provider, a production-scale
ANN/vector-index backend, and Japanese semantic retrieval quality evaluation.

## Next authorized task

Sprint 4D and Phase 4 Vector Retrieval Core are **GO / COMPLETE**. Stop at closeout; no Phase
5 or production activation work is authorized by this task.

The next production work requires separate authorization and includes selecting/implementing
a production embedding provider, selecting/implementing a production-scale ANN/vector-index
backend, and evaluating Japanese semantic retrieval quality. Do **not** begin `ask`,
Contradiction Detection, Memory Consolidation, smartphone integration, or Phase 5 without an
explicit instruction.

## Core invariants

- Markdown/Vault is the persistent source of truth.
- SQLite is a rebuildable index/cache.
- Raw Log original text is preserved.
- `reindex` must reconstruct derived SQLite state from Markdown.
- Recovery must not reclassify an already-established historical Memory outcome with a newer classifier.
- Crash/retry behavior must remain idempotent and consistent.
- Keep modules maintainable, responsibilities separated, and tests isolated from real user data.
- Do not modify `brain-twin/` without explicit instruction.
- Work on `brain-twin-dev` unless the user explicitly changes the branch policy.

## Shared handoff protocol

All agents must follow repository-root `AGENTS.md`.
Claude Code also has repository-root `CLAUDE.md` as its entry point.
Every completed task must append to `docs/WORKLOG.md` and update this file if the state above changed.
