# Brain Twin 2 — Work Log

This is the chronological handoff log shared by Claude Code, Codex, ChatGPT reviewers, and humans.

Rules:

- Append new entries at the end.
- Keep entries concise and factual.
- Do not paste full terminal transcripts.
- Do not store secrets, tokens, passwords, OAuth codes, `.env` contents, or unnecessary sensitive personal data.
- `CURRENT_STATE.md` is the current snapshot; this file is the history.

---

## 2026-08-25 — ChatGPT — Establish shared agent handoff protocol

- Branch: `brain-twin-dev`
- Base: `bfc679d8c13d549a637319af672a118d271f2f79`
- Scope: Establish a repository-based handoff protocol so Claude Code, Codex, ChatGPT, and humans read the same project state before work and leave the next agent a durable record afterward.
- Changed:
  - added repository-root `AGENTS.md` as the agent-neutral operating agreement
  - added repository-root `CLAUDE.md` as the Claude Code entry point that delegates to `AGENTS.md`
  - added `brain-twin-2/docs/CURRENT_STATE.md` as the compact current-phase/blocker/next-step snapshot
  - added this `brain-twin-2/docs/WORKLOG.md` as the chronological handoff log
  - formalized startup, single-writer, maintainability, security, completion, CI, and review rules
- Application code: unchanged
- Last verified tests before this documentation-only handoff commit: `117 passed`
- Last verified CI before this documentation-only handoff commit: GitHub Actions run `32797928602`, `success`
- Commit: this handoff/bootstrap commit (see Git history)
- Known issues: Phase 3 Retrieval still has two review hardening items documented in `CURRENT_STATE.md`: persisted link strength and lightweight Related-candidate retrieval before full body loading.
- Next: complete those two Phase 3 hardening fixes; do not start Vector Search yet.

## 2026-08-25 — Codex — Phase 3 Retrieval hardening

- Branch: `brain-twin-dev`
- Base: `bfc679d8c13d549a637319af672a118d271f2f79`（共有handoff commit `31dbc3e` をrebaseで保持）
- Scope: Link生成時strengthの永続化・復元・ranking利用と、大量Related候補の本文遅延取得。
- Changed: Markdown/SQLiteへ実strengthを保存し、legacyは一律`0.25`で非破壊移行。軽量candidateをrank/dedupeしてからtop N詳細だけ取得。
- Tests: local `123 passed`; CLI process/search --related/reindex再検索とstrength完全一致を確認。
- CI: GitHub Actions run `32801919294`, `success`。
- Commit: this commit
- Known issues: Vector Search等の後続Phaseは未実装。
- Next: CIとレビューでPhase 3完了確認後、別タスクでVector Search。

## 2026-08-25 — Codex — Vector Search design

- Branch: `brain-twin-dev`
- Base: `7a66260cb2319c6d7a9d4229590b506c0171d94b`
- Scope: Vector Searchの設計レビュー文書作成のみ。アプリケーション実装は行わない。
- Changed: `docs/VECTOR_SEARCH_DESIGN.md`を追加し、provider/backend分離、再構築可能cache、hybrid ranking、reindex、migration、Windows/offline経路、Sprint案を記録。
- Tests: application code unchanged; documentation diff checks only.
- CI: push後に確認予定。
- Commit: this commit
- Known issues: 設計文書の未解決事項はレビュー待ち。
- Next: **Vector Search design review pending**。

## 2026-08-25 — Codex — Vector Search design review fixes

- Branch: `brain-twin-dev`
- Base: `ceaf20db895554c8b223829a5f2ebca1b0651529`
- Scope: Vector Search設計の4レビュー指摘のみ修正。アプリケーション実装・sqlite-vec導入は行わない。
- Changed: user configをEmbedding構成の正本にし、profile/backend schemaを分離。revision非公開時のprofile_epochを必須化し、Hybridをpure lexical/vector → RRF → metadata 1回に明確化。
- Tests: application code unchanged; documentation diff checks only.
- CI: push後に確認予定。
- Commit: this commit
- Known issues: 外部設計レビュー待ち。GO/完了判断は未実施。
- Next: **Vector Search design review fixes implemented; external review pending**。

## 2026-08-25 — Codex — Vector Search Sprint 4A

- Branch: `brain-twin-dev`
- Base: `205f3c384bc4db65bb9199aad7a2a020de1765bd`
- Scope: provider/profile/backend contracts、canonical document/float32 cache、SQLite schema migration、ExactScan reference backend、Windows sqlite-vec spike。
- Changed: provider SDK非依存contractとtyped errors、backend非依存fingerprint、canonical document/hash/BLOB validation、4 embedding tables、active vectorだけのexact cosine searchを追加。
- Spike: Windows AMD64 / Python 3.12.10 / SQLite 3.49.1 / sqlite-vec 0.1.9でload/vec0/float32/cosine KNN/delete+insert/delete/rebuildをPASS。core requirementsには未追加。
- Tests: 既存123件を維持し、Sprint 4A contract/storage tests 40件を追加。local `163 passed`。
- CI: push後に確認予定。
- Known issues: production provider、SqliteVecBackend本番adapter、sync/invalidation、Vector/Hybrid Searchは未実装。
- Next: **Sprint 4A implemented; external review pending**。Sprint 4BへはレビューGO前に進まない。

