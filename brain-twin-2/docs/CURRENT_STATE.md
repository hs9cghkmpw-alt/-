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
  - Sprint 4B rebuildable embedding cache: **complete** (external review GO received; a
    remaining consistency race between the provider call and the canonical cache write was
    hardened as part of Sprint 4C, see below)
  - Sprint 4C vector + hybrid primary retrieval: **implemented; external review pending**

## Last known good implementation

- Implementation commit: `87f787d32c0838d5e30a9e424b6bb98bddeca7d0` (this round's Sprint 4C
  work builds on top of this reviewed Sprint 4B baseline; see `WORKLOG.md` for the Sprint 4C
  commit once pushed)
- Commit title: `brain-twin-2: harden embedding staging and validity`
- Local test count at that baseline: **232 passed**
- GitHub Actions run: `32811513632`
- GitHub Actions result: **success**

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
become searchable. Fixed by re-reading the Memory in a short transaction immediately before
the write and skipping the write (not raising) when the current content_hash no longer
matches; staging activation now also re-verifies `ready == total_active` immediately before
switching the active profile/backend, instead of trusting the loop's bookkeeping alone.

## Next authorized task

**Sprint 4C (vector + hybrid primary retrieval) implemented; external review pending.**

Do **not** begin Sprint 4D (Associative Retrieval integration) until this implementation is
reviewed and explicitly approved. Production embedding providers, `SqliteVecBackend`, `ask`,
Contradiction Detection, Memory Consolidation, and smartphone integration remain out of scope.

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
