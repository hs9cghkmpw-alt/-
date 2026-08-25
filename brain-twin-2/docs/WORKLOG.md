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
