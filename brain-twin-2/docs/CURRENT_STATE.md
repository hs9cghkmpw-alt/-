# Brain Twin 2 — Current State

Last updated: 2026-08-25

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
- Phase 4 — Vector Search:
  - Sprint 4A contracts / canonical cache / ExactScan / Windows storage spike: **complete**
  - Sprint 4B rebuildable embedding cache: **complete** (external review GO received)
  - Sprint 4C vector + hybrid primary retrieval: architecture / Vector Search / Hybrid RRF /
    lazy detail fetch / availability gate / CLI / handoff protocol reviewed and approved.
    **Final hardening implemented; external review pending** (see below).
  - Sprint 4D: **all planned validation implemented** — associative integration, CLI
    hardening, Windows benchmark (run as a Linux-environment substitute; see below),
    failure/recovery/migration/corruption validation. **External review pending.**
    Phase 4 Vector Retrieval Core: validated / complete pending external review.
    Production activation: pending (production embedding provider, production-scale vector
    backend decision, and Japanese retrieval quality evaluation remain outstanding).

## Last known good implementation

- Implementation commit: `d8e46d5779e118dc93f9dbf835a0968ba5182edc`
- Commit title: `brain-twin-2: Sprint 4D associative integration`
- Local test count at that commit: **310 passed**
- GitHub Actions run: `32878425146`
- GitHub Actions result: **success** (headSha confirmed to match the pushed commit)
- This round's Sprint 4D final validation work (CLI hardening, Windows/Linux-substitute
  benchmark, failure/recovery/migration/corruption validation; see `WORKLOG.md`) builds on
  top of this reviewed-pending baseline; see `WORKLOG.md` for this round's commit once pushed.

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

## Next authorized task

**Sprint 4D: all planned validation implemented; external review pending.**

Do **not** begin Sprint 4E-equivalent scope, a production embedding provider,
`SqliteVecBackend`, `ask`, Contradiction Detection, Memory Consolidation, or smartphone
integration until this implementation is reviewed and explicitly approved. A Windows-machine
re-run of the benchmark (this round's was an explicit Linux substitute) and, if the reviewer
wants it, a 100k-scale data point remain open follow-ups but are not blockers to review.

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