## 2026-08-25 — Codex — Vector Search Sprint 4A final hardening

- Branch: `brain-twin-dev`
- Base: `c12d01981190edf7cbe01f58377b051d6dd87c2b`
- Scope: plaintext credential key検出強化とVectorIndexBackend mutation lifecycle明確化のみ。
- Changed: separator/camelCaseをtoken化してnested/unknown fieldのcredential名を拒否。Backend APIを`sync_upsert` / `sync_delete` / `clear_index`へ変更し、canonical cacheを変更しない派生index操作として明文化。
- Tests: 既存163件を維持し、hardening cases 17件を追加。local `180 passed`。
- CI: push後に確認予定。
- Commit: this commit。
- Known issues: production provider、SqliteVecBackend、embedding orchestration、Vector/Hybrid Searchは未実装。
- Next: **Sprint 4A hardening implemented; external review pending**。Sprint 4Bへは進めない。

## 2026-08-25 — Codex — Vector Search Sprint 4B

- Branch: `brain-twin-dev`
- Base: `368f0684f0eff0b1e739e676c445e1a848f53a05`
- Scope: rebuildable embedding cache orchestration、resume/profile switch、管理CLI。Vector/Hybrid Searchは対象外。
- Changed: keyset repository、中央batch/retry policy、missing/stale sync、commit単位partial progress、build成功後active切替、backend-only rebuild、`embeddings status/sync/rebuild`を追加。credential検出へcompact API/private keyを追加。
- Tests: 既存180件を維持し、Sprint 4B cases 40件を追加。local `220 passed`。
- CI: push後に確認予定。
- Commit: this commit。
- Known issues: production providerとSqliteVecBackendは未実装。Primary Vector/Hybrid SearchはSprint 4C以降。
- Next: **Sprint 4B implemented; external review pending**。Sprint 4Cへは進めない。

## 2026-08-25 — Codex — Vector Search Sprint 4B final hardening

- Branch: `brain-twin-dev`
- Base: `1978228a1a62d12c606343915476e9d94c1756ac`
- Scope: staging profileのactive index隔離とstale embedding検索除外のみ。
- Changed: active/backend ready判定をrepositoryへ集約し、stagingはcanonical-only、同一active+readyだけincremental同期。title/content update triggerでcacheをinvalid化し、ExactScanはvalid rowのみをtop-K前に取得。
- Tests: 既存220件を維持し、hardening cases 12件を追加。local `232 passed`。
- CI: push後に確認予定。
- Commit: this commit。
- Known issues: SqliteVecBackend/production provider/Vector・Hybrid Searchは未実装。
- Next: **Sprint 4B hardening implemented; external review pending**。Sprint 4Cへは進めない。

## 2026-08-25 — Claude Code — Sprint 4C vector + hybrid primary retrieval

