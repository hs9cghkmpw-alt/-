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
  - Sprint 4D: **associative integration implemented** (Hybrid/Vector Primary connected to
    the existing 1-hop expansion via `retrieval.retrieve_from_primary()`); **the 10k-scale
    Windows benchmark and failure/recovery/migration validation have NOT been done** (this
    session runs in a Linux remote execution environment, not the actual Windows dev
    machine) — see below. External review pending for the implemented part.

## Last known good implementation

- Implementation commit: `cf28b4629c51245ff0ec880b58da97951f465b12`
- Commit title: `brain-twin-2: Sprint 4C final hardening`
- Local test count at that commit: **306 passed**
- GitHub Actions run: `32844409644`
- GitHub Actions result: **success** (headSha confirmed to match the pushed commit)
- This round's Sprint 4D associative-integration work (see `WORKLOG.md`) builds on top of
  this reviewed-pending baseline; see `WORKLOG.md` for the Sprint 4D commit once pushed.

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

**Not done this round** (explicitly out of reach in this session's Linux remote execution
environment, not the actual Windows dev machine): the 10k-scale Windows benchmark, and
failure/recovery/migration validation, both still listed under Sprint 4D in
`docs/VECTOR_SEARCH_DESIGN.md`. Design-value tuning and the Vector Search completion review
submission depend on those and have not started either.

## Next authorized task

**Sprint 4D associative integration implemented; external review pending.** The remaining
Sprint 4D items (10k-scale Windows benchmark, failure/recovery/migration validation, design
value tuning, Vector Search completion review submission) still need a real Windows dev
machine and have not been attempted.

Do **not** begin Sprint 4E-equivalent scope (or anything beyond finishing Sprint 4D) until
this implementation is reviewed and explicitly approved. Production embedding providers,
`SqliteVecBackend`, `ask`, Contradiction Detection, Memory Consolidation, and smartphone
integration remain out of scope.

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
