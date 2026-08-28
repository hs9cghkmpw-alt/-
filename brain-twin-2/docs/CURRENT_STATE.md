# Brain Twin 2 — Current State

Last updated: 2026-08-28

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
  - production-scale ANN/vector backend is not implemented/selected;
  - Japanese semantic retrieval quality candidate evaluation has not yet been performed;
  - Production Vector Activation design received external review **GO** on 2026-08-27 after the
    review-fix commit `c8012c6311bfac8f8f68fdc5a7790d0eeed0a6ac`;
  - provisional pair remains pinned `Qwen/Qwen3-Embedding-0.6B` direct Sentence Transformers
    provider + rebuildable FAISS HNSW sidecar, subject to PA1 Japanese gold evaluation and Windows
    PA3 1k/10k/100k ANN gates;
  - PA1 model/backend-independent Japanese retrieval evaluation harness is **implemented;
    external review pending**. The seed fixture contains 36 synthetic Memories / 24 queries
    (15 dev / 9 blind), all required slices, and no real Vault data. Final quality corpus expansion
    toward 300–500 Memories / 120 queries and real candidate model runs remain deferred;
  - Design: `docs/PRODUCTION_VECTOR_ACTIVATION_DESIGN.md`; ADR draft:
    `docs/ADR_PRODUCTION_VECTOR_ACTIVATION.md`; PA1 harness:
    `docs/JAPANESE_RETRIEVAL_EVALUATION.md`.
  Phase 4 core completion does not mean the Vector Search product feature is production-ready.

## Last known good implementation

- Production retrieval-core implementation commit: `68ac6e420332bf87feecb47eb32b67cd84bd4016`
- Commit title: `brain-twin-2: close Sprint 4D after Windows benchmark`
- Local Windows tests: **321 passed, 1 skipped** (expected POSIX-only `resource` skip)
- GitHub Actions run: `33033340980`
- GitHub Actions result: **success** (`headSha` exactly matched the implementation commit)
- External review: Sprint 4D **GO / COMPLETE**; Phase 4 Vector Retrieval Core
  **GO / COMPLETE**.
- PA1 evaluation harness is a separate evaluation-only implementation currently awaiting external
  review and must not be treated as production activation.

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

Final hardening: the commit-chunk write path issues `BEGIN IMMEDIATE` *before* the
re-verification read, so the read-verify-write sequence for canonical cache + backend
`sync_upsert` runs inside one held write lock, with no gap a second writer could use. The provider
call stays outside the transaction. Exceptions roll back the chunk and leave the item for the next
`sync()`; staging activation re-verifies `ready == total_active` immediately before switching.

### 4. Sprint 4C: deterministic lexical tie-break for Hybrid ranking

`db.search_lexical_candidates()` (the Hybrid-only pure-BM25 API) now uses explicit
`ORDER BY score ASC, m.id ASC`, so tied BM25 candidates have deterministic `lexical_rank` and RRF
fusion. `db.search()` / `search.search()` (plain-search backward-compat path) are unchanged.

### 5. Sprint 4D: connect Hybrid/Vector Primary to Associative Retrieval

`retrieval.retrieve_from_primary()` accepts any Primary result exposing `memory_id`, allowing plain,
Vector, and Hybrid Primary results to use the same one-hop outgoing+incoming associative expansion.
The CLI supports `--vector --related` and `--hybrid --related` without silent lexical fallback.

### 6. Sprint 4D: CLI hardening for negative `--related-limit`

`_cmd_search` validates a negative `--related-limit` before provider/vector work starts, returning a
clear error and printing no partial Primary results.

### 7. Sprint 4D: recovery/migration/corruption validation

Provider partial-failure resume, profile-switch failure preserving the old active generation,
backend-only recovery, stale/inactive exclusion, full SQLite deletion + Vault reindex + resync,
combined legacy schema self-heal, and malformed/corrupt cache rejection were validated with isolated
fixtures. Full details: `docs/VECTOR_RECOVERY_VALIDATION.md`.

### 8. Sprint 4D benchmark final hardening

`scripts/vector_benchmark.py` is Windows-portable (`resource` optional), distinguishes related-only
from true Hybrid+Related end-to-end timing, and generates valid deterministic dates. Corrected Linux
reference measurements and official Windows measurements are kept separate in
`docs/VECTOR_WINDOWS_BENCHMARK.md`.

### 9. Sprint 4D: Windows official benchmark and closeout

The official ExactScan benchmark completed on the Windows development machine. Windows retrieval was
roughly 2–3 times slower than the corrected Linux reference at the measured 10,000-Memory points.
About 1,000 Memories remained comfortable/interactive; 10,000/384 was correct but noticeably slow;
10,000/768 was unsuitable as the primary interactive backend. `ExactScanBackend` remains the
reference implementation, fallback, and small-Vault backend. No hard-coded threshold was added for
the unmeasured intermediate range.

External review declared Sprint 4D and Phase 4 Vector Retrieval Core **GO / COMPLETE**.
Production activation remains pending on a production embedding provider, production-scale ANN
backend, and Japanese semantic retrieval quality evidence.

### 10. Production activation design and PA1 evaluation harness

Production activation design received external review **GO** after four fixes: Qwen instruction
language is evaluated rather than preselected; FAISS HNSW physical identity/update semantics are
explicit; FAISS Windows packaging provenance is correctly distinguished; and sqlite-vec stable vs
experimental ANN status is separated.

PA1 then implemented an evaluation-only `brain_twin_eval/` package with strict synthetic dataset
validation, deterministic dataset hashing, Recall/MRR/nDCG/must-hit/explicit-hard-negative metrics,
per-slice + dev/blind aggregation, ANN-vs-Exact Recall@K, experiment manifests that do not persist raw
instruction text or secrets, JSON/Markdown reports, and thin adapters for the existing lexical,
Vector, and Hybrid APIs. Production `brain_twin/` does not import this package. No model, provider,
FAISS, or other ANN dependency was installed. PA1 is **external review pending**, not self-declared
GO/COMPLETE.

## Next authorized task

**External review of the PA1 Japanese Retrieval Evaluation Harness is next.** Do not begin real
Qwen/BGE/E5/Nomic/GTE model runs, PA2 production-provider implementation, PA3 ANN implementation,
PA4 integration, `ask`, Contradiction Detection, Memory Consolidation, smartphone integration, or
Phase 5 until explicitly authorized after review.

## Core invariants

- Markdown/Vault is the persistent source of truth.
- SQLite is a rebuildable index/cache.
- Raw Log original text is preserved.
- `reindex` must reconstruct derived SQLite state from Markdown.
- Recovery must not reclassify an already-established historical Memory outcome with a newer classifier.
- Crash/retry behavior must remain idempotent and consistent.
- Keep modules maintainable, responsibilities separated, and tests isolated from real user data.
- Evaluation-only code must not become a dependency of production `brain_twin/` runtime code.
- Do not modify `brain-twin/` without explicit instruction.
- Work on `brain-twin-dev` unless the user explicitly changes the branch policy.

## Shared handoff protocol

All agents must follow repository-root `AGENTS.md`.
Claude Code also has repository-root `CLAUDE.md` as its entry point.
Every completed task must append to `docs/WORKLOG.md` and update this file if the state above changed.