- Branch: `brain-twin-dev`
- Base: `87f787d32c0838d5e30a9e424b6bb98bddeca7d0`
- Scope: ユーザーの明示指示（Sprint 4B external review GO / COMPLETE、Sprint 4Cの着手許可）に基づき着手。Sprint 4Cとして pure lexical candidate API、Vector Primary Search、Hybrid Primary Search (weighted RRF)、metadata multiplier共通化、top N後だけのdetail取得、diagnostic component scores、CLI opt-in (`--vector`/`--hybrid`) を実装。Associative Retrievalとの統合(Sprint 4D)、SqliteVecBackend本番adapter、production embedding providerは対象外のまま。
- Also fixed (identified in the same instruction, ahead of Sprint 4C proper): a consistency race in `EmbeddingService.sync()` where a Memory title/content change during the (potentially slow) provider call could let a stale vector be written as `is_valid=1`. Fixed by re-verifying `content_hash` against a fresh Memory read in a short transaction immediately before the write (skip, don't raise, on mismatch — reprocessed by the next sync), and by re-checking `ready == total_active` immediately before staging activation instead of trusting the loop's own bookkeeping.
- Changed:
  - `brain_twin/embedding_service.py`, `brain_twin/embedding_repository.py` (`memories_by_ids`), `brain_twin/embedding_provider.py` (`VectorSearchUnavailableError`): consistency-race hardening.
  - `brain_twin/db.py`: `search_lexical_candidates` (pure BM25, no metadata), `memory_ranking_signals_by_ids` (lightweight importance/confidence/event_date for the full Hybrid candidate union), `memory_result_details_by_ids` (full display detail, fetched only for the final top N).
  - `brain_twin/retrieval_weights.py` (new): `metadata_multiplier`/`recency_weight`/`RetrievalWeights`/`MIN_QUERY_LENGTH`, shared by `search.py` and `hybrid_search.py` so the formula exists in exactly one place and is applied exactly once.
  - `brain_twin/search.py`: refactored onto `retrieval_weights.py` with an injectable `now` for characterization testing; public behavior (score formula, order, limit, short-query, no embedding-config dependency) is unchanged and pinned by `tests/test_search.py`.
  - `brain_twin/vector_search.py` (new): availability gate (active profile + backend id/schema/indexed-profile/ready all match), query embedding validation, `vector_search()` with lazy top-K detail fetch.
  - `brain_twin/hybrid_search.py` (new): pure lexical + pure vector candidate union, Weighted Reciprocal Rank Fusion, metadata multiplier applied once after fusion, deterministic tie-break (final_score desc, best channel rank asc, event_date desc, memory_id asc), lazy top-N detail fetch.
  - `brain_twin/cli.py`: `search --vector` / `search --hybrid` (mutually exclusive via argparse), explicit rejection of `--related` combined with either, capability-unavailable surfaces as a clear `[NG]` error (no silent lexical fallback), `--verbose` diagnostic component scores. Plain `search` is unchanged.
  - `AGENTS.md`: added Section 2 "Authority and stale handoff documents" (explicit user GO/COMPLETE/authorization outranks a stale `CURRENT_STATE.md`/`WORKLOG.md` status, with explicit exceptions for ambiguity/scope mismatch/destructive ops/failing CI/safety conflicts/uncertain authorization); subsequent sections renumbered 3–10. `CLAUDE.md` now references this rule.
- Tests: existing 232 kept unchanged; 66 new (race-condition, lexical candidate, search characterization, Vector, Hybrid, CLI). Local `298 passed`.
- CI: verified against the pushed commit SHA specifically (not just "latest run on branch"); see commit line below.
- Commit: this commit.
- Known issues: `SqliteVecBackend` production adapter and a real embedding provider are still not implemented (`ExactScanBackend` + fake/recording providers only); `--vector`/`--hybrid` therefore return a clear "provider is not installed"-style error outside tests until a production provider lands. `--related` cannot yet be combined with `--vector`/`--hybrid` (planned for Sprint 4D). The Sprint 4C implementation itself is unreviewed.
- Next: **Sprint 4C (vector + hybrid primary retrieval) implemented; external review pending.** Do not begin Sprint 4D until this is reviewed and explicitly approved.

## 2026-08-25 — Claude Code — Sprint 4C final hardening

- Branch: `brain-twin-dev`
- Base: `063c3a60beb30a7d6cc7f2191ea780869f177d7f`
- Scope: user-instructed hardening on top of a Sprint 4C implementation that was reviewed and approved on architecture (Vector Search / Hybrid RRF / lazy detail fetch / availability gate / CLI / handoff protocol). Three fixes only; no Sprint 4D scope.
- Changed:
  1. **Fully atomic embedding consistency race close** (`brain_twin/embedding_service.py`): the prior round's fix re-read current Memory content right before writing `is_valid=1`, but that re-read was a plain `SELECT` — it did not itself hold the write lock, leaving a narrower race window between the re-read and the write where a second writer could still commit a change. Each commit-chunk write now issues `BEGIN IMMEDIATE` *before* the re-verification read (guarded against a redundant `BEGIN` if already mid-transaction), so canonical cache write + backend `sync_upsert` run inside one held write lock with no gap. The provider call itself remains outside any transaction. Any exception rolls back the whole chunk; the item is reprocessed by the next `sync()`.
  2. **Deterministic lexical tie-break for Hybrid** (`brain_twin/db.py`): `search_lexical_candidates()` (Hybrid-only pure-BM25 API) now orders `ORDER BY score ASC, m.id ASC` instead of `ORDER BY score` alone, so tied `bm25()` scores no longer leave `lexical_rank` (and therefore RRF fusion / best-channel tie-break) non-deterministic. `db.search()` / `search.search()` (plain-search backward-compat path) are unchanged.
  3. **Exact-SHA CI verification in `AGENTS.md`** (Section 7): replaced the "latest run on branch" `gh run list --limit 1` example with a loop that polls for the run whose `headSha` matches `git rev-parse HEAD`, and requires confirming that match before citing the run as evidence of CI success/failure.
- Tests: existing 298 kept unchanged; 8 new (`test_embedding_service.py`: write-transaction-held contract test, a genuine second-connection lock-conflict test with `timeout=0` — no sleep/threads, hash-mismatch-skips-`sync_upsert`, canonical-write+backend-sync share one transaction, exception-rolls-back-canonical-write; `test_search.py`: lexical tie-break by `memory_id` ascending, stability across repeated calls, stability across `reindex`). Local `306 passed`.
- CI: verified against the pushed commit SHA specifically (`headSha` match required before reporting); see commit line below.
- Commit: this commit.
- Known issues: same as the prior entry — `SqliteVecBackend` production adapter and a real embedding provider are still not implemented; `--related` still cannot combine with `--vector`/`--hybrid` (Sprint 4D). This hardening round itself is unreviewed.
- Next: **Sprint 4C final hardening implemented; external review pending.** Do not begin Sprint 4D until this is reviewed and explicitly approved.
